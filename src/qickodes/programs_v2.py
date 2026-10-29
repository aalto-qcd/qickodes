from __future__ import annotations

import functools
import operator
from typing import TYPE_CHECKING

import qick.asm_v2
import qick.qick_asm
from qick import obtain

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

    def prepare_round(self):
        params = self.acquire_params
        if params["type"] != "decimated" or not params.get("fast_rounds", False):
            super().prepare_round()
            return
        if not params.get("fast_first_round_done", False):
            # First round: full qick setup (loads data memory, configures buffers, etc.)
            super().prepare_round()
            params["fast_first_round_done"] = True
            return

        soc = params["soc"]
        self.acc_buf = []
        # Re-arm the buffers: the write address only reset to the start
        # address when capture is disabled and re-enabled (config_buf disables).
        for ch, ro in self.ro_chs.items():
            soc.config_buf(ch, length=ro["length"])
            soc.enable_buf(ch, enable_avg=True, enable_buf=True)
        if self.hardware_loop_counts:
            # Swept waveforms are written to waveform memory inside the loops
            soc.reload_mem()
        soc.clear_tproc_counter(addr=self.counter_addr)
        soc.start_src(params["start_src"])

    def finish_round(self):
        params = self.acquire_params
        if params["type"] != "decimated" or not params.get("fast_rounds", False):
            return super().finish_round()

        soc = params["soc"]
        total_count = functools.reduce(operator.mul, self.loop_dims)

        soc.start_tproc()
        count = 0
        while count < total_count:
            count = soc.get_tproc_counter(addr=self.counter_addr)

        dec_buf = []
        for ch, ro in self.ro_chs.items():
            dec_buf.append(
                obtain(
                    soc.get_decimated(
                        ch=ch,
                        address=0,
                        length=ro["length"] * ro["trigs"] * total_count,
                    )
                )
            )
            if params.get("keep_accumulated", False):
                self.acc_buf.append(
                    obtain(
                        soc.get_accumulated(
                            ch=ch,
                            address=0,
                            length=ro["trigs"] * total_count,
                        ).reshape((*self.loop_dims, ro["trigs"], 2))
                    )
                )
        self.rounds_buf.append(self._process_decimated(dec_buf))

        self.rounds_pbar.update()
        params["rounds_remaining"] -= 1
        done = params["rounds_remaining"] <= 0
        if done:
            soc.start_src("internal")  # stop the tProc, as qick does after each round
            soc.cleanup_round()
            self.rounds_pbar.close()
        return not done
