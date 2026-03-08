"""Runtime setup scope shared by launcher process runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.domain import Domain
    from hydromodpy.geographic.core.domain_geographic_pipeline import DomainGeographicContext
    from hydromodpy.process import Flow, Transport
    from hydromodpy.simulation.workspace import Workspace
    from hydromodpy.simulation.settings import Settings


@dataclass
class SetupContext:
    """Objects prepared during setup and reused by all runs."""

    workspace: Workspace | None = None
    geographic: Any = None  # Geographic
    domain_geographic: DomainGeographicContext | None = None
    domain: Domain | None = None
    flow: Flow | None = None
    transport: Transport | None = None
    settings: Settings | None = None
    model_name: str = "default"

