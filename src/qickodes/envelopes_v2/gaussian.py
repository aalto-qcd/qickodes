from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes import ManualParameter
from qcodes.validators import Numbers

from qickodes.envelope_base_v2 import DacEnvelope

if TYPE_CHECKING:
    import qick.asm_v2

    from qickodes.channels_v2 import DacChannel


class GaussianEnvelope(DacEnvelope):
    def __init__(
        self,
        parent: DacChannel,
        name: str = "GaussianEnvelope",
    ) -> None:
        super().__init__(parent, name)

        self.sigma = ManualParameter(
            name="sigma",
            instrument=self,
            label="Standard deviation of the gaussian",
            unit="sec",
            vals=Numbers(min_value=0),
            initial_value=100e-9,
        )
        self.length = ManualParameter(
            name="length",
            instrument=self,
            label="Pulse length",
            unit="sec",
            vals=Numbers(min_value=0),
            initial_value=400e-9,
        )

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        program.add_gauss(
            ch=self.parent.channel_num,
            name=self.short_name,
            sigma=self.sigma.get() * 1e6,
            length=self.length.get() * 1e6,
        )
