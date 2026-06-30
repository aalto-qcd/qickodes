from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from qcodes.instrument import InstrumentChannel

if TYPE_CHECKING:
    from collections.abc import Sequence

    import qick.asm_v2

    from qickodes.channels_v2 import AdcChannel, DacChannel
    from qickodes.envelope_base_v2 import DacEnvelope
    from qickodes.instrument_v2 import QickInstrument
    from qickodes.pulse_base_v2 import DacPulse
    from qickodes.readout_window_v2 import ReadoutWindow


class Macro(InstrumentChannel, ABC):
    """Base class for classes wrapping `qick.asm_v2.Macro`.

    Note that each Macro object can be used only once within a program.

    Parameters
    ----------
    parent : QickInstrument
        Where this Macro will be run.
    name : str
        Name of this Macro. Should be unique within the program.
    dacs : Sequence[DacChannel], optional
        DACs used by this Macro.
    adcs : Sequence[AdcChannel], optional
        ADCs used by this Macro.
    envelopes : Sequence[DacEnvelope], optional
        Pulse envelopes used by this Macro.
    pulses : Sequence[DacPulse | ReadoutWindow], optional
        Pulses and readout windows used by this Macro.
    """

    parent: QickInstrument

    def __init__(
        self,
        parent: QickInstrument,
        name: str,
        dacs: Sequence[DacChannel] = (),
        adcs: Sequence[AdcChannel] = (),
        envelopes: Sequence[DacEnvelope] = (),
        pulses: Sequence[DacPulse | ReadoutWindow] = (),
    ) -> None:
        super().__init__(parent, name)
        self.dacs = dacs
        self.adcs = adcs
        self.pulses = pulses
        self.envelopes = envelopes

    @abstractmethod
    def create_qick_macro(self) -> qick.asm_v2.Macro:
        """Create the qick.asm_v2.Macro object to append to the program."""
