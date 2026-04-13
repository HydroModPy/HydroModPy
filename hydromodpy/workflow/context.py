"""Workflow context — extended run state with store lifecycle.

``WorkflowContext`` is a backward-compatible extension of
``LauncherRunState`` that adds result-store fields needed by the
workflow layer.  Any code that accepts ``LauncherRunState`` also
accepts ``WorkflowContext`` transparently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hydromodpy.core.state.run_state import LauncherRunState


@dataclass
class WorkflowContext(LauncherRunState):
    """Mutable workflow state with result-store lifecycle support.

    Inherits the three canonical scopes from ``LauncherRunState``
    (``setup``, ``loaded_data``, ``execution``) and adds:

    - ``store``: open ``ResultStore`` instance (or ``None``),
    - ``sim_id``: UUID of the current simulation in the store,
    - ``postprocess_runner``: optional post-process hook runner.
    """

    store: Any = field(default=None, repr=False)
    sim_id: str | None = None
    postprocess_runner: Any = field(default=None, repr=False)
