from __future__ import annotations

from typing import TYPE_CHECKING, Self

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

    def _copy_args(self) -> tuple:
        """Extra constructor arguments after ``parent`` and ``name``, used by `copy`."""
        return ()

    def copy(self, name: str, parent: DacChannel | None = None) -> Self:
        """Make a copy of this pulse.

        Every settable parameter is copied, so subclasses don't need to override this.
        Subclasses whose constructor takes extra arguments (e.g. an envelope) override
        `_copy_args` instead.

        Parameters
        ----------
        name : str
            Name for the new pulse.
        parent : DacChannel, optional
            Specify a different DAC for the copied pulse.
        """
        if parent is None:
            parent = self.parent
        new_pulse = type(self)(parent, name, *self._copy_args())
        for param_name, param in self.parameters.items():
            if param.settable:
                new_pulse.parameters[param_name].set(param.get())
        return new_pulse
