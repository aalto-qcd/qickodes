# QICKoDeS

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21066164.svg)](https://doi.org/10.5281/zenodo.21066164)
[![PyPI version](https://img.shields.io/pypi/v/qickodes)](https://pypi.org/project/qickodes/)

A [QCoDeS](https://github.com/microsoft/qcodes) driver for [QICK](https://github.com/openquantumhardware/qick). Usable but still under active development. Pull requests are welcome!

Supports Python 3.11+

## Development goals

- This should be a thin wrapper that directly exposes all features of QICK.
- Pulses ("[`pulses_v2`](https://github.com/aalto-qcd/qickodes/tree/main/src/qickodes/pulses_v2)") and pulse sequences ("[`macros_v2`](https://github.com/aalto-qcd/qickodes/tree/main/src/qickodes/macros_v2)") should be parameterized such that they can be fully reproduced based on the [QCoDeS snapshot](https://microsoft.github.io/Qcodes/examples/DataSet/Working%20with%20snapshots.html) that gets saved with every dataset.

## Status between tProc v1 and v2

Currently, tProc v1 is under maintenance mode where only bug fixes
will be implemented. tProc v2 is what you should be using.

At some point, tProc v1 will be deprecated. If you find some bugs,
please do report them in the [issue tracker](https://github.com/aalto-qcd/qickodes/issues).

## Installation

The authors recommend using [uv](https://docs.astral.sh/uv/) inside a
[virtual environment](https://docs.python.org/3/library/venv.html).

```shell
uv venv my-environment
source my-environment/bin/activate
uv pip install qickodes
```

If you don't like using external packages,

```shell
python -m venv my-environment
source my-environment/bin/activate
pip install qickodes
```

### Development

If you prefer using a more reproducible build, check [locking and
syncing with uv](https://docs.astral.sh/uv/concepts/projects/sync/).
This would install an editable installation of qickodes. Please only
do this if you intend on modifying the source code and prefer to
contribute upstream to this repository.

```shell
git clone https://github.com/aalto-qcd/qickodes.git
cd qickodes/
uv sync
```

This step would create a fresh virtual environment in
`qickodes/.venv/` if a virtual environment doesn't exist already. We
recommend using a fresh venv for reproducibility.

## Getting started

1. Start the Pyro4 nameserver (see [here](https://github.com/openquantumhardware/qick/blob/main/pyro4/00_nameserver.ipynb), use port 8888) and the QICK server (see [here](https://github.com/openquantumhardware/qick/blob/main/pyro4/01_server.ipynb)) on a Xilinx board.
2. Check the connection and the channel number assignment:
    ```python
    from qickodes import QickInstrument
    qick_instrument = QickInstrument("ip.address.of.board")
    print(qick_instrument.soccfg)
    ```
3. Copy the scripts in the folder [`example_scripts`](https://github.com/aalto-qcd/qickodes/tree/main/example_scripts) into your folder.
4. Edit [`header.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/header.py):
    - Specify the IP address of the board by editing the line like
      ```python
      qick_instrument = QickInstrument("ip.address.of.board")
      ```
    - Specify DAC/ADC channel numbers by editing the lines like
      ```python
      readout_dac = qick_instrument.dacs[channel_number]
      ```
5. Run the example scripts:
    - [`meas_s21_vs_adc_trig_offset.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/meas_s21_vs_adc_trig_offset.py): Optimize the ADC trigger offset
    - [`meas_resonator.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/meas_resonator.py): Measure S21 vs frequency
    - [`meas_punchout.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/meas_punchout.py): Measure S21 vs frequency and amplitude
    - [`meas_pulse_probe_2d.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/meas_pulse_probe_2d.py): Pulse probe spectroscopy of a qubit dispersively coupled to a resonator
    - [`meas_pi_pulse_gain_sweep.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/meas_pi_pulse_gain_sweep.py): Optimize the amplitude of a pi pulse (play 10 pi pulses and readout)
    - [`meas_resonator_vs_qubit_state.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/meas_resonator_vs_qubit_state.py): Measure resonator spectra with the qubit in the ground and excited states
    - [`meas_t1.py`](https://github.com/aalto-qcd/qickodes/blob/main/example_scripts/meas_t1.py): Measure the T1 of the qubit

## Long timetraces with the DDR4 buffer (tProc v2)

With `acquisition_mode="ddr4"`, the continuous output of one readou is
recorded into the board's DDR4 memory: up to 2^30 samples per record.
The exact max timetrace that can be acquired depends on the firmware
on the board. Each record is averaged in blocks of `n_block` samples
on the board (previously this was done by sending the raw data onto
the measurement computer via Pyro and then averaging done on it,
however this would store huge chunks of data (in GBs) and take longer
measurement times). All records of a run are saved in one file.

### Board-side module

The averaging runs inside the board's Pyro server, so
[`board/qickodes_board.py`](./board/qickodes_board.py) has to be
copied onto the board. This is the case since v0.3.0.

```shell
ssh xilinx@ip.address.of.board 'mkdir -p ~/board'
scp board/qickodes_board.py xilinx@ip.address.of.board:board/
```

Then start the QICK server with `soc_class=QickodesSoc`:

```shell
sudo XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 -B -c '
import sys
sys.path.insert(0, "/home/xilinx/board")
from qick.pyro import start_server
from qickodes_board import QickodesSoc
start_server(
    ns_host="ip.address.of.board",
    ns_port=8888,
    proxy_name="myqick",
    soc_class=QickodesSoc,
    bitfile="/path/to/bitfile.bit",
)
'
```

`qick_instrument.ddr4_buffer.board.api_version.get()` returns `1` when
the module is running. Without it, qickodes falls back to averaging on
the measurement PC, which transfers the entire raw record over the
network which increases the measurement time.

### Measuring

```python
ddr4 = qick_instrument.ddr4_buffer
ddr4.selected_adc_channel.set(readout_adc.channel_num)
ddr4.num_transfers.set(num_transfers)  # record length, see ddr4.record_duration()
ddr4.n_block.set(157)                  # average blocks of 157 samples (~511 ns on the ZCU216)
ddr4.save_dir.set("ddr4_data")         # one <run_id>.nc file per run

qick_instrument.set_macro_list([
    PlayPulse(qick_instrument, readout_pulse, t=0),
    Trigger(qick_instrument, readout_adc, t=adc_trig_offset, ddr4=True),
    ...
])
qick_instrument.hard_avgs.set(num_shots)  # shots within one record
qick_instrument.soft_avgs.set(1)
qick_instrument.run(
    Measurement(station=station, name="my_measurement"),
    software_sweeps=[...],                # one record per sweep point
    acquisition_mode="ddr4",
)
```

See [`meas_s21_ddr4.py`](./example_scripts_v2/meas_s21_ddr4.py) for a
minimal example.

### Reading the data

The file holds the same structure as the `iq` of a `"decimated"` run.

```python
import xarray as xr
from qcodes.dataset import load_by_run_spec

dataset = load_by_run_spec(captured_run_id=run_id)
iq = xr.open_dataarray(dataset.metadata["ddr4_file"], engine="h5netcdf")
```

## Citing

QICKoDeS is the work of Yoshiki Sunada, Ashish Panigrahi, Jonatan
Albanese and Mikko Möttönen.

If you use QICKoDeS in your research, please cite it via its DOI:

> Sunada, Y., Panigrahi, A., Albanese, J., & Möttönen, M. *QICKoDeS: A QCoDeS driver for QICK*. Zenodo: https://doi.org/10.5281/zenodo.23350958

BibTeX entry:
```bibtex
@software{qickodes,
author = {Sunada, Yoshiki and Panigrahi, Ashish and Albanese, Jonatan and Möttönen, Mikko},
title = {{QICKoDeS}: A {QCoDeS} driver for {QICK}},
doi = {10.5281/zenodo.21066164},
title = {{qickodes}},
url = {https://doi.org/10.5281/zenodo.23350958},
year = {2026},
}
```
