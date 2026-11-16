"""Board-sice extensions for qickodes.

Runs inside the Pyro server on the RFSoC (PYNQ's Python), so it depends only on
numpy and qick. Start the server with ``soc_class=QickodesSoc``.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from qick import QickSoc

# Bump when a method signature or behaviour changes; the client checks it.
BOARD_API_VERSION = 1

# DDR4 completion sentinel: I = Q = -32768, packed into one 32-bit word.
_SENTINEL = np.uint32(0x80008000)
# Sentinel samples at the end of the record (even, keeps 64-bit alignment).
_SENTINEL_LEN = 8
# Refuse to send more than this over Pyro in one call.
_MAX_RETURN_BYTES = 512 * 2**20


class QickodesSoc(QickSoc):
    """QickSoc with DDR4 helpers that keep raw records on the board."""

    def qickodes_board_api_version(self) -> int:
        return BOARD_API_VERSION

    def _ddr4_record_end(self, nt: int) -> int:
        end = nt * self["ddr4_buf"]["burst_len"]
        if end > self["ddr4_buf"]["maxlen"]:
            msg = f"nt={nt} transfers exceed the DDR4 memory"
            raise ValueError(msg)
        return end

    def arm_ddr4_with_sentinel(self, ch: int, nt: int) -> None:
        """Mark the end of the record with a sentinel, then arm the DDR4 buffer."""
        end = self._ddr4_record_end(nt)
        np.copyto(self.ddr4_buf.ddr4_array[end - _SENTINEL_LEN : end], _SENTINEL)
        self.arm_ddr4(ch, nt)

    def ddr4_record_done(self, nt: int) -> bool:
        """Return True once the last samples of the record have been written."""
        end = self._ddr4_record_end(nt)
        tail = self.ddr4_buf.ddr4_array[end - _SENTINEL_LEN : end].copy()
        return not bool(np.all(tail == _SENTINEL))

    def get_ddr4_decimated(
        self,
        nt: int,
        factor: int,
        chunk_samples: int = 1 << 22,
        n_threads: int | None = None,
    ) -> np.ndarray:
        """Boxcar-average the DDR4 record of nt transfers on the board.

        Covers the same samples as get_ddr4(nt). Returns the raw int16 array
        of shape (n, 2) for factor == 1, otherwise float32 means of consecutive
        blocks of `factor` samples; leftover samples at the end are dropped.
        Reading and averaging run in parallel on all CPU cores by default.
        """
        factor = int(factor)
        if factor < 1:
            msg = f"factor must be >= 1, got {factor}"
            raise ValueError(msg)
        start = self["ddr4_buf"].get("junk_len", 0)
        end = self._ddr4_record_end(nt)
        n_blocks = (end - start) // factor
        n_bytes = n_blocks * (4 if factor == 1 else 8)
        if n_bytes > _MAX_RETURN_BYTES:
            msg = f"result would be {n_bytes / 2**20:.0f} MiB; increase factor"
            raise ValueError(msg)
        if factor == 1:
            return self.get_ddr4(nt)

        mem = self.ddr4_buf.ddr4_array
        out = np.empty((n_blocks, 2), dtype=np.float32)
        blocks_per_chunk = max(1, chunk_samples // factor)
        # int32 sums are exact as long as factor * 32768 < 2**31
        sum_dtype = np.int32 if factor < 1 << 16 else np.int64

        def work(b0: int) -> None:
            b1 = min(b0 + blocks_per_chunk, n_blocks)
            s = start + b0 * factor
            e = start + b1 * factor
            # Copy a 64-bit aligned span (unaligned reads of the DDR4 mapping
            # can crash with SIGBUS, see qick's get_mem), then trim.
            buf = np.empty(e - s + s % 2 + e % 2, dtype=np.uint32)
            np.copyto(buf, mem[s - s % 2 : e + e % 2])
            iq = buf[s % 2 : s % 2 + (e - s)].view(np.int16).reshape(b1 - b0, factor, 2)
            # Summing I and Q separately gives numpy long inner loops; reducing
            # over the middle axis of (n, factor, 2) is several times slower.
            for k in (0, 1):
                out[b0:b1, k] = iq[..., k].sum(axis=1, dtype=sum_dtype) / factor

        with ThreadPoolExecutor(n_threads or os.cpu_count()) as pool:
            list(pool.map(work, range(0, n_blocks, blocks_per_chunk)))
        return out
