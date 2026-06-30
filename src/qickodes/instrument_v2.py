from __future__ import annotations

import itertools
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

import numpy as np
import qick
import qick.asm_v2
import qick.qick_asm
from qcodes import ChannelTuple, Instrument, ManualParameter, Measurement, Parameter
from qcodes.instrument import InstrumentModule
from qcodes.validators import Enum, Ints
from qick.asm_v2 import MultiplexedGenManager, QickProgramV2, StandardGenManager
from qick.pyro import make_proxy
from tqdm.contrib.itertools import product as tqdm_product

from qickodes.channels_v2 import (
    AdcChannel,
    DacChannel,
    MultiplexedDacChannel,
    StandardDacChannel,
)
from qickodes.geometric_median import geometric_median
from qickodes.macro_base_v2 import Macro
from qickodes.parameters_v2 import SweepableParameter
from qickodes.programs_v2 import AveragerProgram

if TYPE_CHECKING:
    from qcodes.dataset.measurements import DataSaver


class SoftwareSweep:
    parameters: Sequence[Parameter]
    values: Sequence[float]

    def __init__(
        self,
        parameters: Parameter | Sequence[Parameter],
        start: float | Sequence[float],
        stop: float | None = None,
        num: int | None = None,
        skip_first: bool = False,
        skip_last: bool = False,
    ) -> None:
        if isinstance(parameters, Parameter):
            self.parameters = [parameters]
        else:
            self.parameters = parameters

        # make sure that all parameters have the same unit
        assert len({parameter.unit for parameter in self.parameters}) == 1

        if isinstance(start, (Sequence, np.ndarray)):
            self.values = start
        else:
            self.values = np.linspace(start, stop, num)
        if skip_first:
            self.values = self.values[1:]
        if skip_last:
            self.values = self.values[:-1]


class QickInstrument(Instrument):
    def __init__(
        self, ns_host: str, ns_port=8888, name="QickInstrument", **kwargs
    ) -> None:
        super().__init__(name, **kwargs)

        # Use the IP address and port of the Pyro4 nameserver to get:
        #   soc: Pyro4.Proxy pointing to the QickSoc object on the board
        #   soccfg: QickConfig containing the current configuration of the board
        self.soc, self.soccfg = make_proxy(ns_host, ns_port)

        # set of all parameters which have been assigned a QickSweep object
        self.swept_params: set[SweepableParameter] = set()

        assert len(self.soccfg["tprocs"]) == 1
        tproc_type = self.soccfg["tprocs"][0]["type"]
        if tproc_type != "qick_processor":
            raise NotImplementedError(f"unsupported tProc type: {tproc_type}")

        dac_list = []
        for n in range(len(self.soccfg["gens"])):
            dac_type = self.soccfg["gens"][n]["type"]
            manager_class = QickProgramV2.gentypes[dac_type]
            if manager_class == StandardGenManager:
                dac_list.append(StandardDacChannel(self, f"dac{n}", n))
            elif manager_class == MultiplexedGenManager:
                dac_list.append(MultiplexedDacChannel(self, f"dac{n}", n))
            else:
                raise NotImplementedError(f"unsupported DAC type: {dac_type}")
        self.dacs = ChannelTuple(
            parent=self,
            name="dacs",
            chan_type=DacChannel,
            chan_list=dac_list,
        )
        self.add_submodule("dacs", self.dacs)

        adc_list = []
        for n in range(len(self.soccfg["readouts"])):
            adc_list.append(AdcChannel(self, f"adc{n}", n))
        self.adcs = ChannelTuple(
            parent=self,
            name="adcs",
            chan_type=AdcChannel,
            chan_list=adc_list,
        )
        self.add_submodule("adcs", self.adcs)

        self.ddr4_buffer = Ddr4Buffer(self, "ddr4_buffer")
        self.add_submodule("ddr4_buffer", self.ddr4_buffer)

        self.macro_list = ChannelTuple(
            parent=self,
            name="macro_list",
            chan_type=Macro,
            chan_list=[],
        )
        self.add_submodule("macro_list", self.macro_list)

        # Counters to make sure every Macro in the macro_list has a unique name
        self.macro_name_counter: dict[str, int] = {}

        self.hard_avgs = ManualParameter(
            name="hard_avgs",
            instrument=self,
            label="Number of hardware repetitions to average over",
            vals=Ints(min_value=0),
            initial_value=1000,
        )
        self.soft_avgs = ManualParameter(
            name="soft_avgs",
            instrument=self,
            label="Number of software repetitions to average over",
            vals=Ints(min_value=0),
            initial_value=1,
        )
        self.final_delay = SweepableParameter(
            name="final_delay",
            instrument=self,
            label="Delay time to add at the end of the shot timeline, after the end of the last pulse or readout. Ten times the T1 of the qubit is usually appropriate.",
            unit="sec",
            initial_value=1e-6,
            min_value=0,
        )
        self.final_wait = SweepableParameter(
            name="final_wait",
            instrument=self,
            label="Amount of time to pause tProc execution at the end of each shot, after the end of the last readout. The default of 0 is usually appropriate.",
            unit="sec",
            initial_value=0,
            min_value=0,
        )
        self.initial_delay = SweepableParameter(
            name="initial_delay",
            instrument=self,
            label="Delay time to add to the timeline before starting to run the loops, to allow enough time for tProc to execute your initialization commands",
            unit="sec",
            initial_value=1e-6,
            min_value=0,
        )

    def append_counter_to_macro_name(self, name: str) -> str:
        """Append a number to a macro name to make it unique within the program."""
        counter = self.macro_name_counter.get(name, 0)
        self.macro_name_counter[name] = counter + 1
        return f"{name}_{counter}"

    def set_macro_list(self, macro_list: Sequence[Macro]) -> None:
        """Define chronological sequence of events.

        The sequence consists of pulses, time delays, the readout
        sequence, etc.

        Args: `Macro` type objects such as `PlayPulse`, `DelayAuto`,
        `Trigger`.
        """
        del self.submodules["macro_list"]
        del self._channel_lists["macro_list"]
        self.macro_list = ChannelTuple(
            parent=self,
            name="macro_list",
            chan_type=Macro,
            chan_list=macro_list,
        )
        self.add_submodule("macro_list", self.macro_list)

    def get_idn(self) -> dict[str, str | None]:
        return {
            "vendor": "Xilinx",
            "model": self.soccfg["board"],
            "serial": None,
            "firmware": f"remote QICK library version = {self.soccfg['sw_version']}, local QICK library version = {qick.__version__}, firmware timestamp = {self.soccfg['fw_timestamp']}",
        }

    def run(
        self,
        meas: Measurement,
        software_sweeps: Sequence[SoftwareSweep] = (),
        hardware_loop_counts: dict[str, int] | None = None,
        acquisition_mode: Literal[
            "accumulated",
            "accumulated geometric median",
            "accumulated shots",
            "ddr4",
            "decimated",
            "state population",
        ] = "accumulated",
        num_states: int = 0,
        state_classifier: Callable[[np.ndarray], np.ndarray] | None = None,
        save_shots_as_npy: bool = False,
    ) -> int:
        if len(self.macro_list) == 0:
            msg = (
                "`macro_list` is empty. Please define the sequence with"
                "`QickInstrument.set_macro_list([...])` before running the measurement."
            )
            raise RuntimeError(msg)
        if acquisition_mode in [
            "accumulated geometric median",
            "accumulated shots",
            "ddr4",
            "state population",
        ]:
            assert self.soft_avgs.get() == 1
        if acquisition_mode == "state population":
            assert num_states >= 2
            assert state_classifier is not None
        if hardware_loop_counts is None:
            hardware_loop_counts = {}
        if len(hardware_loop_counts) == 0 and acquisition_mode in [
            "accumulated",
            "accumulated geometric median",
            "state population",
        ]:
            paramtype = "numeric"
            paramtype_iq = "complex"
        else:
            paramtype = "array"
            paramtype_iq = "array"
        setpoints = []

        # initialize and register the software sweep parameters
        for sweep in software_sweeps:
            sweep.parameters[0].set(sweep.values[0])
            setpoints.append(sweep.parameters[0])
            meas.register_parameter(sweep.parameters[0], paramtype=paramtype)
            for parameter in sweep.parameters[1:]:
                parameter.set(sweep.values[0])

        # register the shot axis if necessary
        if acquisition_mode == "accumulated shots":
            shot_parameter = Parameter("shot", label="Shot", unit="")
            meas.register_parameter(shot_parameter, paramtype=paramtype)
            setpoints.append(shot_parameter)
        else:
            shot_parameter = None

        # register the hardware sweep parameters
        hardware_sweep_parameters = []
        for loop in hardware_loop_counts:
            for parameter in self.swept_params:
                sweep = parameter.get()
                assert isinstance(sweep, qick.asm_v2.QickParam)
                if loop in sweep.spans and parameter not in hardware_sweep_parameters:
                    hardware_sweep_parameters.append(parameter)
                    setpoints.append(parameter)
                    meas.register_parameter(parameter, paramtype=paramtype)

        # register the time axis if necessary
        if acquisition_mode in ["decimated", "ddr4"]:
            time_parameter = Parameter("time", label="Time", unit="sec")
            setpoints.append(time_parameter)
            meas.register_parameter(time_parameter, paramtype=paramtype)
        else:
            time_parameter = None

        # generate the program just to obtain the ADC channel numbers and the number of readouts per shot
        program = AveragerProgram(self, hardware_loop_counts)
        adc_channel_nums = program.ro_chs.keys()
        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        assert len(adc_channel_nums) == len(reads_per_shot)
        if sum(reads_per_shot) == 0:
            msg = (
                "The macro_list contains no readout triggers, so no data is acquired."
                "Include a readout macro with `QickInstrument.set_macro_list()`."
            )
            raise RuntimeError(msg)

        # create and register the parameters representing the acquired data
        result_parameters = []
        if acquisition_mode == "state population":
            for states in itertools.product(
                range(num_states), repeat=sum(reads_per_shot)
            ):
                name = "population_" + "_".join(str(state) for state in states)
                population_parameter = Parameter(name)
                result_parameters.append(population_parameter)
                meas.register_parameter(
                    population_parameter, setpoints, paramtype=paramtype
                )
        else:
            for i, channel_num in enumerate(adc_channel_nums):
                for readout_num in range(reads_per_shot[i]):
                    name = "iq"
                    if reads_per_shot[i] > 1:
                        name += f"{readout_num}"
                    if len(adc_channel_nums) > 1:
                        name += f"_ch{channel_num}"

                    iq_parameter = Parameter(name)
                    result_parameters.append(iq_parameter)
                    meas.register_parameter(
                        iq_parameter, setpoints, paramtype=paramtype_iq
                    )

                    if acquisition_mode == "accumulated geometric median":
                        # also save the median absolute deviation (MAD)
                        mad_parameter = Parameter(name + "_mad")
                        result_parameters.append(mad_parameter)
                        meas.register_parameter(
                            mad_parameter, setpoints, paramtype=paramtype_iq
                        )

        self.snapshot(update=True)

        with meas.run() as datasaver:
            if len(software_sweeps) == 0:
                self._run_hardware_loops(
                    datasaver,
                    software_sweeps,
                    shot_parameter,
                    hardware_loop_counts,
                    hardware_sweep_parameters,
                    time_parameter,
                    result_parameters,
                    acquisition_mode,
                    num_states,
                    state_classifier,
                    save_shots_as_npy,
                    software_sweep_indices=(),
                    progress=True,
                )
            else:
                software_sweep_ranges = [
                    range(len(sweep.values)) for sweep in software_sweeps
                ]
                for indices in tqdm_product(*software_sweep_ranges):
                    # update the software sweep parameters
                    for sweep, index in zip(software_sweeps, indices):
                        for parameter in sweep.parameters:
                            parameter.set(sweep.values[index])

                    self._run_hardware_loops(
                        datasaver,
                        software_sweeps,
                        shot_parameter,
                        hardware_loop_counts,
                        hardware_sweep_parameters,
                        time_parameter,
                        result_parameters,
                        acquisition_mode,
                        num_states,
                        state_classifier,
                        save_shots_as_npy,
                        software_sweep_indices=indices,
                        progress=False,
                    )

        return datasaver.run_id

    def _run_hardware_loops(
        self,
        datasaver: DataSaver,
        software_sweeps: Sequence[SoftwareSweep],
        shot_parameter: Parameter | None,
        hardware_loop_counts: dict[str, int],
        hardware_sweep_parameters: Sequence[SweepableParameter],
        time_parameter: Parameter | None,
        result_parameters: Sequence[Parameter],
        acquisition_mode: Literal[
            "accumulated",
            "accumulated geometric median",
            "accumulated shots",
            "ddr4",
            "decimated",
            "state population",
        ],
        num_states: int,
        state_classifier: Callable[[np.ndarray], np.ndarray] | None,
        save_shots_as_npy: bool,
        software_sweep_indices: Sequence[int],
        progress: bool,
    ):
        if acquisition_mode == "ddr4":
            self.ddr4_buffer.arm()

        # run the program
        program = AveragerProgram(self, hardware_loop_counts)
        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        if acquisition_mode == "decimated":
            all_iq = qick.qick_asm.AcquireMixin.acquire_decimated(
                self=program,
                soc=self.soc,
                rounds=self.soft_avgs.get(),
                progress=progress,
            )
            for channel_index in range(len(reads_per_shot)):
                channel_iq = all_iq[channel_index]
                length = len(program.get_time_axis(channel_index))
                all_iq[channel_index] = channel_iq.reshape(
                    self.hard_avgs.get(), -1, reads_per_shot[channel_index], length, 2
                )
                if len(hardware_loop_counts) == 0:
                    all_iq[channel_index] = all_iq[channel_index][:, 0, :, :, :]
        else:
            all_iq = qick.qick_asm.AcquireMixin.acquire(
                self=program,
                soc=self.soc,
                rounds=self.soft_avgs.get(),
                progress=progress,
            )

        param_values = []

        # Add software sweep paramters to the result
        for sweep in software_sweeps:
            param_values.append((sweep.parameters[0], sweep.parameters[0].get()))

        # Add the shot axis to the result if necessary
        if acquisition_mode == "accumulated shots":
            shape = (self.hard_avgs.get(), *hardware_loop_counts.values())
            values = np.arange(self.hard_avgs.get())
            for _ in range(len(hardware_loop_counts)):
                values = values[..., np.newaxis]
            values = np.broadcast_to(values, shape)
            param_values.append((shot_parameter, values))
        else:
            shape = hardware_loop_counts.values()

        # Add hardware sweep parameters to the result
        for parameter in hardware_sweep_parameters:
            sweep = parameter.qick_param
            assert isinstance(sweep, qick.asm_v2.QickParam)
            values = sweep.get_actual_values(hardware_loop_counts)
            values = np.broadcast_to(values, shape)
            param_values.append((parameter, values))

        # save the results
        if acquisition_mode == "state population":
            self._save_results_state_population(
                param_values,
                program,
                datasaver,
                result_parameters,
                num_states,
                state_classifier,
            )
        else:
            self._save_results(
                all_iq,
                param_values,
                program,
                datasaver,
                time_parameter,
                result_parameters,
                acquisition_mode,
            )

        if save_shots_as_npy:
            path = (
                Path(datasaver.dataset.path_to_db).parent / f"{datasaver.run_id}_shots"
            )
            path.mkdir(exist_ok=True)
            reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
            for channel_index in range(len(reads_per_shot)):
                channel_num = list(program.ro_chs.keys())[channel_index]
                for readout_num in range(reads_per_shot[channel_index]):
                    shots = program.acc_buf[channel_index][..., readout_num, :].dot(
                        [1, 1j]
                    )
                    name = ""
                    if len(software_sweep_indices) > 0:
                        name += "sweep_"
                        for index in software_sweep_indices:
                            name += f"{index}_"
                    name += "iq"
                    if reads_per_shot[channel_index] > 1:
                        name += f"{readout_num}"
                    if len(reads_per_shot) > 1:
                        name += f"_ch{channel_num}"
                    np.save(path / name, shots)

    def _save_results(
        self,
        all_iq: Sequence[np.ndarray],
        param_values: Sequence[tuple[Parameter, np.ndarray]],
        program: AveragerProgram,
        datasaver: DataSaver,
        time_parameter: Parameter | None,
        result_parameters: Sequence[Parameter],
        acquisition_mode: Literal[
            "accumulated",
            "accumulated geometric median",
            "accumulated shots",
            "ddr4",
            "decimated",
        ],
    ) -> None:
        ddr4_channel = self.ddr4_buffer.selected_adc_channel.get()
        ddr4_num_transfers = self.ddr4_buffer.num_transfers.get()

        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        result_index = 0
        for channel_index in range(len(reads_per_shot)):
            channel_iq = all_iq[channel_index]
            channel_num = list(program.ro_chs.keys())[channel_index]
            for readout_num in range(reads_per_shot[channel_index]):
                # Add acquired data to the result
                if acquisition_mode == "accumulated":
                    iq = channel_iq[readout_num, ...].dot([1, 1j])
                    if iq.shape == (1,):
                        iq = iq[0]
                    datasaver.add_result(
                        *param_values, (result_parameters[result_index], iq)
                    )
                    result_index += 1
                elif acquisition_mode == "accumulated geometric median":
                    # Calculate the geometric median of the single-shot data
                    iq = program.acc_buf[channel_index][..., readout_num, :]
                    gm = geometric_median(iq).dot([1, 1j])
                    datasaver.add_result(
                        *param_values, (result_parameters[result_index], gm)
                    )
                    result_index += 1
                    # Also calculate the median absolute deviation from the geometric mean
                    mad = np.median(abs(iq.dot([1, 1j]) - gm), axis=0)
                    datasaver.add_result(
                        *param_values, (result_parameters[result_index], mad)
                    )
                    result_index += 1
                elif acquisition_mode == "accumulated shots":
                    # Accumulate over readout window and save single-shot data
                    iq = program.acc_buf[channel_index][..., readout_num, :].dot(
                        [1, 1j]
                    )
                    datasaver.add_result(
                        *param_values, (result_parameters[result_index], iq)
                    )
                    result_index += 1
                elif acquisition_mode == "decimated":
                    # Save acquired waveform averaged over shots
                    assert time_parameter is not None
                    time = program.get_time_axis(channel_index) / 1e6
                    iq = channel_iq[..., readout_num, :, :].mean(axis=0).dot([1, 1j])
                    datasaver.add_result(
                        *param_values,
                        (time_parameter, time),
                        (result_parameters[result_index], iq),
                    )
                    result_index += 1
                elif acquisition_mode == "ddr4":
                    if channel_num == ddr4_channel:
                        assert time_parameter is not None
                        iq = self.soc.get_ddr4(ddr4_num_transfers).dot([1, 1j])
                        time = program.get_time_axis_ddr4(ddr4_channel, iq) / 1e6
                        datasaver.add_result(
                            *param_values,
                            (time_parameter, time),
                            (result_parameters[result_index], iq),
                        )
                        result_index += 1
                else:
                    raise NotImplementedError

    def _save_results_state_population(
        self,
        param_values: Sequence[tuple[Parameter, np.ndarray]],
        program: AveragerProgram,
        datasaver: DataSaver,
        result_parameters: Sequence[Parameter],
        num_states: int,
        state_classifier: Callable[[np.ndarray], np.ndarray] | None,
    ) -> None:
        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        num_readouts = sum(reads_per_shot)
        hard_avgs = self.hard_avgs.get()
        sweep_shape = program.acc_buf[0].shape[1:-2]

        classified = np.empty((hard_avgs, *sweep_shape, num_readouts), dtype=int)
        readout_index = 0
        for channel_index in range(len(reads_per_shot)):
            for readout_num in range(reads_per_shot[channel_index]):
                iq = program.acc_buf[channel_index][..., readout_num, :].dot([1, 1j])
                classified[..., readout_index] = state_classifier(iq)
                readout_index += 1

        population = np.zeros(sweep_shape + num_readouts * (num_states,), dtype=int)
        for sweep_index in np.ndindex(sweep_shape):
            index = (slice(None), *sweep_index, Ellipsis)
            states, counts = np.unique(classified[index], return_counts=True, axis=0)
            for state, count in zip(states, counts):
                population[sweep_index + tuple(state)] = count

        population = population.reshape(*sweep_shape, -1)
        for i, parameter in enumerate(result_parameters):
            datasaver.add_result(*param_values, (parameter, population[..., i]))

    def run_without_saving(self, progress: bool = False) -> dict[str, complex]:
        program = AveragerProgram(self, hardware_loop_counts={})
        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        assert sum(reads_per_shot) > 0
        all_iq = qick.qick_asm.AcquireMixin.acquire(
            self=program,
            soc=self.soc,
            rounds=self.soft_avgs.get(),
            progress=progress,
        )
        iqs = {}
        for channel_index in range(len(reads_per_shot)):
            channel_num = list(program.ro_chs.keys())[channel_index]
            for readout_num in range(reads_per_shot[channel_index]):
                iq = all_iq[channel_index][readout_num, ...].dot([1, 1j])
                name = "iq"
                if reads_per_shot[channel_index] > 1:
                    name += f"{readout_num}"
                if len(reads_per_shot) > 1:
                    name += f"_ch{channel_num}"
                iqs[name] = iq
        return iqs


class Ddr4Buffer(InstrumentModule):
    parent: QickInstrument

    def __init__(self, parent: QickInstrument, name: str) -> None:
        super().__init__(parent, name)

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

    def arm(self):
        """Get ready to be triggered."""
        self.parent.soc.arm_ddr4(
            self.selected_adc_channel.get(), self.num_transfers.get()
        )
