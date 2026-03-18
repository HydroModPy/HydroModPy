"""Lightweight runtime state for the data-overview launcher.

No ``ExecutionRegistry``, no ``Flow``/``Transport`` — only what the
geographic pipeline and data managers need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hydromodpy.simulation.state.data import LoadedDataContext

if TYPE_CHECKING:
    from hydromodpy.geographic.core.domain_geographic_pipeline import (
        DomainGeographicContext,
    )
    from hydromodpy.geographic.geographic import Geographic
    from hydromodpy.simulation.workspace.workspace import Workspace
    from launchers.data_overview.config import DataOverviewConfig


@dataclass
class DataOverviewState:
    """Carries all runtime objects through the overview pipeline."""

    cfg: DataOverviewConfig
    workspace: Workspace | None = None
    geographic: Geographic | None = None
    domain_geographic: DomainGeographicContext | None = None
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
