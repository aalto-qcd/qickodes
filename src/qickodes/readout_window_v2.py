from __future__ import annotations

from typing import TYPE_CHECKING

from qcodes.instrument import InstrumentModule

from qickodes.parameters_v2 import SweepableParameter

if TYPE_CHECKING:
    import qick.asm_v2

    from qickodes.channels_v2 import AdcChannel


class ReadoutWindow(InstrumentModule):
    """A readout window which gets added to the program's pulse library.

    Parameters
    ----------
    parent : AdcChannel
        The ADC which will perform the readout.
    name : str
        A unique name within the QickInstrument.
    """

    parent: AdcChannel

    def __init__(
        self,
        parent: AdcChannel,
        name: str,
    ) -> None:
        if not parent.tproc_controlled.get():
            msg = f"ReadoutWindow requires a tProc-controlled ADC, {parent.full_name} is not."
            raise ValueError(msg)
        super().__init__(parent, name)

        self.freq = SweepableParameter(
            name="freq",
            instrument=self,
            label="Digital downconversion frequency",
            unit="Hz",
            initial_value=1e9,
            docstring="This is the absolute frequency, even if there is a digital mixer.",
        )

    def initialize(self, program: qick.asm_v2.QickProgramV2) -> None:
        """Add this readout window to the program's pulse library.

        Parameters
        ----------
        program : qick.asm_v2.QickProgramV2
            The program which uses this readout window.
        """
        self.parent.add_readoutconfig(
            program, self.short_name, self.freq.qick_param / 1e6
        )

    def copy(self, name: str, parent: AdcChannel | None = None) -> ReadoutWindow:
        """Make a copy of this readout window.

        Parameters
        ----------
        name : str
            Name for the new readout window.
        parent : AdcChannel, optional
            Specify a different ADC for the copied readout window.
        """
        if parent is None:
            parent = self.parent
        new_window = ReadoutWindow(parent, name)
        new_window.freq.set(self.freq.get())
        return new_window
