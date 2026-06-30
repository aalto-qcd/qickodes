from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Literal

from qcodes import Parameter
from qcodes.instrument import InstrumentModule
from qcodes.validators import Enum, MultiType, Numbers, Validator
from qick.asm_v2 import QickParam

if TYPE_CHECKING:
    from qcodes.instrument import InstrumentBase

    from qickodes.instrument_v2 import QickInstrument


class SweepableNumbers(Validator):
    def __init__(
        self,
        min_value: float = -float("inf"),
        max_value: float = float("inf"),
    ) -> None:
        self.numbers = Numbers(min_value, max_value)
        self._valid_values = (min_value, max_value)

    def validate(self, value: float | QickParam, context: str = ""):
        if isinstance(value, QickParam):
            self.numbers.validate(value.minval(), context)
            self.numbers.validate(value.maxval(), context)
        else:
            self.numbers.validate(value, context)


class SweepableParameter(Parameter):
    """Hardware-sweepable parameter. Corresponds to qick.asm_v2.QickParam."""

    qick_param: QickParam | Literal["auto"]

    def __init__(
        self,
        name: str,
        instrument: InstrumentBase,
        label: str,
        unit: str,
        initial_value: float,
        min_value: float = -float("inf"),
        max_value: float = float("inf"),
        allow_auto: bool = False,
        **kwargs,
    ) -> None:
        # get parent of parent until a QickInstrument is reached
        inst = instrument
        while isinstance(inst, InstrumentModule):
            inst = inst.parent
        self.qick_instrument: QickInstrument = inst

        if allow_auto:
            validator = MultiType(SweepableNumbers(min_value, max_value), Enum("auto"))
        else:
            validator = SweepableNumbers(min_value, max_value)

        super().__init__(
            name=name,
            instrument=instrument,
            label=label,
            unit=unit,
            vals=validator,
            initial_value=initial_value,
            **kwargs,
        )

    def set_raw(self, value: float | QickParam | Literal["auto"]) -> None:
        if isinstance(value, (float, int)):
            # convert scalar value to QickParam
            self.qick_param = QickParam(value)
        else:
            self.qick_param = value

        # keep track of all swept parameters of the instrument
        if isinstance(value, QickParam) and value.is_sweep():
            self.qick_instrument.swept_params.add(self)
        elif self in self.qick_instrument.swept_params:
            self.qick_instrument.swept_params.remove(self)

    def get_raw(self) -> float | QickParam | Literal["auto"]:
        value = self.qick_param

        if isinstance(value, QickParam):
            # if available, get the actual value after rounding to the hardware resolution
            with contextlib.suppress(RuntimeError):
                value = value.get_rounded()

            # convert scalar QickParam to float
            if not value.is_sweep():
                value = value.start

        return value
