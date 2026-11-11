"""The names of the steps of a simulation, the words every layer shares."""

from __future__ import annotations

STEP_NAMES: tuple[str, ...] = (
    "validate",
    "resolve",
    "build_geographic",
    "load_data",
    "build_mesh",
    "setup_process",
    "prepare_solver",
    "run_solver",
    "extract",
    "derive",
    "export",
    "seal",
    "display",
)
"""The steps of a simulation in order. ``from_step``, ``until_step``, ``--from``, ``--until``
and the ``step`` of ``outcome.json`` read these words.

They are frozen: a name here never changes its meaning, and ``outcome.step`` is an open
vocabulary, so a later version may add a step and a reader keeps what it does not know.
``tools/surface_snapshot.py`` holds the list and a test holds it against the pipeline."""

__all__ = ["STEP_NAMES"]
