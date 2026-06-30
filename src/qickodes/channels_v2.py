from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from qcodes import ChannelTuple, InstrumentChannel, ManualParameter, Parameter
from qcodes.validators import Bool, Enum, Numbers

if TYPE_CHECKING:
    import qick.asm_v2

    from qickodes.instruments import QickInstrument


class DacChannel(InstrumentChannel, ABC):
    """Abstract base class for a DAC channel.

    This is called 'generator' or 'gen' in the QICK library.

    Parameters
    ----------
    parent : QickInstrument
        The instrument which has this channel.
    name : str
        A unique name within the QickInstrument.
    channel_num : int
        The channel number.
    """

    parent: QickInstrument

    def __init__(self, parent: QickInstrument, name: str, channel_num: int) -> None:
        super().__init__(parent, name)
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
            label="Matching ADC",
            vals=Enum(None, *range(len(parent.soccfg["readouts"]))),
            initial_value=None,
            docstring="Channel number of the ADC to match the frequency resolution to.",
        )
        self.nqz = ManualParameter(
            name="nqz",
            instrument=self,
            label="Nyquist zone",
            vals=Enum(1, 2),
            initial_value=1,
        )
        if parent.soccfg["gens"][channel_num]["has_mixer"]:
            self.digital_mixer_freq = ManualParameter(
                name="digital_mixer_freq",
                instrument=self,
                label="Digital mixer frequency",
                unit="Hz",
                vals=Numbers(),
                initial_value=0,
                docstring="LO frequency of the digital mixer.",
            )

    @abstractmethod
    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this DAC to the program.

        Parameters
        ----------
        program : AbsQickProgram
            The program to add this DAC to.
        """


class StandardDacChannel(DacChannel):
    """A non-frequency-multiplexed DAC channel.

    Parameters
    ----------
    parent : QickInstrument
        The instrument which has this channel.
    name : str
        A unique name within the QickInstrument.
    channel_num : int
        The channel number.
    """

    def __init__(self, parent: QickInstrument, name: str, channel_num: int) -> None:
        super().__init__(parent, name, channel_num)

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this DAC to the program.

        Parameters
        ----------
        program : AbsQickProgram
            The program to add this DAC to.
        """
        if hasattr(self, "digital_mixer_freq"):
            mixer_freq = self.digital_mixer_freq.get() / 1e6
        else:
            mixer_freq = None
        program.declare_gen(self.channel_num, self.nqz.get(), mixer_freq)


class MuxedDacTone(InstrumentChannel):
    """A tone of a frequency-multiplexed DAC channel.

    Parameters
    ----------
    parent : QickInstrument
        The instrument which has this channel.
    name : str
        A unique name within the QickInstrument.
    channel_num : int
        The channel number.
    """

    parent: MultiplexedDacChannel

    def __init__(self, parent: MultiplexedDacChannel, name: str):
        super().__init__(parent, name)

        self.freq = ManualParameter(
            name="freq",
            instrument=self,
            label="Frequency of the tone",
            unit="Hz",
            vals=Numbers(),
            initial_value=0,
            docstring="This is the absolute frequency, even if there is a digital mixer.",
        )
        self.gain = ManualParameter(
            name="gain",
            instrument=self,
            label="Gain of the tone",
            unit="DAC unit",
            vals=Numbers(-1, 1),
            initial_value=1,
        )


class MultiplexedDacChannel(DacChannel):
    """A frequency-multiplexed DAC channel.

    Parameters
    ----------
    parent : QickInstrument
        The instrument which has this channel.
    name : str
        A unique name within the QickInstrument.
    channel_num : int
        The channel number.
    """

    parent: QickInstrument

    def __init__(self, parent: QickInstrument, name: str, channel_num: int) -> None:
        super().__init__(parent, name, channel_num)

        self.tones = ChannelTuple(
            parent=self,
            name="tones",
            chan_type=MuxedDacTone,
            chan_list=[
                MuxedDacTone(self, f"tone{i}")
                for i in range(parent.soccfg["gens"][channel_num]["n_tones"])
            ],
        )

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this DAC to the program.

        Parameters
        ----------
        program : AbsQickProgram
            The program to add this DAC to.
        """
        if hasattr(self, "digital_mixer_freq"):
            mixer_freq = self.digital_mixer_freq.get() / 1e6
        else:
            mixer_freq = None
        program.declare_gen(
            ch=self.channel_num,
            nqz=self.nqz.get(),
            mixer_freq=mixer_freq,
            mux_freqs=[tone.freq.get() / 1e6 for tone in self.tones],
            mux_gains=[tone.gain.get() for tone in self.tones],
            ro_ch=self.matching_adc.get(),
        )


class AdcChannel(InstrumentChannel):
    """An ADC channel.

    This is called 'readout' or 'ro' in the QICK library.

    Parameters
    ----------
    parent : QickInstrument
        The instrument which has this channel.
    name : str
        A unique name within the QickInstrument.
    channel_num : int
        The channel number.
    """

    parent: QickInstrument

    def __init__(self, parent: QickInstrument, name: str, channel_num: int) -> None:
        super().__init__(parent, name)
        self.channel_num = channel_num
        config = parent.soccfg["readouts"][channel_num]

        self.channel_type = Parameter(
            name="type",
            instrument=self,
            label="ADC type",
            initial_cache_value=config["ro_type"],
        )
        self.tproc_controlled = Parameter(
            name="tproc_controlled",
            instrument=self,
            label="tProc-controlled",
            vals=Bool(),
            initial_cache_value="tproc_ctrl" in config,
        )
        self.f_fabric = Parameter(
            name="f_fabric",
            instrument=self,
            label="Fabric clock frequency",
            initial_cache_value=config["f_fabric"] * 1e6,
        )
        self.avgbuf_fullpath = Parameter(
            name="avgbuf_fullpath",
            instrument=self,
            label="Full path (in the firmware) of the average buffer driven by this channel",
            initial_cache_value=config["avgbuf_fullpath"],
        )
        self.matching_dac = ManualParameter(
            name="matching_dac",
            instrument=self,
            label="Channel number of the DAC to match the frequency unit to.",
            vals=Enum(None, *range(len(self.parent.soccfg["gens"]))),
            initial_value=None,
        )
        self.freq = ManualParameter(
            name="freq",
            instrument=self,
            label="Default frequency for digital downconversion",
            unit="Hz",
            vals=Numbers(),
            initial_value=0,
        )
        self.length = ManualParameter(
            name="length",
            instrument=self,
            label="Readout window length",
            unit="sec",
            vals=Numbers(min_value=0),
            initial_value=10e-6,
        )

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this ADC to the program.

        Parameters
        ----------
        program : qick.asm_v2.QickProgramV2
            The program to add this to.
        """
        if self.tproc_controlled.get():
            program.declare_readout(
                ch=self.channel_num,
                length=self.length.get() * 1e6,
            )
            program.add_readoutconfig(
                ch=self.channel_num,
                name=self.short_name,
                freq=self.freq.get() / 1e6,
                phase=0,
                gen_ch=self.matching_dac.get(),
            )
            program.send_readoutconfig(
                ch=self.channel_num,
                name=self.short_name,
            )
        else:
            program.declare_readout(
                ch=self.channel_num,
                freq=self.freq.get() / 1e6,
                phase=0,
                length=self.length.get() * 1e6,
                gen_ch=self.matching_dac.get(),
            )
