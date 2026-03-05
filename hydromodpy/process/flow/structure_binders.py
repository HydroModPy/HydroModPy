"""Flow-side binders for data-to-structure updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig

if TYPE_CHECKING:
    from hydromodpy.data_managers.climatic import Climatic
    from hydromodpy.data_managers.oceanic import Oceanic
    from hydromodpy.process import Flow


def apply_oceanic_to_flow(
    *,
    flow: "Flow",
    oceanic: "Oceanic" | None,
) -> None:
    """Inject mean sea-level value into the active ocean boundary condition."""
    if oceanic is None:
        return
    ocean_bc = flow.boundary_conditions.get("ocean")
    if ocean_bc is None:
        return
    ocean_bc.value = oceanic.MSL


def apply_climatic_to_flow_recharge(
    *,
    flow: "Flow",
    climatic: "Climatic" | None,
) -> None:
    """Inject loaded climatic recharge into the flow recharge sink/source.

    This binder keeps solver-side recharge policy declared in
    ``flow.sinks_sources.recharge`` (``first_clim``, ``negative_to_evt``) and
    only replaces the ``values`` payload with runtime-loaded climatic recharge.
    """
    if climatic is None or getattr(climatic, "recharge", None) is None:
        return
    sinks_sources = getattr(flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, dict) else None
    if recharge_cfg is None:
        return

    flow.set_recharge(
        FlowRechargeConfig(
            values=climatic.recharge,
            first_clim=recharge_cfg.first_clim,
            units=getattr(recharge_cfg, "units", "m/s"),
            negative_to_evt=recharge_cfg.negative_to_evt,
        )
    )
