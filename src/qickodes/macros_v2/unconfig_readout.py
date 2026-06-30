from __future__ import annotations

from typing import TYPE_CHECKING

import qick.asm_v2

from qickodes.macro_base_v2 import Macro
from qickodes.parameters_v2 import SweepableParameter

if TYPE_CHECKING:
    from qick.asm_v2 import QickParam

    from qickodes.channels_v2 import AdcChannel
    from qickodes.instrument_v2 import QickInstrument


class UnconfigReadout(Macro):
    """Revert the readout window config of an ADC to its default.

    Parameters
    ----------
    parent : QickInstrument
        Where to preform the readout.
    adc : AdcChannel
        The ADC channel.
    t : float | QickParam, default=0
        Time relative to the last Delay or DelayAuto.
    """

    def __init__(
        self,
        parent: QickInstrument,
        adc: AdcChannel,
        t: float | QickParam = 0,
    ) -> None:
        assert adc.parent is parent
        name = parent.append_counter_to_macro_name("UnconfigReadout")
        super().__init__(parent, name, adcs=[adc])

        self.t = SweepableParameter(
            name="t",
            instrument=self,
            label="Time",
            unit="sec",
            initial_value=t,
        )

    def create_qick_macro(self) -> qick.asm_v2.Macro:
        return qick.asm_v2.ConfigReadout(
            ch=self.adcs[0].channel_num,
            name=self.adcs[0].short_name,
            t=self.t.qick_param * 1e6,
            tag=self.short_name,
        )
