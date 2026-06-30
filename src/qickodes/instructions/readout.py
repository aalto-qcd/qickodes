from qcodes.parameters import ManualParameter, Parameter
from qcodes.validators import Bool
from qick.averager_program import QickSweep

from qickodes.channels import AdcChannel
from qickodes.instruction_base import QickInstruction
from qickodes.instruments import QickInstrument
from qickodes.parameters import TProcSecParameter
from qickodes.protocol_base import HardwareSweep, SweepProgram


class Readout(QickInstruction):
    """Generate a specified pulse and trigger an ADC channel.

    Parameters
    ----------
    parent : QickInstrument
        Make me a submodule of this QickInstrument.
    pulse : QickInstruction
        The pulse to generate.
    adc : AdcChannel
        The ADC channel to trigger.
    name : str
        My unique name.
    **kwargs : dict, optional
        Keyword arguments to pass on to InstrumentBase.__init__.
    """

    def __init__(
        self,
        parent: QickInstrument,
        pulse: QickInstruction,
        adc: AdcChannel,
        name="Readout",
        **kwargs,
    ):
        super().__init__(parent, dacs=pulse.dacs, adcs=[adc], name=name, **kwargs)
        # assert len(self.dacs) == 1
        assert self.dacs[0].matching_adc.get() == self.adcs[0].channel_num
        assert self.adcs[0].matching_dac.get() == self.dacs[0].channel_num
        self.pulse = pulse

        self.pulse_name = Parameter(
            name="pulse_name",
            instrument=self,
            label="Name of the readout pulse",
            initial_cache_value=self.pulse.full_name,
        )
        self.wait_before = TProcSecParameter(
            name="wait_before",
            instrument=self,
            label="Wait time before the pulse",
            initial_value=100e-9,
            qick_instrument=self.parent,
        )
        self.wait_after = TProcSecParameter(
            name="wait_after",
            instrument=self,
            label="Wait time after the pulse",
            initial_value=1e-3,
            qick_instrument=self.parent,
        )
        self.adc_trig_offset = TProcSecParameter(
            name="adc_trig_offset",
            instrument=self,
            label="Delay between the start of the pulse and the ADC trigger",
            initial_value=0,
            qick_instrument=self.parent,
        )
        self.wait_for_adc = ManualParameter(
            name="wait_for_adc",
            instrument=self,
            label="Pause tProc execution until the end of the ADC readout window to prevent loop counters from getting incremented before the data is available",
            vals=Bool(),
            initial_value=True,
        )

    def initialize(self, program: SweepProgram):
        """Add initialization commands to a program.

        Parameters
        ----------
        program : SweepProgram
        """
        self.pulse.initialize(program)
        self.wait_before_reg = program.new_gen_reg(
            gen_ch=self.dacs[0].channel_num,
            init_val=self.wait_before.get() * 1e6,
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
        program.sync(self.wait_before_reg.page, self.wait_before_reg.addr)
        program.trigger(
            adcs=[self.adcs[0].channel_num],
            adc_trig_offset=self.adc_trig_offset.get_raw(),
        )
        self.pulse.append_to(program)
        if self.wait_for_adc.get():
            program.wait_all()
        program.sync_all(t=self.wait_after.get_raw())

    def add_sweep(self, program: SweepProgram, sweep: HardwareSweep):
        """Add a sweep over one of my parameters to a program.

        Parameters
        ----------
        program : SweepProgram
        sweep: HardwareSweep

        """
        if sweep.parameter is self.wait_before:
            reg = self.wait_before_reg
            program.add_sweep(
                QickSweep(program, reg, sweep.start * 1e6, sweep.stop * 1e6, sweep.num)
            )
        else:
            raise NotImplementedError(
                f"cannot perform a hardware sweep over {sweep.parameter.name}"
            )
