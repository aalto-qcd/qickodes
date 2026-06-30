from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from qcodes import ManualParameter
from qcodes.validators import Numbers

if TYPE_CHECKING:
    from qickodes.channels import AdcChannel, DacChannel
    from qickodes.instruments import QickInstrument


class HardwareParameter(ABC, ManualParameter):
    def __init__(self, name: str, **kwargs):
        super().__init__(
            name, get_parser=self.int2float, set_parser=self.float2int, **kwargs
        )

    @abstractmethod
    def int2float(self, i: int) -> float: ...

    @abstractmethod
    def float2int(self, f: float) -> int: ...


class HzParameter(HardwareParameter):
    """Frequency parameter with automatic rounding to a multiple of the frequency unit of the specified DAC/ADC channel. The `get_raw()` method returns the register value (int) that should be sent to QICK."""

    def __init__(self, name: str, channel: DacChannel | AdcChannel, **kwargs):
        self.channel = channel
        super().__init__(name, unit="Hz", **kwargs)

    def int2float(self, i: int) -> float:
        return self.channel.reg2hz(i)

    def float2int(self, f: float) -> int:
        return self.channel.hz2reg(f)


class DegParameter(HardwareParameter):
    """Phase parameter with automatic rounding to a multiple of the phase unit of the specified DAC channel. The `get_raw()` method returns the register value (int) that should be sent to QICK."""

    def __init__(self, name: str, channel: DacChannel, **kwargs):
        self.channel = channel
        super().__init__(name=name, unit="deg", **kwargs)

    def int2float(self, i: int) -> float:
        return self.channel.reg2deg(i)

    def float2int(self, f: float) -> int:
        return self.channel.deg2reg(f)


class SecParameter(HardwareParameter):
    """Time parameter with automatic rounding to a multiple of the clock period of the specified DAC/ADC channel. The `get_raw()` method returns the time in the number of clock cycles."""

    def __init__(self, name: str, channel: DacChannel | AdcChannel, **kwargs):
        self.channel = channel
        super().__init__(name=name, unit="sec", **kwargs)

    def int2float(self, i: int) -> float:
        return self.channel.cycles2sec(i)

    def float2int(self, f: float) -> int:
        return self.channel.sec2cycles(f)


class TProcSecParameter(HardwareParameter):
    """Time parameter with automatic rounding to a multiple of the tProc clock period. The `get_raw()` method returns the time in the number of clock cycles."""

    def __init__(self, name: str, qick_instrument: QickInstrument, **kwargs):
        self.qick_instrument = qick_instrument
        super().__init__(name=name, unit="sec", **kwargs)

    def int2float(self, i: int) -> float:
        return self.qick_instrument.cycles2sec_tproc(i)

    def float2int(self, f: float) -> int:
        return self.qick_instrument.sec2cycles_tproc(f)


class GainParameter(HardwareParameter):
    """Gain parameter with automatic rounding to a multiple of the gain unit. The `get_raw()` method returns the register value (int) that should be sent to QICK."""

    def __init__(self, name: str, **kwargs):
        super().__init__(name=name, vals=Numbers(-1, 32767 / 32768), **kwargs)

    def int2float(self, i: int) -> float:
        return i / 32768

    def float2int(self, f: float) -> int:
        return round(f * 32768)
