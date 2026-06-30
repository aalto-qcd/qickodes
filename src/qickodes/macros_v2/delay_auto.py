from __future__ import annotations

from typing import TYPE_CHECKING

import qick.asm_v2
from qcodes import Parameter

from qickodes.macro_base_v2 import Macro
from qickodes.parameters_v2 import SweepableParameter

if TYPE_CHECKING:
    from qick.asm_v2 import QickParam

    from qickodes.instrument_v2 import QickInstrument


class DelayAuto(Macro):
    """Set the reference time to the end of the last pulse/readout, plus the specified value.

    You can select whether this accounts for pulses, readout windows, or both.

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
        t: float | QickParam = 0,
        wait_for_dacs: bool = True,
        wait_for_adcs: bool = False,
    ) -> None:
        name = parent.append_counter_to_macro_name("DelayAuto")
        super().__init__(parent, name)

        self.t = SweepableParameter(
            name="t",
            instrument=self,
            label="Time",
            unit="sec",
            initial_value=t,
        )
        self.wait_for_dacs = Parameter(
            name="wait_for_dacs",
            instrument=self,
            label="Wait for DACs",
            initial_cache_value=wait_for_dacs,
        )
        self.wait_for_adcs = Parameter(
            name="wait_for_adcs",
            instrument=self,
            label="Wait for ADCs",
            initial_cache_value=wait_for_adcs,
        )

    def create_qick_macro(self) -> qick.asm_v2.Macro:
        return qick.asm_v2.Delay(
            t=self.t.qick_param * 1e6,
            auto=True,
            gens=self.wait_for_dacs.get(),
            ros=self.wait_for_adcs.get(),
            tag=self.short_name,
        )
