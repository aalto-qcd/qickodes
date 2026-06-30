from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes.instrument import InstrumentModule

if TYPE_CHECKING:
    import qick.asm_v2

    from qickodes.channels_v2 import DacChannel


class DacEnvelope(InstrumentModule):
    """Base class for a pulse envelope stored in a DAC channel's envelope memory.

    Parameters
    ----------
    parent : DacChannel
        The DAC channel which will play this pulse envelope.
    name : str
        A name which is unique within the DacChannel.
    """

    parent: DacChannel

    def __init__(self, parent: DacChannel, name: str) -> None:
        super().__init__(parent, name)
        self.parent.add_submodule(name, self)

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this envelope to the program's envelope library.

        Parameters
        ----------
        program : qick.asm_v2.QickProgramV2
            The program which uses this envelope.
        """
