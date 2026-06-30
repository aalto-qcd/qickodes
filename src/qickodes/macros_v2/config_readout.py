from __future__ import annotations

from typing import TYPE_CHECKING

import qick.asm_v2
from qcodes import Parameter

from qickodes.macro_base_v2 import Macro
from qickodes.parameters_v2 import SweepableParameter

if TYPE_CHECKING:
    from qick.asm_v2 import QickParam

    from qickodes.instrument_v2 import QickInstrument
    from qickodes.readout_window_v2 import ReadoutWindow


class ConfigReadout(Macro):
    """Send a previously defined readout window config to an ADC.

    Note that you need to have UnconfigReadout in your program if you want the first readout of the program to use the default config because the config presists across loop iterations.

    Parameters
    ----------
    parent : QickInstrument
        Where to preform the readout.
    pulse : ReadoutWindow
        The readout window config to send.
    t : float | QickParam, default=0
        Time relative to the last Delay or DelayAuto.
    """

    def __init__(
        self,
        parent: QickInstrument,
        window: ReadoutWindow,
        t: float | QickParam = 0,
    ) -> None:
        assert window.parent.parent is parent
        name = parent.append_counter_to_macro_name("ConfigReadout")
        super().__init__(parent, name, adcs=[window.parent], pulses=[window])

        self.window_name = Parameter(
            name="window_name",
            instrument=self,
            label="Readout window name",
            initial_cache_value=window.short_name,
        )
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
            name=self.pulses[0].short_name,
            t=self.t.qick_param * 1e6,
            tag=self.short_name,
        )
