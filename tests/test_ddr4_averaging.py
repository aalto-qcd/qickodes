"""Unit tests for DDR4 block averaging on the board and on the PC.

The board module (board/qickodes_board.py) runs on the RFSoC, so these tests
replace QickSoc with a fake that holds a simulated DDR4 memory and reads it
the way qick's DDR4 driver does. Board-side averaging, the PC-side fallback
and a plain reference average must agree exactly. Every test runs with the
DDR4 configuration of each supported board.
"""

import importlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import qick

from qickodes.instrument_v2 import Ddr4Buffer

MAXLEN = 1 << 20  # simulated DDR4 memory (samples), smaller than the real 2**30

# DDR4 configuration as reported in soccfg; both junk lengths are odd, so
# unaligned record starts are exercised
BOARDS = {
    "rfsoc4x2": {"burst_len": 256, "junk_len": 801, "sample_rate": 552.96e6},
    "zcu216": {"burst_len": 128, "junk_len": 401, "sample_rate": 307.2e6},
}


class FakeSoc:
    """Stand-in for QickSoc with a DDR4 memory of random samples."""

    board: dict  # set per board by the `board` fixture

    def __init__(self) -> None:
        rng = np.random.default_rng(0)
        memory = rng.integers(0, 2**32, MAXLEN, dtype=np.uint64).astype(np.uint32)
        self.ddr4_buf = SimpleNamespace(ddr4_array=memory)
        self.cfg = {
            "ddr4_buf": {
                "burst_len": self.board["burst_len"],
                "junk_len": self.board["junk_len"],
                "maxlen": MAXLEN,
            }
        }
        self.armed = None

    def __getitem__(self, key):
        """Return a configuration entry, like QickConfig."""
        return self.cfg[key]

    def arm_ddr4(self, ch, nt):
        self.armed = (ch, nt)

    def get_ddr4(self, nt, start=None):
        # Same semantics as qick's AxisBufferDdrV1.get_mem
        burst, junk = self.board["burst_len"], self.board["junk_len"]
        if start is None:
            start, end = junk, nt * burst
        else:
            end = start + nt * burst
        memory = self.ddr4_buf.ddr4_array
        copy = memory[start - start % 2 : end + end % 2].copy()
        return copy[start % 2 : start % 2 + end - start].view(np.int16).reshape(-1, 2)


@pytest.fixture(params=BOARDS.values(), ids=BOARDS.keys())
def board(request, monkeypatch):
    """Return the board module, built on a FakeSoc with one board's DDR4 configuration."""
    soc_class = type("FakeSoc", (FakeSoc,), {"board": request.param})
    monkeypatch.setattr(qick, "QickSoc", soc_class, raising=False)
    sys.modules.pop("board.qickodes_board", None)
    module = importlib.import_module("board.qickodes_board")
    yield module
    sys.modules.pop("board.qickodes_board", None)


def _reference(soc, nt, factor):
    raw = soc.get_ddr4(nt).astype(np.int64)
    n = len(raw) // factor
    return (raw[: n * factor].reshape(n, factor, 2).sum(axis=1) / factor).astype(
        np.float32
    )


def _buffer(soc, nt=0, n_block=1):
    """Return a stand-in for Ddr4Buffer with just what its methods use."""
    return SimpleNamespace(
        parent=SimpleNamespace(soc=soc, soccfg=soc.cfg),
        num_transfers=SimpleNamespace(get=lambda: nt),
        n_block=SimpleNamespace(get=lambda: n_block),
        sample_rate=lambda: soc.board["sample_rate"],
    )


@pytest.mark.parametrize(
    ("nt", "factor"), [(4000, 283), (4000, 157), (4000, 256), (4095, 7), (4096, 70000)]
)
def test_board_average_matches_reference(board, nt, factor):
    soc = board.QickodesSoc()
    np.testing.assert_array_equal(
        soc.get_ddr4_decimated(nt, factor), _reference(soc, nt, factor)
    )


def test_board_average_independent_of_chunks_and_threads(board):
    soc = board.QickodesSoc()
    expected = soc.get_ddr4_decimated(4000, 283)
    for chunk_samples, n_threads in [(283, 1), (1000, 3), (1 << 16, 8)]:
        result = soc.get_ddr4_decimated(
            4000, 283, chunk_samples=chunk_samples, n_threads=n_threads
        )
        np.testing.assert_array_equal(result, expected)


def test_board_factor_one_returns_raw(board):
    soc = board.QickodesSoc()
    np.testing.assert_array_equal(soc.get_ddr4_decimated(100, 1), soc.get_ddr4(100))


@pytest.mark.parametrize("factor", [283, 157, 7])
def test_pc_fallback_matches_board(board, factor):
    soc = board.QickodesSoc()
    pc = Ddr4Buffer._decimate_on_pc(_buffer(soc), 4000, factor, chunk_samples=5000)  # noqa: SLF001
    np.testing.assert_array_equal(pc, soc.get_ddr4_decimated(4000, factor))


def test_num_samples_matches_fetched_length(board):
    soc = board.QickodesSoc()
    for nt, n_block in [(4000, 283), (4000, 157), (10, 1), (4095, 7)]:
        expected = len(soc.get_ddr4_decimated(nt, n_block))
        assert Ddr4Buffer.num_samples(_buffer(soc, nt, n_block)) == expected


def test_block_t0_is_centre_of_first_block(board):
    soc = board.QickodesSoc()
    rate = soc.board["sample_rate"]
    assert Ddr4Buffer.block_t0(_buffer(soc, n_block=283)) == pytest.approx(141 / rate)
    assert Ddr4Buffer.block_t0(_buffer(soc, n_block=1)) == 0


def test_sentinel_marks_record_completion(board):
    soc = board.QickodesSoc()
    nt = 100
    soc.arm_ddr4_with_sentinel(0, nt)
    assert soc.armed == (0, nt)
    assert not soc.ddr4_record_done(nt)
    # the hardware overwrites the end of the record when it is complete
    soc.ddr4_buf.ddr4_array[nt * soc.board["burst_len"] - 1] = 0
    assert soc.ddr4_record_done(nt)


def test_board_guards(board, monkeypatch):
    soc = board.QickodesSoc()
    with pytest.raises(ValueError, match="exceed the DDR4 memory"):
        soc.get_ddr4_decimated(MAXLEN // soc.board["burst_len"] + 1, 283)
    with pytest.raises(ValueError, match="factor must be >= 1"):
        soc.get_ddr4_decimated(100, 0)
    monkeypatch.setattr(board, "_MAX_RETURN_BYTES", 1024)
    with pytest.raises(ValueError, match="increase factor"):
        soc.get_ddr4_decimated(4000, 7)
