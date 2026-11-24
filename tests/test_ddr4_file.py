"""Unit tests for the per-run DDR4 file (qickodes.ddr4_file).

These tests run without hardware: they write records with `Ddr4File` and
read them back with xarray, as an analysis script would.
"""

import numpy as np
import pytest
import xarray as xr
from qcodes.parameters import ManualParameter

from qickodes.ddr4_file import Ddr4File
from qickodes.instrument_v2 import SoftwareSweep

# An example DDR4 rate and block length (those of the RFSoC 4x2). The file
# only stores dt and t0, so the rate does not matter except for the time axis,
# which is tested with each board's values below.
FS = 552.96e6
N_BLOCK = 283
DT = N_BLOCK / FS
T0 = (N_BLOCK - 1) / 2 / FS
N_SAMPLES = 1000


def _record(value: float) -> np.ndarray:
    """Return a record of I/Q pairs with I = value and Q = -value."""
    iq = np.empty((N_SAMPLES, 2), dtype=np.float32)
    iq[:, 0] = value
    iq[:, 1] = -value
    return iq


@pytest.fixture
def sweeps():
    repetition = ManualParameter("repetition", unit="")
    gain = ManualParameter("gain", label="Gain", unit="")
    gain_copy = ManualParameter("gain_copy", label="Gain copy", unit="")
    return [
        SoftwareSweep(repetition, np.arange(3)),
        SoftwareSweep([gain, gain_copy], [0.2, 0.4]),
    ]


def _write(path, sweeps, records):
    """Write {indices: (value, acquired_at_ns)} into a new file."""
    with Ddr4File(path, sweeps, N_SAMPLES, DT, T0, {"run_id": 7}) as file:
        for indices, (value, acquired_at_ns) in records.items():
            file.write(indices, _record(value), acquired_at_ns)


@pytest.mark.filterwarnings("error")
def test_reads_like_a_decimated_run(tmp_path, sweeps):
    path = tmp_path / "7.nc"
    _write(path, sweeps, {(0, 0): (1.0, 10), (2, 1): (2.0, 20)})

    iq = xr.open_dataarray(path, engine="h5netcdf")
    assert iq.name == "iq"
    assert iq.dims == ("repetition", "gain", "time")
    assert iq.shape == (3, 2, N_SAMPLES)
    assert np.iscomplexobj(iq.values)
    np.testing.assert_array_equal(iq.repetition, [0, 1, 2])
    np.testing.assert_array_equal(iq.gain, [0.2, 0.4])
    # second parameter of the same sweep is a coordinate on that dimension
    assert iq.gain_copy.dims == ("gain",)


def test_records_land_in_their_slots(tmp_path, sweeps):
    path = tmp_path / "7.nc"
    _write(path, sweeps, {(0, 0): (1.0, 10), (2, 1): (2.0, 20)})

    iq = xr.open_dataarray(path, engine="h5netcdf")
    np.testing.assert_array_equal(iq.sel(repetition=0, gain=0.2), 1 - 1j)
    np.testing.assert_array_equal(iq.sel(repetition=2, gain=0.4), 2 - 2j)


def test_unwritten_records_are_nan_and_nat(tmp_path, sweeps):
    path = tmp_path / "7.nc"
    _write(path, sweeps, {(0, 0): (1.0, 10)})

    iq = xr.open_dataarray(path, engine="h5netcdf")
    written = np.zeros((3, 2), dtype=bool)
    written[0, 0] = True
    assert not np.isnan(iq.values[written]).any()
    assert np.isnan(iq.values[~written]).all()
    acquired_at = iq.acquired_at.values
    assert acquired_at[0, 0] == np.datetime64(10, "ns")
    assert np.isnat(acquired_at[~written]).all()


@pytest.mark.parametrize(
    ("fs", "n_block"),
    [(552.96e6, 283), (307.2e6, 157), (307.2e6, 1)],
    ids=["rfsoc4x2", "zcu216", "raw"],
)
def test_time_axis_is_block_centres(tmp_path, fs, n_block):
    path = tmp_path / "7.nc"
    with Ddr4File(path, [], N_SAMPLES, n_block / fs, (n_block - 1) / 2 / fs, {}):
        pass

    time = xr.open_dataarray(path, engine="h5netcdf").time
    raw_times = np.arange(N_SAMPLES * n_block) / fs
    centres = raw_times.reshape(N_SAMPLES, n_block).mean(axis=1)
    np.testing.assert_allclose(time.values, centres, rtol=0, atol=1e-15)
    assert time.attrs["units"] == "sec"


def test_attributes(tmp_path):
    path = tmp_path / "7.nc"
    with Ddr4File(path, [], N_SAMPLES, DT, T0, {"run_id": 7, "guid": None}):
        pass

    attrs = xr.open_dataset(path, engine="h5netcdf").attrs
    assert attrs["run_id"] == 7
    assert attrs["dt"] == pytest.approx(DT)
    assert "guid" not in attrs  # None attributes are skipped


def test_without_software_sweeps(tmp_path):
    path = tmp_path / "7.nc"
    with Ddr4File(path, [], N_SAMPLES, DT, T0, {}) as file:
        file.write((), _record(3.0), 30)

    iq = xr.open_dataarray(path, engine="h5netcdf")
    assert iq.dims == ("time",)
    np.testing.assert_array_equal(iq, 3 - 3j)
    assert iq.acquired_at.values == np.datetime64(30, "ns")


def test_wrong_record_length_raises(tmp_path):
    with (
        Ddr4File(tmp_path / "7.nc", [], N_SAMPLES, DT, T0, {}) as file,
        pytest.raises(ValueError, match="DDR4 settings must not change"),
    ):
        file.write((), np.zeros((N_SAMPLES - 1, 2)), 0)
