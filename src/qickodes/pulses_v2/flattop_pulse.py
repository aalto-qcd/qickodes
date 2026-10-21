from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes.parameters import ManualParameter, Parameter
from qcodes.validators import Bool

from qickodes.parameters_v2 import SweepableParameter
from qickodes.pulse_base_v2 import DacPulse

if TYPE_CHECKING:
    import qick.asm_v2

    from qickodes.channels_v2 import DacChannel
    from qickodes.envelope_base_v2 import DacEnvelope


class FlatTopPulse(DacPulse):
    """Flat-top pulse with arbitrary ramps.

    The waveform is played in three segments: ramp-up, flat, and ramp-down.
    You need to supply an envelope which goes from 0 to 1 and back down to 0.
    The first half of the envelope will be used as the ramp-up and the second half as the ramp-down.
    If the envelope is not of even length, the middle sample will be skipped.
    It's recommended to use an even-length envelope.

    Parameters
    ----------
    parent : DacChannel
        The DAC which will play this pulse.
    name: str
        A unique name within the QickInstrument.
    envelope : DacEnvelope | None
        The ramp-up and ramp-down envelopes.
    """

    def __init__(
        self,
        parent: DacChannel,
        name: str,
        envelope: DacEnvelope,
    ) -> None:
        if envelope.parent is not parent:
            msg = (
                f"Envelope {envelope.full_name} belongs to {envelope.parent.full_name}, "
                f"but the pulse is being created on {parent.full_name}."
            )
            raise ValueError(msg)
        super().__init__(parent, name)
        self.envelope = envelope

        self.envelope_name = Parameter(
            name="envelope_name",
            instrument=self,
            label="Pulse envelope name",
            initial_cache_value=envelope.short_name if envelope is not None else None,
        )
        self.freq = SweepableParameter(
            name="freq",
            instrument=self,
            label="Pulse frequency",
            unit="Hz",
            initial_value=1e9,
            docstring="This is the absolute frequency, even if there is a digital mixer.",
        )
        self.phase = SweepableParameter(
            name="phase",
            instrument=self,
            label="Pulse phase",
            unit="deg",
            initial_value=0,
        )
        self.gain = SweepableParameter(
            name="gain",
            instrument=self,
            label="Pulse amplitude",
            unit="",
            initial_value=1,
            min_value=-1,
            max_value=1,
        )
        self.length = SweepableParameter(
            name="length",
            instrument=self,
            label="Pulse length",
            unit="sec",
            initial_value=1e-6,
            min_value=0,
            docstring="Length of the flat portion of the pulse. Not relevant for style='arb'.",
        )
        self.reset_phase = ManualParameter(
            name="reset_phase",
            instrument=self,
            label="Reset accumulated phase",
            vals=Bool(),
            initial_value=False,
        )
        self.hold_last_sample = ManualParameter(
            name="hold_last_sample",
            instrument=self,
            label="Hold last sample of pulse",
            vals=Bool(),
            initial_value=False,
            docstring="If True, the last calculated sample of the pulse is output continuously after the pulse.",
        )

    def _copy_args(self) -> tuple:
        return (self.envelope,)

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this pulse to the program's pulse library.

        Parameters
        ----------
        program : qick.asm_v2.QickProgramV2
            The program which uses this pulse.
        """
        program.add_pulse(
            ch=self.parent.channel_num,
            name=self.short_name,
            ro_ch=self.parent.matching_adc.get(),
            style="flat_top",
            freq=self.freq.qick_param / 1e6,
            phase=self.phase.qick_param,
            gain=self.gain.qick_param,
            length=self.length.qick_param * 1e6,
            phrst=self.reset_phase.get(),
            stdysel={False: "zero", True: "last"}[self.hold_last_sample.get()],
            envelope=self.envelope_name.get(),
        )
