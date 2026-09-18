"""What every solver model shares, and it is not much.

``RunExecutionResult.primary_model`` was typed ``Any`` and carried seven
unrelated classes plus, for a mesh run, a plain summary dict. ``Any`` said
nothing, and the dict said something false: a mesh run produces no model.

The contract below is deliberately thin, because the measurement says it has to
be. The seven producers share exactly three members - the name they were given,
the folder they were given, and the path they work in. Nothing else is common:
``solver_mesh`` is absent from Boussinesq, ``exe`` from the transport family,
``sim`` and ``gwf`` from MODFLOW-NWT. A wider protocol here would be a wish, not
a fact, and every consumer that needs more already asks its own backend.

It lives in ``core`` because ``simulation`` types the field and cannot import
``solver``; the layer matrix runs the other way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SolverModel(Protocol):
    """A model a solver adapter produced, and where it works.

    ``full_path`` is a ``str`` on the MODFLOW families and a ``Path`` on
    Boussinesq, which is why it is typed as both rather than normalised here:
    normalising it would move a path string in seven classes for the benefit of
    an annotation.
    """

    model_name: str
    model_folder: str | Path
    full_path: str | Path


__all__ = ["SolverModel"]
