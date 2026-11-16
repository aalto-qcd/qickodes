"""Per-run netCDF file for DDR4 records.

The file mirrors a QCoDeS dataset of a ``"decimated"`` run: one complex data
variable ``iq`` with one dimension per software sweep plus ``time`` (s), so
``xr.open_dataarray(path, engine="h5netcdf")`` reads both kinds of data the
same way. The time coordinate is stored once per run as sample indices scaled
by ``dt`` plus ``t0`` (CF ``scale_factor`` and ``add_offset``), which xarray
decodes to seconds on reading.
"""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import h5netcdf
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from qickodes.instrument_v2 import SoftwareSweep

_NAT = np.iinfo(np.int64).min  # fill value of `acquired_at`, decoded as NaT


@contextmanager
def _complex_allowed() -> Iterator[None]:
    # Complex data is an h5netcdf extension of netCDF-4 (as in QCoDeS's own
    # exports); h5netcdf warns about it on every flush.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="You are writing invalid netcdf features"
        )
        yield


class Ddr4File:
    """Preallocated file that DDR4 records are written into one by one.

    Records that were never written (e.g. after an interrupted run) read as
    NaN, with ``acquired_at`` NaT.
    """

    def __init__(
        self,
        path: str | Path,
        software_sweeps: Sequence[SoftwareSweep],
        num_samples: int,
        dt: float,
        t0: float,
        attrs: Mapping[str, Any],
        chunk_samples: int = 1 << 20,
    ) -> None:
        self.path = Path(path)
        self.num_samples = num_samples
        self._file = h5netcdf.File(self.path, "w", invalid_netcdf=True)

        sweep_dims = []
        extra_coords = []
        for sweep in software_sweeps:
            dim = sweep.parameters[0].full_name
            sweep_dims.append(dim)
            self._file.dimensions[dim] = len(sweep.values)
            for parameter in sweep.parameters:
                coord = self._file.create_variable(
                    parameter.full_name, (dim,), data=np.asarray(sweep.values)
                )
                coord.attrs["long_name"] = parameter.label
                coord.attrs["units"] = parameter.unit
                if parameter is not sweep.parameters[0]:
                    extra_coords.append(parameter.full_name)

        # Time axis as scaled sample indices: decoded to seconds by xarray,
        # and the integer ramp compresses to a few MiB per run
        self._file.dimensions["time"] = num_samples
        chunk = min(num_samples, chunk_samples)
        index_dtype = np.int32 if num_samples < 2**31 else np.int64
        time = self._file.create_variable(
            "time",
            ("time",),
            data=np.arange(num_samples, dtype=index_dtype),
            chunks=(chunk,),
            compression="gzip",
            shuffle=True,
        )
        time.attrs["scale_factor"] = float(dt)
        time.attrs["add_offset"] = float(t0)
        time.attrs["long_name"] = "Time"
        time.attrs["units"] = "sec"

        acquired_at = self._file.create_variable(
            "acquired_at", tuple(sweep_dims), dtype=np.int64, fillvalue=_NAT
        )
        acquired_at.attrs["long_name"] = "End of the record's acquisition"
        acquired_at.attrs["units"] = "nanoseconds since 1970-01-01"

        iq = self._file.create_variable(
            "iq",
            (*sweep_dims, "time"),
            dtype=np.complex64,
            chunks=(1,) * len(sweep_dims) + (chunk,),
            fillvalue=np.complex64(np.nan + 1j * np.nan),
        )
        iq.attrs["long_name"] = "iq"
        iq.attrs["units"] = "ADC units"
        iq.attrs["coordinates"] = " ".join([*extra_coords, "acquired_at"])

        self._file.attrs.update({k: v for k, v in attrs.items() if v is not None})
        self._file.attrs["dt"] = float(dt)
        with _complex_allowed():
            self._file.flush()

    def write(
        self, indices: Sequence[int], iq: np.ndarray, acquired_at_ns: int
    ) -> None:
        """Write one record (I/Q pairs, shape (num_samples, 2)) at the sweep indices."""
        if len(iq) != self.num_samples:
            msg = (
                f"The record has {len(iq)} samples, but {self.path.name} was created "
                f"for {self.num_samples}. DDR4 settings must not change during a run."
            )
            raise ValueError(msg)
        index = tuple(indices)
        self._file["iq"][(*index, slice(None))] = (iq[:, 0] + 1j * iq[:, 1]).astype(
            np.complex64
        )
        self._file["acquired_at"][index] = acquired_at_ns
        with _complex_allowed():
            self._file.flush()

    def close(self) -> None:
        with _complex_allowed():
            self._file.close()

    def __enter__(self) -> Self:
        """Return the file for use in a ``with`` statement."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the file when the ``with`` block ends."""
        self.close()
