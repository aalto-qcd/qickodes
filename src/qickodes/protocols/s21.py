from __future__ import annotations

from typing import TYPE_CHECKING

from qickodes.protocol_base import SimpleSweepProtocol

if TYPE_CHECKING:
    from qickodes.instructions.readout import Readout
    from qickodes.instruments import QickInstrument


class S21Protocol(SimpleSweepProtocol):
    def __init__(
        self,
        parent: QickInstrument,
        readout: Readout,
        name="S21Protocol",
        **kwargs,
    ):
        super().__init__(
            parent=parent,
            instructions=[
                readout,
            ],
            name=name,
            **kwargs,
        )
