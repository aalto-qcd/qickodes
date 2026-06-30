from __future__ import annotations

from typing import TYPE_CHECKING

from qickodes.instructions.delay import Delay
from qickodes.protocol_base import SimpleSweepProtocol

if TYPE_CHECKING:
    from qickodes.instruction_base import QickInstruction
    from qickodes.instructions.readout import Readout
    from qickodes.instruments import QickInstrument


class HahnEchoProtocol(SimpleSweepProtocol):
    def __init__(
        self,
        parent: QickInstrument,
        half_pi_pulse: QickInstruction,
        readout: Readout,
        name="HahnEchoProtocol",
        **kwargs,
    ):
        self.delay = Delay(parent, half_pi_pulse.dacs[0])
        super().__init__(
            parent=parent,
            instructions=[
                half_pi_pulse,
                self.delay,
                half_pi_pulse,
                half_pi_pulse,
                self.delay,
                half_pi_pulse,
                readout,
            ],
            name=name,
            **kwargs,
        )
