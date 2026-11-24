from header import *

readout_pulse.length.set(0.2e-6)
qi.ddr4_buffer.num_transfers.set(10)
qi.ddr4_buffer.save_dir.set("ddr4_data")

qi.set_macro_list(
    [
        Trigger(qi, readout_adc, t=0, ddr4=True),
        PlayPulse(qi, readout_pulse),
    ]
)

qi.hard_avgs.set(1)
qi.soft_avgs.set(1)

qi.run(
    Measurement(station=station, name=Path(__file__).name[:-3]),
    acquisition_mode="ddr4",
)
