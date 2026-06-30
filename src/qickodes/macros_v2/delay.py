from __future__ import annotations

from typing import TYPE_CHECKING

import qick.asm_v2

from qickodes.macro_base_v2 import Macro
from qickodes.parameters_v2 import SweepableParameter

if TYPE_CHECKING:
    from qick.asm_v2 import QickParam

    from qickodes.instrument_v2 import QickInstrument


class Delay(Macro):
    """Increment the reference time.

    This will have the effect of delaying all timed instructions executed after this one.

    Parameters
    ----------
    parent : QickInstrument
        Where this is done.
    t : float | QickParam
        The number to add to the reference time.
    """

    def __init__(
        self,
        parent: QickInstrument,
        t: float | QickParam,
    ) -> None:
        name = parent.append_counter_to_macro_name("Delay")
        super().__init__(parent, name)

        self.t = SweepableParameter(
            name="t",
            instrument=self,
            label="Time",
            unit="sec",
            initial_value=t,
        )

    def create_qick_macro(self) -> qick.asm_v2.Macro:
        return qick.asm_v2.Delay(
            t=self.t.qick_param * 1e6, auto=False, tag=self.short_name
        )
