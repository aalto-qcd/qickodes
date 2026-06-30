from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes.instrument import InstrumentModule

if TYPE_CHECKING:
    from qickodes.channels_v2 import DacChannel


class DacPulse(InstrumentModule):
    """Base class for a pulse which gets added to the program's pulse library.

    Parameters
    ----------
    parent : DacChannel
        The DAC which will play this pulse.
    name: str
        A unique name within the QickInstrument.
    """

    parent: DacChannel

    def __init__(
        self,
        parent: DacChannel,
        name: str,
    ) -> None:
        super().__init__(parent, name)
        parent.add_submodule(name, self)
