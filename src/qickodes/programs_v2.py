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
        self._dec_sum = None
        self._dec_rounds = 0

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

    def _process_decimated(self, dec_buf):
        """Store a running sum of timetraces instead of all the raw timetraces."""
        result = super()._process_decimated(dec_buf)
        if self._dec_sum is None:
            self._dec_sum = result
        else:
            for i, new in enumerate(result):
                self._dec_sum[i] += new
        self._dec_rounds += 1

    def _summarize_decimated(self, rounds_buf):  # noqa: ARG002
        # QICK calls self._summarize_decimated(self.rounds_buf) in `finish_acquire`.
        averaged = [total / self._dec_rounds for total in self._dec_sum]
        self._dec_sum = None
        self._dec_rounds = 0
        return averaged
