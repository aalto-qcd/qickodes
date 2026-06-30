from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes import InstrumentChannel, ManualParameter, Parameter
from qcodes.validators import Enum

from qickodes.parameters import HzParameter, SecParameter

if TYPE_CHECKING:
    from qick.qick_asm import AbsQickProgram

    from qickodes.instruments import QickInstrument


class DacChannel(InstrumentChannel):
    parent: QickInstrument

    def __init__(self, parent: QickInstrument, name: str, channel_num: int, **kwargs):
        super().__init__(parent, name, **kwargs)
        self.channel_num = channel_num

        self.channel_type = Parameter(
            name="type",
            instrument=self,
            label="DAC type",
            initial_cache_value=parent.soccfg["gens"][channel_num]["type"],
        )
        self.matching_adc = ManualParameter(
            name="matching_adc",
            instrument=self,
            label="Channel number of the ADC to match the frequency unit to.",
            vals=Enum(None, *range(len(self.parent.soccfg["readouts"]))),
            initial_value=None,
        )
        self.nqz = ManualParameter(
            name="nqz",
            instrument=self,
            label="Nyquist zone",
            vals=Enum(1, 2),
            initial_value=1,
        )

    def initialize(self, program: AbsQickProgram):
        """Add initialization commands to a program.

        Parameters
        ----------
        program : AbsQickProgram
        """
        program.declare_gen(ch=self.channel_num, nqz=self.nqz.get())

    def reg2hz(self, reg: int) -> float:
        """Convert a DAC frequency from the register value (int) to Hz."""
        return self.parent.soccfg.reg2freq(reg, self.channel_num) * 1e6

    def hz2reg(self, hz: float) -> int:
        """Convert a DAC frequency from Hz to the register value (int)."""
        adc_channel = self.matching_adc.get()
        if adc_channel == -1:
            adc_channel = None
        return self.parent.soccfg.freq2reg(hz / 1e6, self.channel_num, adc_channel)

    def reg2deg(self, reg: int) -> float:
        """Convert a DAC phase from the register value (int) to degrees."""
        return self.parent.soccfg.reg2deg(reg, self.channel_num)

    def deg2reg(self, deg: float) -> int:
        """Convert a DAC phase from degrees to the register value (int)."""
        return self.parent.soccfg.deg2reg(deg, self.channel_num)

    def cycles2sec(self, reg: int) -> float:
        """Convert time from the number of DAC clock cycles to seconds."""
        return self.parent.soccfg.cycles2us(reg, gen_ch=self.channel_num) / 1e6

    def sec2cycles(self, sec: float) -> int:
        """Convert time from seconds to the number of DAC clock cycles."""
        return self.parent.soccfg.us2cycles(sec * 1e6, gen_ch=self.channel_num)


class AdcChannel(InstrumentChannel):
    parent: QickInstrument

    def __init__(self, parent: QickInstrument, name: str, channel_num: int, **kwargs):
        super().__init__(parent, name, **kwargs)
        self.channel_num = channel_num

        self.avgbuf_fullpath = Parameter(
            name="avgbuf_fullpath",
            instrument=self,
            label="Full path (in the firmware) of the average buffer driven by this channel.",
            initial_cache_value=self.parent.soccfg["readouts"][channel_num].get(
                "avgbuf_fullpath", ""
            ),
        )
        self.matching_dac = ManualParameter(
            name="matching_dac",
            instrument=self,
            label="Channel number of the DAC to match the frequency unit to.",
            vals=Enum(None, *range(len(self.parent.soccfg["gens"]))),
            initial_value=None,
        )
        self.freq = HzParameter(
            name="freq",
            instrument=self,
            label="LO frequency for digital downconversion",
            initial_value=0,
            channel=self,
        )
        self.length = SecParameter(
            name="length",
            instrument=self,
            label="Readout window length",
            initial_value=10e-6,
            channel=self,
        )

    def initialize(self, program: AbsQickProgram):
        """Add initialization commands to a program.

        Parameters
        ----------
        program : AbsQickProgram
        """
        program.declare_readout(
            ch=self.channel_num,
            freq=self.freq.get() / 1e6,
            phase=0,
            length=self.length.get_raw(),
            gen_ch=self.matching_dac.get(),
        )

    def reg2hz(self, reg: int) -> float:
        """Convert ADC frequency from the register value (int) to Hz."""
        return self.parent.soccfg.reg2freq_adc(reg, self.channel_num) * 1e6

    def hz2reg(self, hz: float) -> int:
        """Convert ADC frequency from Hz to the register value (int)."""
        dac_channel = self.matching_dac.get()
        if dac_channel == -1:
            dac_channel = None
        return self.parent.soccfg.freq2reg_adc(hz / 1e6, self.channel_num, dac_channel)

    def cycles2sec(self, reg: int) -> float:
        """Convert time from the number of ADC clock cycles to seconds."""
        return self.parent.soccfg.cycles2us(reg, ro_ch=self.channel_num) / 1e6

    def sec2cycles(self, sec: float) -> int:
        """Convert time from seconds to the number of ADC clock cycles."""
        return self.parent.soccfg.us2cycles(sec * 1e6, ro_ch=self.channel_num)
