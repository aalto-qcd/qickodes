from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from qcodes import ManualParameter
from qcodes.validators import Arrays, Bool, Numbers

from qickodes.parameters_v2 import SweepableParameter
from qickodes.pulse_base_v2 import DacPulse

if TYPE_CHECKING:
    import qick.asm_v2

    from qickodes.channels_v2 import DacChannel


class CorrectedConstantPulse(DacPulse):
    """Constant (rectangular) pulse.

    Parameters
    ----------
    parent : DacChannel
        The DAC which will play this pulse.
    name: str
        A unique name within the QickInstrument.
    """

    def __init__(
        self,
        parent: DacChannel,
        name: str,
    ) -> None:
        super().__init__(parent, name)

        self.freq = ManualParameter(
            name="freq",
            instrument=self,
            label="Pulse frequency",
            unit="Hz",
            vals=Numbers(),
            initial_value=1e9,
            docstring="This is the absolute frequency, even if there is a digital mixer.",
        )
        self.phase = ManualParameter(
            name="phase",
            instrument=self,
            label="Pulse phase",
            unit="deg",
            vals=Numbers(),
            initial_value=0,
        )
        self.gain = ManualParameter(
            name="gain",
            instrument=self,
            label="Pulse amplitude",
            unit="",
            vals=Numbers(),
            initial_value=1,
        )
        self.length = SweepableParameter(
            name="length",
            instrument=self,
            label="Pulse length",
            unit="sec",
            initial_value=1e-6,
            min_value=0,
        )
        self.reset_phase = ManualParameter(
            name="reset_phase",
            instrument=self,
            label="Reset accumulated phase",
            vals=Bool(),
            initial_value=False,
        )
        self.hold_last_sample = ManualParameter(
            name="hold_last_sample",
            instrument=self,
            label="Hold last sample of pulse",
            vals=Bool(),
            initial_value=False,
            docstring="If True, the last calculated sample of the pulse is output continuously after the pulse.",
        )
        self.periodic = ManualParameter(
            name="periodic",
            instrument=self,
            label="Periodic",
            vals=Bool(),
            initial_value=False,
        )
        self.correctable_freqs = ManualParameter(
            name="correctable_freqs",
            instrument=self,
            label="Correctable frequencies",
            vals=Arrays(),
            initial_value=np.array([]),
        )
        self.gain_factors = ManualParameter(
            name="gain_factors",
            instrument=self,
            label="Gain correction factors",
            vals=Arrays(),
            initial_value=np.array([]),
        )
        self.phase_offsets = ManualParameter(
            name="phase_offsets",
            instrument=self,
            label="Phase correction offsets",
            vals=Arrays(),
            initial_value=np.array([]),
        )

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this pulse to the program's pulse library.

        Parameters
        ----------
        program : qick.asm_v2.QickProgramV2
            The program which uses this pulse.
        """
        if len(self.correctable_freqs.get()) == 0:
            gain_factor = 1
            phase_offset = 0
        else:
            gain_factor = np.interp(
                x=self.freq.get(),
                xp=self.correctable_freqs.get(),
                fp=self.gain_factors.get(),
            )
            phase_offset = np.interp(
                x=self.freq.get(),
                xp=self.correctable_freqs.get(),
                fp=self.phase_offsets.get(),
            )
        assert abs(self.gain.get() * gain_factor) <= 1
        program.add_pulse(
            ch=self.parent.channel_num,
            name=self.short_name,
            style="const",
            freq=self.freq.get() / 1e6,
            phase=self.phase.get() + phase_offset,
            gain=self.gain.get() * gain_factor,
            length=self.length.qick_param * 1e6,
            ro_ch=self.parent.matching_adc.get(),
            phrst=self.reset_phase.get(),
            stdysel={False: "zero", True: "last"}[self.hold_last_sample.get()],
            mode={False: "oneshot", True: "periodic"}[self.periodic.get()],
        )

    def copy(
        self, name: str, parent: DacChannel | None = None
    ) -> CorrectedConstantPulse:
        """Make a copy of this pulse.

        Parameters
        ----------
        name : str
            Name for the new pulse.
        parent : DacChannel, optional
            Specify a different DAC for the copied pulse.
        """
        if parent is None:
            parent = self.parent
        new_pulse = CorrectedConstantPulse(parent, name)
        new_pulse.freq.set(self.freq.get())
        new_pulse.phase.set(self.phase.get())
        new_pulse.gain.set(self.gain.get())
        new_pulse.length.set(self.length.get())
        new_pulse.reset_phase.set(self.reset_phase.get())
        new_pulse.hold_last_sample.set(self.hold_last_sample.get())
        new_pulse.periodic.set(self.periodic.get())
        new_pulse.correctable_freqs.set(self.correctable_freqs.get())
        new_pulse.gain_factors.set(self.gain_factors.get())
        new_pulse.phase_offsets.set(self.phase_offsets.get())
        return new_pulse
