from __future__ import annotations

from typing import TYPE_CHECKING

import qick
from qcodes import ChannelTuple, Instrument
from qcodes.instrument import InstrumentModule
from qcodes.parameters import ManualParameter, Parameter
from qcodes.validators import Enum, Ints
from qick.pyro import make_proxy

from qickodes.channels import AdcChannel, DacChannel

if TYPE_CHECKING:
    from qickodes.parameters_v2 import SweepableParameter


class QickInstrument(Instrument):
    def __init__(self, ns_host: str, ns_port=8888, name="QickInstrument", **kwargs):
        super().__init__(name, **kwargs)

        # Use the IP address and port of the Pyro4 nameserver to get:
        #   soc: Pyro4.Proxy pointing to the QickSoc object on the board
        #   soccfg: QickConfig containing the current configuration of the board
        self.soc, self.soccfg = make_proxy(ns_host, ns_port)

        # set of all parameters which have been assigned a QickSweep object
        self.swept_params: set[SweepableParameter] = set()

        assert len(self.soccfg["tprocs"]) == 1
        tproc_type = self.soccfg["tprocs"][0]["type"]
        if tproc_type == "axis_tproc64x32_x8":
            tproc_version = 1
        else:
            raise NotImplementedError(f"unsupported tProc type: {tproc_type}")

        self.tproc_version = Parameter(
            name="tproc_version",
            instrument=self,
            label="tProc version",
            initial_cache_value=tproc_version,
        )

        if tproc_version == 1:
            dac_list = []
            for n in range(len(self.soccfg["gens"])):
                dac_list.append(DacChannel(self, f"dac{n}", n))
            self.dacs = ChannelTuple(
                parent=self,
                name="dacs",
                chan_type=DacChannel,
                chan_list=dac_list,
            )
            adc_list = []
            for n in range(len(self.soccfg["readouts"])):
                adc_list.append(AdcChannel(self, f"adc{n}", n))
            self.adcs = ChannelTuple(
                parent=self,
                name="adcs",
                chan_type=AdcChannel,
                chan_list=adc_list,
            )

        self.add_submodule("dacs", self.dacs)
        self.add_submodule("adcs", self.adcs)

        self.ddr4_buffer = Ddr4Buffer(self, "ddr4_buffer")
        self.add_submodule("ddr4_buffer", self.ddr4_buffer)

    def cycles2sec_tproc(self, reg: int) -> float:
        """Convert time from the number of tProc clock cycles to seconds."""
        return self.soccfg.cycles2us(reg) / 1e6

    def sec2cycles_tproc(self, sec: float) -> int:
        """Convert time from seconds to the number of tProc clock cycles."""
        return self.soccfg.us2cycles(sec * 1e6)

    def get_idn(self) -> dict[str, str | None]:
        return {
            "vendor": "Xilinx",
            "model": self.soccfg["board"],
            "serial": None,
            "firmware": f"remote QICK library version = {self.soccfg['sw_version']}, local QICK library version = {qick.__version__}, firmware timestamp = {self.soccfg['fw_timestamp']}",
        }


class Ddr4Buffer(InstrumentModule):
    parent: QickInstrument

    def __init__(self, parent: QickInstrument, name: str, **kwargs):
        super().__init__(parent, name, **kwargs)

        all_avgbufs = [adc.avgbuf_fullpath.get() for adc in parent.adcs]
        wired_avgbufs = self.parent.soccfg["ddr4_buf"]["readouts"]

        self.wired_adc_channels = Parameter(
            name="wired_adc_channels",
            instrument=self,
            label="Channel numbers of the ADCs wired to this DDR4 buffer",
            initial_cache_value=[all_avgbufs.index(name) for name in wired_avgbufs],
        )
        self.selected_adc_channel = ManualParameter(
            name="selected_adc_channel",
            instrument=self,
            label="Channel number of the ADC to get data from",
            vals=Enum(*self.wired_adc_channels.get()),
            initial_value=self.wired_adc_channels.get()[0],
        )
        self.samples_per_transfer = Parameter(
            name="samples_per_transfer",
            instrument=self,
            label="Number of samples in a chunk of data transfer from the decimated stream to this DDR4 buffer. The sample rate is the fabric clock frequency of the ADC.",
            initial_cache_value=self.parent.soccfg["ddr4_buf"]["burst_len"],
        )
        self.num_transfers = ManualParameter(
            name="num_transfers",
            instrument=self,
            label="Duration of data acquisition expressed as the number of data transfers",
            vals=Ints(min_value=1),
            initial_value=1,
        )
