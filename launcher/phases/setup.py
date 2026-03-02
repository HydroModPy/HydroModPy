"""Phase 'setup': initialise workspace, geographic, domain, flow, transport."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher.run_result import RunResult


def _run_setup(result: "RunResult") -> None:
    import hydromodpy as hmp
    from hydromodpy.data_managers import DataManagers
    from hydromodpy.data_managers.geology.geology_field import GeologyField
    from hydromodpy.domain import Domain
    from hydromodpy.process import Flow, Transport
    from hydromodpy.watershed.settings import Settings

    cfg = result.cfg

    result.workspace  = hmp.Workspace(config=cfg.workspace)
    result.geographic = hmp.Geographic(cfg.geographic, result.workspace)

    surface_topo = result.geographic.get_domain_surface_topo()

    data_managers = DataManagers.from_config(cfg.data)
    result.domain = Domain(config=cfg.domain, surface_topo=surface_topo)
    if "geology" in data_managers.types:
        geology = GeologyField.from_watershed_config(
            cfg.data.geology,
            raster_support=surface_topo.support,
        )
        result.domain.set_zone("geology", geology)

    result.flow      = Flow(config=cfg.flow)
    result.settings  = Settings()
    result.transport = Transport(config=cfg.transport)
