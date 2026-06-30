from qick.averager_program import QickSweep

from qickodes.channels import DacChannel
from qickodes.instruction_base import QickInstruction
from qickodes.instruments import QickInstrument
from qickodes.parameters import DegParameter
from qickodes.protocol_base import HardwareSweep, SweepProgram


class SetPhase(QickInstruction):
    """Set the phase of the LO of a DAC channel.

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
        dac: DacChannel,
        name="SetPhase",
        **kwargs,
    ):
        super().__init__(parent, dacs=[dac], name=name, **kwargs)

        self.phase = DegParameter(
            name="phase",
            instrument=self,
            label="phase",
            initial_value=0,
            channel=self.dacs[0],
        )

    def initialize(self, program: SweepProgram):
        """Add initialization commands to a program.

        Parameters
        ----------
        program : SweepProgram
        """
        self.dac_phase_reg = program.get_gen_reg(self.dacs[0].channel_num, "phase")
        self.phase_reg = program.new_gen_reg(
            gen_ch=self.dacs[0].channel_num,
            init_val=self.phase.get(),
            reg_type="phase",
        )

    def append_to(self, program: SweepProgram):
        """Append me to a program.

        Parameters
        ----------
        program : SweepProgram
        """
        assert self in program.protocol.instructions
        self.dac_phase_reg.set_to(self.phase_reg)

    def add_sweep(self, program: SweepProgram, sweep: HardwareSweep):
        """Add a sweep over one of my parameters to a program.

        Parameters
        ----------
        program : SweepProgram
        sweep: HardwareSweep
        """
        if sweep.parameter is self.phase:
            reg = self.phase_reg
            program.add_sweep(
                QickSweep(program, reg, sweep.start_int, sweep.stop_int, sweep.num)
            )
        else:
            raise NotImplementedError(
                f"cannot perform a hardware sweep over {sweep.parameter.name}"
            )
