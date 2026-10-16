from __future__ import annotations

from typing import TYPE_CHECKING

import qick.asm_v2
import qick.qick_asm

if TYPE_CHECKING:
    from qickodes.instrument_v2 import QickInstrument


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

        # Iterate in a fixed order
        def unique_sorted(attr: str) -> list:
            objects = set().union(*(getattr(m, attr) for m in macros))
            return sorted(objects, key=lambda obj: obj.full_name)

        for attr in ("dacs", "adcs", "envelopes", "pulses"):
            for obj in unique_sorted(attr):
                obj.initialize(self)

        for name, count in self.hardware_loop_counts.items():
            self.add_loop(name, count)

    def _body(self, cfg: dict):  # noqa: ARG002
        for macro in self.qick_instrument.macro_list:
            self.append_macro(macro.create_qick_macro())
