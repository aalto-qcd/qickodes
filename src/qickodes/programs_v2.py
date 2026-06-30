from __future__ import annotations

from typing import TYPE_CHECKING

import qick.asm_v2
import qick.qick_asm

if TYPE_CHECKING:
    from qickodes.channels_v2 import AdcChannel, DacChannel
    from qickodes.envelope_base_v2 import DacEnvelope
    from qickodes.instrument_v2 import QickInstrument
    from qickodes.pulse_base_v2 import DacPulse
    from qickodes.readout_window_v2 import ReadoutWindow


class AveragerProgram(qick.asm_v2.AveragerProgramV2):
    def __init__(
        self,
        qick_instrument: QickInstrument,
        hardware_loop_counts: dict[str, int],
    ):
        self.qick_instrument = qick_instrument
        self.hardware_loop_counts = hardware_loop_counts
        super().__init__(
            qick_instrument.soccfg,
            reps=qick_instrument.hard_avgs.get(),
            final_delay=qick_instrument.final_delay.qick_param * 1e6,
            final_wait=qick_instrument.final_wait.qick_param * 1e6,
            initial_delay=qick_instrument.initial_delay.qick_param * 1e6,
        )

    def _initialize(self, cfg: dict):  # noqa: ARG002
        macros = self.qick_instrument.macro_list

        # remove duplicates from the set of objects to initialize
        dacs: set[DacChannel] = set().union(*(m.dacs for m in macros))
        adcs: set[AdcChannel] = set().union(*(m.adcs for m in macros))
        envelopes: set[DacEnvelope] = set().union(*(m.envelopes for m in macros))
        pulses: set[DacPulse | ReadoutWindow] = set().union(*(m.pulses for m in macros))

        for dac in dacs:
            dac.initialize(self)
        for adc in adcs:
            adc.initialize(self)
        for envelope in envelopes:
            envelope.initialize(self)
        for pulse in pulses:
            pulse.initialize(self)

        for name, count in self.hardware_loop_counts.items():
            self.add_loop(name, count)

    def _body(self, cfg: dict):  # noqa: ARG002
        for macro in self.qick_instrument.macro_list:
            self.append_macro(macro.create_qick_macro())
