from __future__ import annotations

import functools
import itertools
import logging
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from time import monotonic, sleep, time_ns
from typing import TYPE_CHECKING, Literal, get_args

import numpy as np
import qick
import qick.asm_v2
import qick.qick_asm
from qcodes.instrument import ChannelList, ChannelTuple, Instrument, InstrumentModule
from qcodes.parameters import ManualParameter, Parameter, ParameterBase
from qcodes.validators import Bool, Enum, Ints
from qick.asm_v2 import MultiplexedGenManager, QickProgramV2, StandardGenManager
from qick.pyro import make_proxy
from tqdm.contrib.itertools import product as tqdm_product

from qickodes.channels_v2 import (
    AdcChannel,
    DacChannel,
    MultiplexedDacChannel,
    StandardDacChannel,
)
from qickodes.ddr4_file import Ddr4File
from qickodes.geometric_median import geometric_median
from qickodes.macro_base_v2 import Macro
from qickodes.macros_v2.trigger import Trigger
from qickodes.parameters_v2 import SweepableParameter
from qickodes.programs_v2 import AveragerProgram

if TYPE_CHECKING:
    from qcodes.dataset import Measurement
    from qcodes.dataset.measurements import DataSaver

AcquisitionMode = Literal[
    "accumulated",
    "accumulated geometric median",
    "accumulated shots",
    "ddr4",
    "decimated",
    "state population",
]

# API version of board/qickodes_board.py that this qickodes expects
_BOARD_API_VERSION = 1
# Largest DDR4 result fetched in one go (raw int16 or decimated float32)
_MAX_DDR4_FETCH_BYTES = 512 * 2**20


@contextmanager
def _silence_paramtype_warning():
    """Suppress QCoDeS' paramtype-mismatch warning during registration."""

    class _Filter(logging.Filter):
        def filter(self, record):
            return "already has paramtype" not in record.getMessage()

    root = logging.getLogger(ParameterBase.__module__)
    log_filter = _Filter()
    root.addFilter(log_filter)
    try:
        yield
    finally:
        root.removeFilter(log_filter)


@contextmanager
def _qick_progress_options(**tqdm_kwargs):
    """Temporarily preset tqdm options for the progress bars that qick creates."""
    original = qick.qick_asm.tqdm
    qick.qick_asm.tqdm = functools.partial(original, **tqdm_kwargs)
    try:
        yield
    finally:
        qick.qick_asm.tqdm = original


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

        units = {parameter.unit for parameter in self.parameters}
        if len(units) != 1:
            msg = (
                "All parameters of a SoftwareSweep must have the same unit, "
                f"got {sorted(units)}."
            )
            raise ValueError(msg)

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

        n_tprocs = len(self.soccfg["tprocs"])
        if n_tprocs != 1:
            msg = f"Expected exactly one tProc on the board, found {n_tprocs}."
            raise NotImplementedError(msg)
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

        # Not every firmware has a DDR4 buffer
        self.ddr4_buffer: Ddr4Buffer | None = None
        if "ddr4_buf" in self.soccfg.get_cfg():
            self.ddr4_buffer = Ddr4Buffer(self, "ddr4_buffer")
            self.add_submodule("ddr4_buffer", self.ddr4_buffer)

        self.macro_list = ChannelList(
            parent=self,
            name="macro_list",
            chan_type=Macro,
        )
        self.add_submodule("macro_list", self.macro_list)

        # Counters to make sure every Macro in the macro_list has a unique name
        # Deliberately never reset: macros can be reused across set_macro_list()
        # calls, so restarting the count could produce duplicate names.
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
        self.fast_decimated = ManualParameter(
            name="fast_decimated",
            instrument=self,
            label="Skip redundant per-round board calls in decimated acquisitions",
            vals=Bool(),
            initial_value=False,
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
        self.macro_list.clear()
        self.macro_list.extend(macro_list)

    def get_idn(self) -> dict[str, str | None]:
        return {
            "vendor": "Xilinx",
            "model": self.soccfg["board"],
            "serial": None,
            "firmware": f"remote QICK library version = {self.soccfg['sw_version']}, local QICK library version = {qick.__version__}, firmware timestamp = {self.soccfg['fw_timestamp']}",
        }

    def triggers_ddr4(self) -> bool:
        """Return whether a macro in macro_list triggers the DDR4 buffer."""
        return any(
            isinstance(macro, Trigger) and macro.ddr4.get() for macro in self.macro_list
        )

    def _check_ddr4_record_fits_database(self) -> None:
        """Raise if a DDR4 record is too large for the QCoDeS database."""
        with closing(sqlite3.connect(":memory:")) as connection:
            limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
        # iq (complex64) and time (float64) are stored as one blob each
        n_bytes = self.ddr4_buffer.num_samples() * 8
        if n_bytes > limit:
            msg = (
                f"A DDR4 record of {self.ddr4_buffer.num_samples()} samples needs "
                f"{n_bytes:,} bytes per array, more than the {limit:,} bytes the "
                "database allows. Set ddr4_buffer.save_dir to save records to "
                "files, or increase ddr4_buffer.n_block."
            )
            raise ValueError(msg)

    def run(
        self,
        meas: Measurement,
        software_sweeps: Sequence[SoftwareSweep] = (),
        hardware_loop_counts: dict[str, int] | None = None,
        acquisition_mode: AcquisitionMode = "accumulated",
        num_states: int = 0,
        state_classifier: Callable[[np.ndarray], np.ndarray] | None = None,
        save_shots_as_npy: bool = False,
        inner_progress: bool = False,
        progress_label: str | None = None,
    ) -> int:
        if acquisition_mode not in get_args(AcquisitionMode):
            msg = f"Unknown acquisition_mode {acquisition_mode!r}. Valid modes: {', '.join(map(repr, get_args(AcquisitionMode)))}."
            raise ValueError(msg)
        if len(self.macro_list) == 0:
            msg = (
                "`macro_list` is empty. Please define the sequence with "
                "`QickInstrument.set_macro_list([...])` before running the measurement."
            )
            raise RuntimeError(msg)
        if (
            acquisition_mode
            in [
                "accumulated geometric median",
                "accumulated shots",
                "ddr4",
                "state population",
            ]
            and self.soft_avgs.get() != 1
        ):
            msg = (
                f"acquisition_mode={acquisition_mode!r} requires soft_avgs=1, "
                f"got {self.soft_avgs.get()}. Use hard_avgs for the number of shots."
            )
            raise ValueError(msg)
        if acquisition_mode == "ddr4":
            if self.ddr4_buffer is None:
                msg = "This firmware has no DDR4 buffer, so acquisition_mode='ddr4' is not available."
                raise RuntimeError(msg)
            if not self.triggers_ddr4():
                msg = "acquisition_mode='ddr4' needs a Trigger(..., ddr4=True) in the macro_list."
                raise RuntimeError(msg)
            ddr4_channel = self.ddr4_buffer.selected_adc_channel.get()
            triggered = {
                adc.channel_num
                for macro in self.macro_list
                if isinstance(macro, Trigger)
                for adc in macro.adcs
            }
            if ddr4_channel not in triggered:
                msg = (
                    f"The DDR4 buffer records ADC {ddr4_channel}, which no Trigger in the "
                    "macro_list triggers, so its readout would not be configured. Add it, "
                    f"e.g. Trigger(qi, qi.adcs[{ddr4_channel}], ddr4=True)."
                )
                raise RuntimeError(msg)
            if self.ddr4_buffer.save_dir.get() is None:
                self._check_ddr4_record_fits_database()
        ddr4_to_file = (
            acquisition_mode == "ddr4" and self.ddr4_buffer.save_dir.get() is not None
        )
        if acquisition_mode == "state population":
            if num_states < 2:
                msg = f"num_states must be atleast 2, got {num_states}."
                raise ValueError(msg)
            if state_classifier is None:
                msg = "acquisition_mode='state population' requires a state_classifier."
                raise ValueError(msg)
        if hardware_loop_counts is None:
            hardware_loop_counts = {}
        if (
            len(hardware_loop_counts) == 0
            and acquisition_mode
            in [
                "accumulated",
                "accumulated geometric median",
                "state population",
            ]
        ) or ddr4_to_file:
            paramtype = "numeric"
            paramtype_iq = "complex"
        else:
            paramtype = "array"
            paramtype_iq = "array"
        setpoints = []

        # initialize and register the software sweep parameters
        with _silence_paramtype_warning():
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

            # register the hardware sweep parameters (a DDR4 record holds the
            # whole hardware loop, so it gets no hardware sweep axes)
            hardware_sweep_parameters = []
            if acquisition_mode != "ddr4":
                for loop in hardware_loop_counts:
                    for parameter in self.swept_params:
                        sweep = parameter.get()
                        assert isinstance(sweep, qick.asm_v2.QickParam)
                        if (
                            loop in sweep.spans
                            and parameter not in hardware_sweep_parameters
                        ):
                            hardware_sweep_parameters.append(parameter)
                            setpoints.append(parameter)
                            meas.register_parameter(parameter, paramtype=paramtype)

            # register the time axis if necessary
            if acquisition_mode == "decimated" or (
                acquisition_mode == "ddr4" and not ddr4_to_file
            ):
                time_parameter = Parameter("time", label="Time", unit="sec")
                setpoints.append(time_parameter)
                meas.register_parameter(time_parameter, paramtype=paramtype)
            else:
                time_parameter = None

            # create and register the parameters representing the acquired data
            result_parameters = []
            if acquisition_mode == "ddr4":
                # One record per software-sweep point. The database stores the
                # record itself, or when the record goes to a file, when it was
                # acquired (the file holds the data).
                if ddr4_to_file:
                    ddr4_parameter = Parameter(
                        "acquired_at", label="Record acquired at (UNIX time)", unit="s"
                    )
                    meas.register_parameter(
                        ddr4_parameter, setpoints, paramtype="numeric"
                    )
                else:
                    ddr4_parameter = Parameter("iq")
                    meas.register_parameter(
                        ddr4_parameter, setpoints, paramtype="array"
                    )
                result_parameters.append(ddr4_parameter)
            else:
                # generate the program just to obtain the ADC channel numbers and the number of readouts per shot
                program = AveragerProgram(self, hardware_loop_counts)
                adc_channel_nums = program.ro_chs.keys()
                reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
                if sum(reads_per_shot) == 0:
                    msg = (
                        "The macro_list contains no readout triggers, so no data is acquired. "
                        "Include a readout macro with `QickInstrument.set_macro_list()`."
                    )
                    raise RuntimeError(msg)

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
                                    mad_parameter, setpoints, paramtype=paramtype
                                )

        with (
            meas.run() as datasaver,
            self._open_ddr4_file(
                datasaver, software_sweeps, acquisition_mode
            ) as ddr4_file,
        ):
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
                    ddr4_file=ddr4_file,
                )
            else:
                software_sweep_ranges = [
                    range(len(sweep.values)) for sweep in software_sweeps
                ]
                with _qick_progress_options(leave=False):
                    for indices in tqdm_product(
                        *software_sweep_ranges, desc=progress_label
                    ):
                        # update the software sweep parameters
                        for sweep, index in zip(software_sweeps, indices, strict=True):
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
                            progress=inner_progress,
                            ddr4_file=ddr4_file,
                        )

        return datasaver.run_id

    def _open_ddr4_file(
        self,
        datasaver: DataSaver,
        software_sweeps: Sequence[SoftwareSweep],
        acquisition_mode: AcquisitionMode,
    ) -> Ddr4File | nullcontext[None]:
        """Create the run's DDR4 file, or return a no-op context if none is needed."""
        if acquisition_mode != "ddr4" or self.ddr4_buffer.save_dir.get() is None:
            return nullcontext(None)
        save_dir = Path(self.ddr4_buffer.save_dir.get())
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{datasaver.run_id}.nc"
        if path.exists():
            msg = (
                f"{path} already exists. Run IDs restart in every database, "
                "so use a separate save_dir for each database."
            )
            raise FileExistsError(msg)
        datasaver.dataset.add_metadata("ddr4_file", str(path))

        ddr4 = self.ddr4_buffer
        n_block = ddr4.n_block.get()
        return Ddr4File(
            path,
            software_sweeps,
            num_samples=ddr4.num_samples(),
            dt=n_block / ddr4.sample_rate(),
            t0=ddr4.block_t0(),
            attrs={
                "run_id": datasaver.run_id,
                "guid": datasaver.dataset.guid,
                "n_block": n_block,
                "sample_rate": ddr4.sample_rate(),
                "num_transfers": ddr4.num_transfers.get(),
                "adc_channel": ddr4.selected_adc_channel.get(),
            },
        )

    def _run_hardware_loops(
        self,
        datasaver: DataSaver,
        software_sweeps: Sequence[SoftwareSweep],
        shot_parameter: Parameter | None,
        hardware_loop_counts: dict[str, int],
        hardware_sweep_parameters: Sequence[SweepableParameter],
        time_parameter: Parameter | None,
        result_parameters: Sequence[Parameter],
        acquisition_mode: AcquisitionMode,
        num_states: int,
        state_classifier: Callable[[np.ndarray], np.ndarray] | None,
        save_shots_as_npy: bool,
        software_sweep_indices: Sequence[int],
        progress: bool,
        ddr4_file: Ddr4File | None,
    ):
        if acquisition_mode == "ddr4":
            self._run_ddr4_record(
                datasaver,
                software_sweeps,
                software_sweep_indices,
                hardware_loop_counts,
                time_parameter,
                result_parameters[0],
                ddr4_file,
                progress,
            )
            return

        # run the program
        program = AveragerProgram(self, hardware_loop_counts)
        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        if acquisition_mode == "decimated":
            all_iq = qick.qick_asm.AcquireMixin.acquire_decimated(
                self=program,
                soc=self.soc,
                rounds=self.soft_avgs.get(),
                progress=progress,
                extra_args={
                    "fast_rounds": self.fast_decimated.get(),
                    "keep_accumulated": save_shots_as_npy,
                },
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
            "decimated",
        ],
    ) -> None:
        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        result_index = 0
        for channel_index in range(len(reads_per_shot)):
            channel_iq = all_iq[channel_index]
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
                else:
                    raise NotImplementedError

    def _run_ddr4_record(
        self,
        datasaver: DataSaver,
        software_sweeps: Sequence[SoftwareSweep],
        software_sweep_indices: Sequence[int],
        hardware_loop_counts: dict[str, int],
        time_parameter: Parameter | None,
        result_parameter: Parameter,
        ddr4_file: Ddr4File | None,
        progress: bool,
    ) -> None:
        """Acquire one DDR4 record and save it to the run's file or the database."""
        ddr4 = self.ddr4_buffer
        ddr4.arm()
        program = AveragerProgram(self, hardware_loop_counts)
        qick.qick_asm.AcquireMixin.acquire(
            self=program, soc=self.soc, rounds=1, progress=progress
        )
        ddr4.wait_for_record()
        iq, dt = ddr4.fetch()

        software_values = [
            (sweep.parameters[0], sweep.parameters[0].get())
            for sweep in software_sweeps
        ]
        if ddr4_file is not None:
            ddr4_file.write(software_sweep_indices, iq, ddr4.record_completed_at_ns)
            datasaver.add_result(
                *software_values,
                (result_parameter, ddr4.record_completed_at_ns / 1e9),
            )
        else:
            assert time_parameter is not None
            time = ddr4.block_t0() + np.arange(len(iq)) * dt
            iq_complex = (iq[:, 0] + 1j * iq[:, 1]).astype(np.complex64)
            datasaver.add_result(
                *software_values,
                (time_parameter, time),
                (result_parameter, iq_complex),
            )

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
            for state, count in zip(states, counts, strict=True):
                population[sweep_index + tuple(state)] = count

        population = population.reshape(*sweep_shape, -1)
        for i, parameter in enumerate(result_parameters):
            datasaver.add_result(*param_values, (parameter, population[..., i]))

    def run_without_saving(self, progress: bool = False) -> dict[str, complex]:
        program = AveragerProgram(self, hardware_loop_counts={})
        reads_per_shot = [ro["trigs"] for ro in program.ro_chs.values()]
        if sum(reads_per_shot) == 0:
            msg = (
                "The macro_list contains no readout triggers, so no data is acquired. "
                "Include a readout macro with `QickInstrument.set_macro_list()`."
            )
            raise RuntimeError(msg)
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

        ddr4_cfg = self.parent.soccfg["ddr4_buf"]
        all_avgbufs = [adc.avgbuf_fullpath.get() for adc in parent.adcs]
        wired_avgbufs = ddr4_cfg["readouts"]

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
            initial_cache_value=ddr4_cfg["burst_len"],
        )
        self.num_transfers = ManualParameter(
            name="num_transfers",
            instrument=self,
            label="Duration of data acquisition expressed as the number of data transfers",
            vals=Ints(
                min_value=1, max_value=ddr4_cfg["maxlen"] // ddr4_cfg["burst_len"]
            ),
            initial_value=1,
        )
        self.n_block = ManualParameter(
            name="n_block",
            instrument=self,
            label="Number of consecutive DDR4 samples averaged into one output sample (boxcar)",
            vals=Ints(min_value=1),
            initial_value=1,
        )
        self.save_dir = Parameter(
            name="save_dir",
            instrument=self,
            label="Directory for DDR4 records (None: store in the QCoDeS database)",
            initial_value=None,
            set_cmd=None,
        )
        self.board_api_version = Parameter(
            name="board_api_version",
            instrument=self,
            label="API version of the board-side qickodes module (None: plain QickSoc server)",
            initial_cache_value=self._query_board_api_version(),
        )
        self._armed_num_transfers: int | None = None
        self.record_completed_at_ns: int | None = None

    def _query_board_api_version(self) -> int | None:
        try:
            version = int(self.parent.soc.qickodes_board_api_version())
        except AttributeError:
            return None
        if version != _BOARD_API_VERSION:
            msg = (
                f"The board runs qickodes_board API version {version}, but this "
                f"qickodes expects {_BOARD_API_VERSION}. Update "
                "board/qickodes_board.py on the board and restart the Pyro server."
            )
            raise RuntimeError(msg)
        return version

    def sample_rate(self) -> float:
        """Rate (Hz) at which the DDR4 buffer stores samples (ADC fabric clock)."""
        return self.parent.adcs[self.selected_adc_channel.get()].f_fabric.get()

    def record_duration(self, num_transfers: int | None = None) -> float:
        """Length (s) of a record of `num_transfers` (default: the parameter)."""
        if num_transfers is None:
            num_transfers = self.num_transfers.get()
        return num_transfers * self.samples_per_transfer.get() / self.sample_rate()

    def num_samples(self) -> int:
        """Return the number of samples per record that fetch() will return.

        Uses the current num_transfers and n_block settings.
        """
        cfg = self.parent.soccfg["ddr4_buf"]
        raw = self.num_transfers.get() * cfg["burst_len"] - cfg.get("junk_len", 0)
        return raw // self.n_block.get()

    def block_t0(self) -> float:
        """Time (s) of the first saved sample: the centre of the first block."""
        return (self.n_block.get() - 1) / 2 / self.sample_rate()

    def _require_armed(self) -> int:
        if self._armed_num_transfers is None:
            msg = "The DDR4 buffer has not been armed; call arm() first."
            raise RuntimeError(msg)
        return self._armed_num_transfers

    def arm(self) -> None:
        """Get ready to be triggered."""
        channel = self.selected_adc_channel.get()
        num_transfers = self.num_transfers.get()
        if self.board_api_version.get() is None:
            self.parent.soc.arm_ddr4(channel, num_transfers)
        else:
            self.parent.soc.arm_ddr4_with_sentinel(channel, num_transfers)
        self._armed_num_transfers = num_transfers

    def wait_for_record(self, poll_interval: float = 0.05) -> None:
        """Block until the armed record is complete.

        Call this after the program that triggers the DDR4 buffer has returned.
        """
        num_transfers = self._require_armed()
        duration = self.record_duration(num_transfers)
        if self.board_api_version.get() is None:
            # No completion flag: the trigger fired before the program
            # returned, so the record ends at most `duration` from now.
            sleep(duration)
        else:
            deadline = monotonic() + duration + 1.0
            while not self.parent.soc.ddr4_record_done(num_transfers):
                if monotonic() > deadline:
                    msg = (
                        f"The DDR4 record ({duration:.3f} s) did not complete. Either "
                        "the program never triggered the DDR4 buffer (Trigger(..., "
                        "ddr4=True)) or the input is hard-saturated."
                    )
                    raise RuntimeError(msg)
                sleep(poll_interval)
        self.record_completed_at_ns = time_ns()

    def fetch(self, use_board: bool | None = None) -> tuple[np.ndarray, float]:
        """Read the armed record, boxcar-averaged by `n_block`.

        Parameters
        ----------
        use_board : bool, optional
            Average on the board (True) or on this PC (False). By default on
            the board if its Pyro server runs qickodes_board.

        Returns
        -------
        iq : np.ndarray
            Shape (n, 2): raw int16 samples if n_block == 1, otherwise
            float32 block means.
        dt : float
            Sample spacing of `iq` in seconds.
        """
        num_transfers = self._require_armed()
        factor = self.n_block.get()
        cfg = self.parent.soccfg["ddr4_buf"]
        n_out = (num_transfers * cfg["burst_len"] - cfg.get("junk_len", 0)) // factor
        n_bytes = n_out * (4 if factor == 1 else 8)
        if n_bytes > _MAX_DDR4_FETCH_BYTES:
            msg = (
                f"The record would be {n_bytes / 2**20:.0f} MiB after averaging "
                f"by {factor}; increase ddr4_buffer.n_block."
            )
            raise ValueError(msg)
        if use_board is None:
            use_board = self.board_api_version.get() is not None
        if use_board and self.board_api_version.get() is None:
            msg = "The board's Pyro server does not run qickodes_board."
            raise RuntimeError(msg)

        if factor == 1:
            iq = self.parent.soc.get_ddr4(num_transfers)
        elif use_board:
            iq = self.parent.soc.get_ddr4_decimated(num_transfers, factor)
        else:
            iq = self._decimate_on_pc(num_transfers, factor)
        return np.asarray(iq), factor / self.sample_rate()

    def _decimate_on_pc(
        self, num_transfers: int, factor: int, chunk_samples: int = 1 << 24
    ) -> np.ndarray:
        """Fetch the record in chunks and block-average it here (same result as on the board)."""
        cfg = self.parent.soccfg["ddr4_buf"]
        burst = cfg["burst_len"]
        start = cfg.get("junk_len", 0)
        n_blocks = (num_transfers * burst - start) // factor
        out = np.empty((n_blocks, 2), dtype=np.float32)
        blocks_per_chunk = max(1, chunk_samples // factor)
        for b0 in range(0, n_blocks, blocks_per_chunk):
            b1 = min(b0 + blocks_per_chunk, n_blocks)
            n = (b1 - b0) * factor
            raw = self.parent.soc.get_ddr4(-(-n // burst), start=start + b0 * factor)
            iq = np.asarray(raw)[:n].reshape(b1 - b0, factor, 2)
            out[b0:b1] = iq.sum(axis=1, dtype=np.int64) / factor
        return out
