from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes import ManualParameter
from qcodes.validators import Ints
from qcodes.validators import Sequence as SequenceValidator

from qickodes.parameters_v2 import SweepableParameter
from qickodes.pulse_base_v2 import DacPulse

if TYPE_CHECKING:
    import qick.asm_v2

    from qickodes.channels_v2 import MultiplexedDacChannel


class MuxedConstantPulse(DacPulse):
    """Frequency-multiplexed constant (rectangular) pulse.

    Parameters
    ----------
    parent : MultiplexedDacChannel
        The DAC which will play this pulse.
    name: str
        A unique name within the QickInstrument.
    """

    def __init__(
        self,
        parent: MultiplexedDacChannel,
        name: str,
    ) -> None:
        super().__init__(parent, name)

        self.length = SweepableParameter(
            name="length",
            instrument=self,
            label="Pulse length",
            unit="sec",
            initial_value=1e-6,
            min_value=0,
        )
        self.tone_nums = ManualParameter(
            name="tone_nums",
            instrument=self,
            label="Tone numbers",
            vals=SequenceValidator(Ints(0, len(parent.tones))),
            initial_value=(),
            docstring="List of tone numbers to generate.",
        )

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this pulse to the program's pulse library.

        Parameters
        ----------
        program : qick.asm_v2.QickProgramV2
            The program which uses this pulse.
        """
        program.add_pulse(
            ch=self.parent.channel_num,
            name=self.short_name,
            style="const",
            length=self.length.qick_param * 1e6,
            mask=self.tone_nums.get(),
        )

    def copy(
        self, name: str, parent: MultiplexedDacChannel | None = None
    ) -> MuxedConstantPulse:
        """Make a copy of this pulse.

        Parameters
        ----------
        name : str
            Name for the new pulse.
        parent : MultiplexedDacChannel, optional
            Specify a different DAC for the copied pulse.
        """
        if parent is None:
            parent = self.parent
        new_pulse = MuxedConstantPulse(parent, name)
        new_pulse.length.set(self.length.get())
        new_pulse.tone_nums.set(self.tone_nums.get())
        return new_pulse
