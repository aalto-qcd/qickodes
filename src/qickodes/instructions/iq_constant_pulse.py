from qcodes.parameters import ManualParameter
from qcodes.validators import Bool

from qickodes.channels import DacChannel
from qickodes.instruction_base import QickInstruction
from qickodes.instruments import QickInstrument
from qickodes.parameters import (
    DegParameter,
    GainParameter,
    HzParameter,
    SecParameter,
)
from qickodes.protocol_base import HardwareSweep, SweepProgram


class IQConstantPulse(QickInstruction):
    """Rectangular pulse for an IQ mixer.

    Parameters
    ----------
    parent : QickInstrument
        Make me a submodule of this QickInstrument.
    dac : DacChannel
        The DAC channel to use.
    name : str
        My unique name.
    **kwargs : dict, optional
        Keyword arguments to pass on to InstrumentBase.__init__.
    """

    def __init__(
        self,
        parent: QickInstrument,
        dac_i: DacChannel,
        dac_q: DacChannel,
        name="IQConstantPulse",
        **kwargs,
    ):
        super().__init__(parent, dacs=[dac_i, dac_q], name=name, **kwargs)
        self.dac_i = dac_i
        self.dac_q = dac_q

        self.gain = GainParameter(
            name="gain",
            instrument=self,
            label="Pulse gain",
            initial_value=0.5,
        )
        self.freq = HzParameter(
            name="freq",
            instrument=self,
            label="Pulse frequency",
            initial_value=0,
            channel=self.dac_i,
        )
        self.length = SecParameter(
            name="length",
            instrument=self,
            label="Pulse length",
            initial_value=400e-9,
            channel=self.dac_i,
        )
        self.phase_imbalance = DegParameter(
            name="phase_imbalance",
            instrument=self,
            label="Phase offset to add to Q",
            initial_value=0,
            channel=self.dac_q,
        )
        self.periodic = ManualParameter(
            name="periodic",
            instrument=self,
            label="Repeat the waveform until there is a new one in the queue",
            vals=Bool(),
            initial_value=False,
        )

    def initialize(self, program: SweepProgram):
        """Add initialization commands to a program.

        Parameters
        ----------
        program : SweepProgram
        """
        program.set_pulse_registers(
            ch=self.dac_i.channel_num,
            style="const",
            freq=self.freq.get_raw(),
            phase=0,
            gain=self.gain.get_raw(),
            phrst=0,
            stdysel="zero",
            mode="periodic" if self.periodic.get() else "oneshot",
            length=self.length.get_raw(),
        )
        program.set_pulse_registers(
            ch=self.dac_q.channel_num,
            style="const",
            freq=self.freq.get_raw(),
            phase=self.dac_q.deg2reg(90 + self.phase_imbalance.get()),
            gain=self.gain.get_raw(),
            phrst=0,
            stdysel="zero",
            mode="periodic" if self.periodic.get() else "oneshot",
            length=self.length.get_raw(),
        )

    def append_to(self, program: SweepProgram):
        """Append me to a program.

        Parameters
        ----------
        program : SweepProgram
        """
        # assert self in program.protocol.instructions
        program.pulse(ch=self.dac_i.channel_num, t="auto")
        program.pulse(ch=self.dac_q.channel_num, t="auto")

    def add_sweep(self, program: SweepProgram, sweep: HardwareSweep):
        """Add a sweep over one of my parameters to a program.

        Parameters
        ----------
        program : SweepProgram
        sweep: HardwareSweep
        """
        raise NotImplementedError(
            f"cannot perform a hardware sweep over {sweep.parameter.name}"
        )
