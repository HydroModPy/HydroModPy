"""Shared utilities for TOML → simulation pipeline preparation.

Helper functions used by :class:`~hydromodpy.project.Project` and the
workflow pipeline layer.  The ``HydroModPyLauncher`` class that used to
live here has been removed — use ``Project`` instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Workflow steps (canonical source of truth) --------------------------------
from hydromodpy.workflow.steps.setup import (  # noqa: F401
    collect_requested_support_ids,
    support_provider_names,
    resolve_support_configs,
)
from hydromodpy.workflow.steps.data_loading import log_data_plan  # noqa: F401
from hydromodpy.workflow.steps.mesh import (  # noqa: F401
    resolve_optional_mesh_section,
    resolve_optional_mesh_input,
)

if TYPE_CHECKING:
    from hydromodpy.data import DataLoadPlan
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfigSchema


def _build_data_plan(*args, **kwargs):
    """Import planner lazily to keep imports lightweight in tests."""
    from hydromodpy.data import DataManagersPlanner

    return DataManagersPlanner().build(*args, **kwargs)
