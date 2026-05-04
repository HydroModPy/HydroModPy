"""Runtime state threaded through the data-overview pipeline phases.

Lives in ``core`` to break the inverse coupling that previously had
``display.overview`` import from ``workflow.pipelines``. Sibling layer
types (``CatchmentDelineation``, ``GeographicDerivedFeatures``,
``DomainGeographicContext``) are kept as ``Any`` so ``core`` stays a leaf
of the import DAG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hydromodpy.core.state.data import LoadedDataContext

if TYPE_CHECKING:
    from hydromodpy.core.workspace.workspace import Workspace


@dataclass
class DataOverviewState:
    """Runtime state threaded through the overview pipeline phases.

    ``cfg`` is the root :class:`HydroModPyConfig` instance. It is typed
    ``Any`` so this module stays in the ``core`` leaf layer (the architecture
    contract forbids ``core -> config`` even under TYPE_CHECKING).
    """

    cfg: Any
    workspace: Workspace | None = None
    geographic: Any = None
    geographic_features: Any = None
    domain_geographic: Any = None
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
