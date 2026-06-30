"""Unit tests for the tproc v1 sweep logic in qickodes.protocol_base.

These tests run without the hardware. They cover just the logic of
SoftwareSweep, which is purely pythonic.
"""

import numpy as np
import pytest
from qcodes import ManualParameter

from qickodes.protocol_base import SoftwareSweep


def _param(unit: str = "") -> ManualParameter:
    return ManualParameter("p", unit=unit)


def test_triplet_start_stop():
    sweep = SoftwareSweep(_param(), 0, 1, 11)
    assert len(sweep.values) == 11
    assert sweep.values[0] == 0
    assert sweep.values[-1] == 1


def test_numpy_linspace_input():
    sweep = SoftwareSweep(_param(), np.linspace(0, 1, 21))
    assert len(sweep.values) == 21
    np.testing.assert_allclose(np.asarray(sweep.values)[[0, -1]], [0, 1])


def test_skip_first_and_last():
    sweep = SoftwareSweep(
        _param(), np.linspace(0, 1, 21), skip_first=True, skip_last=True
    )
    assert len(sweep.values) == 19
    assert sweep.values[0] == pytest.approx(0.05)
    assert sweep.values[-1] == pytest.approx(0.95)


def test_multiple_parameters_share_units():
    a = ManualParameter("a", unit="Hz")
    b = ManualParameter("b", unit="Hz")
    sweep = SoftwareSweep([a, b], 0, 1, 5)
    assert sweep.parameters == [a, b]


def test_mismatched_units():
    a = ManualParameter("a", unit="Hz")
    b = ManualParameter("b", unit="V")
    with pytest.raises(AssertionError):
        SoftwareSweep([a, b], 0, 1, 5)
