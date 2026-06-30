from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import qick.asm_v2
from qcodes import Parameter

from qickodes.macro_base_v2 import Macro
from qickodes.parameters_v2 import SweepableParameter

if TYPE_CHECKING:
    from qick.asm_v2 import QickParam

    from qickodes.instrument_v2 import QickInstrument
    from qickodes.pulse_base_v2 import DacPulse


class PlayPulse(Macro):
    """Play a pulse.

    Parameters
    ----------
    parent : QickInstrument
        Where to play the pulse.
    pulse : Pulse
        The pulse to play.
    t : float | QickParam | Literal['auto'], default='auto'
        Time relative to the last Delay or DelayAuto. 'auto' means the end of the last pulse on the DAC channel.
    """

    def __init__(
        self,
        parent: QickInstrument,
        pulse: DacPulse,
        t: float | QickParam | Literal["auto"] = "auto",
    ) -> None:
        assert pulse.parent.parent is parent
        name = parent.append_counter_to_macro_name("PlayPulse")
        super().__init__(
            parent,
            name,
            dacs=[pulse.parent],
            envelopes=[pulse.envelope] if hasattr(pulse, "envelope") else (),
            pulses=[pulse],
        )

        self.dac_channel = Parameter(
            name="dac_channel",
            instrument=self,
            label="DAC channel",
            initial_cache_value=self.dacs[0].channel_num,
        )
        self.pulse_name = Parameter(
            name="pulse_name",
            instrument=self,
            label="Pulse name",
            initial_cache_value=pulse.short_name,
        )
        self.t = SweepableParameter(
            name="t",
            instrument=self,
            label="Time",
            unit="sec",
            initial_value=t,
            allow_auto=True,
        )

    def create_qick_macro(self) -> qick.asm_v2.Macro:
        return qick.asm_v2.Pulse(
            ch=self.dacs[0].channel_num,
            name=self.pulse_name.get(),
            t=self.t.qick_param * 1e6 if self.t.get() != "auto" else "auto",
            tag=self.short_name,
        )
