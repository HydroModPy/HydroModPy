"""Members of the public objects that left before the first stable version.

Each one is refused with the name that replaces it, and leaves this table at 2.2, as an
entry of ``OLD_NAMES`` in ``hydromodpy/_lazy.py``, which reads it. It lives in ``core`` so
that every layer that holds an object can refuse.
"""

from __future__ import annotations

from hydromodpy.core.exceptions import OldNameError

OLD_MEMBERS: dict[str, str] = {
    "Project.best": "Project.best_runs, or Project.runs().best for one Run",
    "Project.execute": "Project.simulate",
    "Project.run": "Project.launch",
    "Project.workflow_context": "Project.config, Project.domain or Project.loaded_data",
    "Run.params": "Run.parameters",
}
"""What each old member is called now, as a reader writes it."""


def refuse_old_member(owner: str, name: str) -> None:
    """Refuse *name* on *owner* when it is an old member; do nothing otherwise."""
    new = OLD_MEMBERS.get(f"{owner}.{name}")
    if new is not None:
        raise OldNameError(f"{owner}.{name} left before 2.0.0. Use {new}.")


__all__ = ["OLD_MEMBERS", "refuse_old_member"]
