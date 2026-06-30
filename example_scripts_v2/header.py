from pathlib import Path

import numpy as np
from qcodes import (
    Measurement,
    Station,
    initialise_or_create_database_at,
    load_or_create_experiment,
)
from qick.asm_v2 import QickSweep1D

from qickodes.channels_v2 import DacChannel
from qickodes.envelope_base_v2 import DacEnvelope
from qickodes.envelopes_v2 import *
from qickodes.instrument_v2 import QickInstrument, SoftwareSweep
from qickodes.macros_v2 import *
from qickodes.pulse_base_v2 import DacPulse
from qickodes.pulses_v2 import *

experiment_name = "example_experiment"
sample_name = "example_sample"
wiring = """
your wiring
(this text gets saved with data)
"""

initialise_or_create_database_at(Path(__file__).parent / "database.db")
experiment = load_or_create_experiment(experiment_name, sample_name)

station = Station()
station.metadata["wiring"] = wiring
qi: QickInstrument = QickInstrument("ip.address.of.board", name="qi")
station.add_component(qi)

readout_dac = qi.dacs[0]
readout_adc = qi.adcs[0]
readout_dac.matching_adc.set(readout_adc.channel_num)
readout_adc.matching_dac.set(readout_dac.channel_num)
qi.ddr4_buffer.selected_adc_channel.set(readout_adc.channel_num)
readout_dac.nqz.set(1)

readout_pulse = ConstantPulse(readout_dac, "readout_pulse")
readout_pulse.gain.set(1)
readout_pulse.freq.set(6e9)
readout_pulse.length.set(10e-6)
readout_adc.freq.set(readout_pulse.freq.get())
readout_adc.length.set(readout_pulse.length.get())


def readout():
    return [
        DelayAuto(qi, 10e-9),
        Trigger(qi, readout_adc, t=450e-9),
        PlayPulse(qi, readout_pulse),
        DelayAuto(qi, 10e-9),
    ]


qubit_dac = qi.dacs[1]
qubit_dac.nqz.set(1)

ge_envelope = GaussianDragEnvelope(qubit_dac, "ge_envelope")
ge_envelope.sigma.set(5e-9)
ge_envelope.length.set(20e-9)
ge_envelope.delta.set(-161e6)
ge_envelope.alpha.set(-0.12)

ge_pi_pulse = ArbitraryPulse(qubit_dac, "ge_pi_pulse", ge_envelope)
ge_pi_pulse.gain.set(0.520)
ge_pi_pulse.freq.set(3.43899e9)

ge_half_pi_pulse = ge_pi_pulse.copy("ge_half_pi_pulse")
ge_half_pi_pulse.gain.set(ge_pi_pulse.gain.get() / 2)

ef_envelope = GaussianDragEnvelope(qubit_dac, "ef_envelope")
ef_envelope.sigma.set(5e-9)
ef_envelope.length.set(20e-9)
ef_envelope.delta.set(-161e6)
ef_envelope.alpha.set(-0.12)

ef_pi_pulse = ArbitraryPulse(qubit_dac, "ef_pi_pulse", ef_envelope)
ef_pi_pulse.gain.set(0.348)
ef_pi_pulse.freq.set(3.27805e9)

ef_half_pi_pulse = ef_pi_pulse.copy("ef_half_pi_pulse")
ef_half_pi_pulse.gain.set(ef_pi_pulse.gain.get() / 2)
