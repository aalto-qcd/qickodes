from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes.instrument import InstrumentModule
from qcodes.parameters import Parameter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from qickodes.channels import AdcChannel, DacChannel
    from qickodes.instruments import QickInstrument
    from qickodes.protocol_base import HardwareSweep, SweepProgram


class QickInstruction(InstrumentModule):
    """Base class for an instruction.

    Parameters
    ----------
    parent : QickInstrument
        Make me a submodule of this QickInstrument.
    dacs : Sequence[DacChannel]
        The DAC channels to use.
    adcs : Sequence[AdcChannel]
        The ADC channels to use.
    name : str
        My unique name.
    **kwargs : dict, optional
        Keyword arguments to pass on to InstrumentBase.__init__.
    """

    parent: QickInstrument

    def __init__(
        self,
        parent: QickInstrument,
        dacs: Sequence[DacChannel] = (),
        adcs: Sequence[AdcChannel] = (),
        name: str = "QickInstruction",
        **kwargs,
    ):
        super().__init__(parent, name, **kwargs)
        assert parent.tproc_version.get() == 1
        parent.add_submodule(name, self)
        self.dacs = dacs
        self.adcs = adcs

        self.dac_channel_nums = Parameter(
            name="dac_channel_nums",
            instrument=self,
            label="DAC channel numbers",
            initial_cache_value=[dac.channel_num for dac in dacs],
        )
        self.adc_channel_nums = Parameter(
            name="adc_channel_nums",
            instrument=self,
            label="ADC channel numbers",
            initial_cache_value=[adc.channel_num for adc in adcs],
        )

    def initialize(self, program: SweepProgram):
        """Add initialization commands to a program.

        Parameters
        ----------
        program : SweepProgram
        """

    def append_to(self, program: SweepProgram):
        """Append me to a program.

        Parameters
        ----------
        program : SweepProgram
        """

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
