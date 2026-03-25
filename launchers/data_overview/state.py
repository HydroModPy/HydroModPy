"""Lightweight runtime state for the data-overview launcher.

No ``ExecutionRegistry``, no ``Flow``/``Transport`` — only what the
geographic pipeline and data managers need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hydromodpy.core.state.data import LoadedDataContext

if TYPE_CHECKING:
    from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (
        DomainGeographicContext,
    )
    from hydromodpy.spatial.geographic.geographic import Geographic
    from hydromodpy.core.workspace.workspace import Workspace
    from launchers.data_overview.config import DataOverviewConfig


@dataclass
class DataOverviewState:
    """Carries all runtime objects through the overview pipeline."""

    cfg: DataOverviewConfig
    workspace: Workspace | None = None
    geographic: Geographic | None = None
    domain_geographic: DomainGeographicContext | None = None
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
