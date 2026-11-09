"""Mutable state container for :class:`hydromodpy.project.Project`.

Encapsulates the runtime fields that previously lived directly on the
``Project`` instance and are assigned from :mod:`hydromodpy.project.phases`
and :mod:`hydromodpy.project.runner`. Centralizing them gives mypy/pyright a
typed view of the state and removes the dunder-attribute sprawl on
``Project`` itself.

``Project`` proxies private attribute reads and writes (``project._config_path``,
``project._cfg``, ...) to this dataclass via ``__getattr__`` / ``__setattr__``.
The public read-only view of the config is ``Project.config``.

A project opened on its directory (``hmp.open``) carries its ``root`` and no
configuration yet: the first read of a field of
:data:`CONFIGURED_STATE_FIELDS` configures it from ``project.toml``, so
reading the runs of a project never validates, plans or builds a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.core.time.window import (
        ResolvedSimulationTimeGrid,
        ResolvedSteadySimulationTimeGrid,
    )
    from hydromodpy.project.environment import Environment
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.run import Run


@dataclass(slots=True)
class ProjectState:
    """Typed bag of runtime state owned by a :class:`Project`.

    Construction defaults match the values set by
    :func:`hydromodpy.project.phases.configure` so a Project can be
    instantiated with the dataclass alone and populated afterwards.
    """

    config_path: Path | None = None
    cfg: HydroModPyConfig | None = None
    environment: Environment | None = None
    solver: str | None = None
    time_grid: ResolvedSimulationTimeGrid | ResolvedSteadySimulationTimeGrid | None = None
    headless: bool = False
    no_display: bool = False
    spatial_support_registry: Any = None
    requested_support_ids: tuple[str, ...] = ()
    requested_domain_supports: dict[str, Any] = field(default_factory=dict)
    ctx: WorkflowContext | None = None
    store: Catalog | None = None
    project_name: str | None = None
    run_counter: int = 0
    active_runs: dict[str, str] = field(default_factory=dict)
    last_wall_seconds: dict[str, float] = field(default_factory=dict)
    phase: str = "uninitialized"
    data_loaded: set[str] = field(default_factory=set)
    run_history: list[Run] = field(default_factory=list)
    root: Path | None = None
    """Project directory of a project opened on its directory, ``None`` otherwise."""


PROJECT_ATTR_TO_STATE_FIELD: dict[str, str] = {
    "_config_path": "config_path",
    "_cfg": "cfg",
    "_environment": "environment",
    "_solver": "solver",
    "_time_grid": "time_grid",
    "_headless": "headless",
    "_no_display": "no_display",
    "_spatial_support_registry": "spatial_support_registry",
    "_requested_support_ids": "requested_support_ids",
    "_requested_domain_supports": "requested_domain_supports",
    "_ctx": "ctx",
    "_store": "store",
    "_project_name": "project_name",
    "_run_counter": "run_counter",
    "_active_runs": "active_runs",
    "_last_wall_seconds": "last_wall_seconds",
    "_phase": "phase",
    "_data_loaded": "data_loaded",
    "_run_history": "run_history",
}
"""Maps ``project.<name>`` access to ``project._state.<state_field>``.

Read by :class:`Project` to proxy private attribute reads and writes through
its :class:`ProjectState` container.
"""


CONFIGURED_STATE_FIELDS: frozenset[str] = frozenset(
    {
        "cfg",
        "ctx",
        "solver",
        "time_grid",
        "spatial_support_registry",
        "requested_support_ids",
        "requested_domain_supports",
    }
)
"""State fields a project opened on its directory fills when it configures itself."""


__all__ = ["CONFIGURED_STATE_FIELDS", "PROJECT_ATTR_TO_STATE_FIELD", "ProjectState"]
