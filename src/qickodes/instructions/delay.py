from qick.averager_program import QickSweep

from qickodes.channels import DacChannel
from qickodes.instruction_base import QickInstruction
from qickodes.instruments import QickInstrument
from qickodes.parameters import TProcSecParameter
from qickodes.protocol_base import HardwareSweep, SweepProgram


class Delay(QickInstruction):
    """Add a delay to a DAC channel.

    Parameters
    ----------
    parent : QickInstrument
        Make me a submodule of this QickInstrument.
    dac : DacChannel
        The DAC channel to add the delay to.
    name : str
        My unique name.
    **kwargs : dict, optional
        Keyword arguments to pass on to InstrumentBase.__init__.
    """

    def __init__(
        self,
        parent: QickInstrument,
        dac: DacChannel,
        name="Delay",
        **kwargs,
    ):
        super().__init__(parent, dacs=[dac], name=name, **kwargs)

        self.time = TProcSecParameter(
            name="time",
            instrument=self,
            label="Delay time",
            initial_value=1e-6,
            qick_instrument=self.parent,
        )

    def initialize(self, program: SweepProgram):
        """Add initialization commands to a program.

        Parameters
        ----------
        program : SweepProgram
        """
        self.time_reg = program.new_gen_reg(
            gen_ch=self.dacs[0].channel_num,
            init_val=self.time.get() * 1e6,
            reg_type="time",
            tproc_reg=True,
        )

    def append_to(self, program: SweepProgram):
        """Append me to a program.

        Parameters
        ----------
        program : SweepProgram
        """
        assert self in program.protocol.instructions
        program.sync_all()
        program.sync(self.time_reg.page, self.time_reg.addr)

    def add_sweep(self, program: SweepProgram, sweep: HardwareSweep):
        """Add a sweep over one of my parameters to a program.

        Parameters
        ----------
        program : SweepProgram
        sweep: HardwareSweep
        """
        if sweep.parameter is self.time:
            reg = self.time_reg
            program.add_sweep(
                QickSweep(self, reg, sweep.start * 1e6, sweep.stop * 1e6, sweep.num)
            )
        else:
            raise NotImplementedError(
                f"cannot perform a hardware sweep over {sweep.parameter.name}"
            )
