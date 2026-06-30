"""Units tests for the tproc v2 sweep logic in qickodes.

These tests cover `SoftwareSweep', `SweepableNumbers' validator, and
the `SweepableParameter' get/set behaviour.
"""

import numpy as np
import pytest
from qcodes import Instrument, ManualParameter
from qick.asm_v2 import QickSweep1D

from qickodes.instrument_v2 import SoftwareSweep
from qickodes.parameters_v2 import SweepableNumbers, SweepableParameter


# SoftwareSweep tests
def _param(unit: str = "") -> ManualParameter:
    return ManualParameter("p", unit=unit)


def test_software_sweep_triplet_start_stop():
    sweep = SoftwareSweep(_param(), 0, 1, 11)
    assert len(sweep.values) == 11
    assert sweep.values[0] == 0
    assert sweep.values[-1] == 1


def test_software_sweep_numpy_linspace_input():
    sweep = SoftwareSweep(_param(), np.linspace(0, 1, 21))
    assert len(sweep.values) == 21
    np.testing.assert_allclose(np.array(sweep.values)[[0, -1]], [0, 1])


def test_software_sweep_skip_first_and_last():
    sweep = SoftwareSweep(
        _param(), np.linspace(0, 1, 21), skip_first=True, skip_last=True
    )
    assert len(sweep.values) == 19
    assert sweep.values[0] == pytest.approx(0.05)
    assert sweep.values[-1] == pytest.approx(0.95)


def test_software_sweep_multiple_parameters_share_units():
    a = ManualParameter("a", unit="Hz")
    b = ManualParameter("b", unit="Hz")
    sweep = SoftwareSweep([a, b], 0, 1, 5)
    assert sweep.parameters == [a, b]


def test_software_sweep_mismatched_units():
    a = ManualParameter("a", unit="Hz")
    b = ManualParameter("b", unit="V")
    with pytest.raises(AssertionError):
        SoftwareSweep([a, b], 0, 1, 5)


# SweepableNumbers validator tests
def test_sweepable_numbers_accepts_scalar_in_range():
    SweepableNumbers(0, 10).validate(5.0)  # should not raise


def test_sweepable_numbers_rejects_scalar_out_of_range():
    with pytest.raises(ValueError, match="must be between"):
        SweepableNumbers(0, 10).validate(20.0)


def test_sweepable_numbers_accepts_sweep_within_range():
    SweepableNumbers(0, 10).validate(QickSweep1D("loop", 2.0, 8.0))


def test_sweepable_numbers_rejects_sweep_exceeding_range():
    with pytest.raises(ValueError, match="must be between"):
        SweepableNumbers(0, 10).validate(QickSweep1D("loop", 2.0, 50.0))


# SweepableParameter tests: create a fake hardware to run these tests.
class FakeQickInstrument(Instrument):
    """Hardware-free replacement for `QickInstrument`."""

    def __init__(self, name: str):
        super().__init__(name)
        self.swept_params: set = set()


@pytest.fixture
def instrument():
    inst = FakeQickInstrument("fake")
    yield inst
    inst.close()


def _sweepable(inst: Instrument) -> SweepableParameter:
    return SweepableParameter(
        name="freq",
        instrument=inst,
        label="Frequency",
        unit="Hz",
        initial_value=5.0,
        min_value=0,
        max_value=10,
    )


def test_sweepable_parameter_initial_value(instrument):
    p = _sweepable(instrument)
    assert p.get() == 5.0


def test_sweepable_parameter_scalar_set_not_tracked(instrument):
    p = _sweepable(instrument)
    p.set(7.0)
    assert p.get() == 7.0
    assert p not in instrument.swept_params


def test_sweepable_parameter_sweep_set_is_tracked(instrument):
    p = _sweepable(instrument)
    p.set(QickSweep1D("loop", 4.0, 7.0))
    assert p in instrument.swept_params


def test_sweepable_parameter_scalar_after_sweep_is_untracked(instrument):
    p = _sweepable(instrument)
    p.set(QickSweep1D("loop", 4.0, 7.0))
    assert p in instrument.swept_params
    # Switching back to a scalar should remove it from the sweep object
    p.set(3.0)
    assert p not in instrument.swept_params


def test_sweepable_parameter_rejects_out_of_range(instrument):
    p = _sweepable(instrument)
    with pytest.raises(ValueError, match="must be between"):
        p.set(70.0)
