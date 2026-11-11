"""SFR reach networks put on a Flow, and the catchment runoff they route."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.model.boundaries.binder_payloads import payloads_as_mappings
from hydromodpy.model.boundaries.climate import watershed_mean_rates
from hydromodpy.model.contracts import LoadResultProto

if TYPE_CHECKING:
    from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
    from hydromodpy.model.flow import Flow

logger = get_logger(__name__)


def apply_sfr_network_to_flow(
    *,
    flow: Flow,
    reach_traces: Mapping[str, object] | None,
) -> bool:
    """Attach delineated SFR reach traces onto each flow SFR network payload.

    ``reach_traces`` maps a network id to its spatial ``SfrReachTrace`` (an
    opaque payload at this layer; the geometry was computed by the spatial
    delineation step). A network carrying an explicit ``reaches`` table keeps it
    and needs no trace. The solver builder then intersects each trace polyline
    with the DISV mesh.

    Returns True if at least one trace was attached, False otherwise.
    """
    if not reach_traces:
        return False
    payloads = payloads_as_mappings(flow, "sfr")
    if not payloads:
        return False

    attached = False
    for network_id, payload in payloads.items():
        trace = reach_traces.get(network_id)
        if trace is None or payload.get("reaches") is not None:
            continue
        payload["reach_trace"] = trace
        attached = True

    if not attached:
        return False
    flow.sinks_sources["sfr"] = payloads
    return True


def _active_sfr_payloads(flow: Flow) -> dict[str, dict[str, object]]:
    """Return the SFR payload dicts when the ``sfr`` boundary is active, else {}."""
    active_bc = {str(name).lower() for name in getattr(flow, "active_bc", []) or []}
    if "sfr" not in active_bc:
        return {}
    return payloads_as_mappings(flow, "sfr")


def sfr_routes_catchment_runoff(flow: Flow) -> bool:
    """Return whether an active SFR network takes the catchment runoff.

    With an active stream network the catchment runoff is ROUTED: it enters the
    reaches (distributed by length), travels downstream, and reaches a coupled
    lake through MVR instead of being dumped directly onto the lake surface.
    The lake meteo binder uses this to skip its legacy direct ``runoff * area``
    feed, so the same water is never counted twice.
    """
    return bool(_active_sfr_payloads(flow))


def apply_runoff_to_sfr_networks(
    *,
    flow: Flow,
    runoff: LoadResultProto | None = None,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    catchment_area_m2: float | None = None,
) -> bool:
    """Attach the catchment runoff as the routed SFR ``runoff`` forcing.

    The catchment-scale runoff data family (e.g. SIM2, internal unit mm/day) is
    reduced to a watershed-mean per-period rate in m/s and multiplied by the
    catchment area: the volumetric (m3/s) overland inflow entering the stream
    network, which the SFR builder distributes over the reaches by length. A
    ``runoff`` forcing already declared in config wins, so the data family is
    only the default source.

    Returns True if at least one forcing was attached, False otherwise.
    """
    if runoff is None or simulation_window is None or not catchment_area_m2:
        return False
    payloads = _active_sfr_payloads(flow)
    if not payloads:
        return False

    rate = watershed_mean_rates(runoff, "sfr_runoff", simulation_window)
    if rate is None:
        return False
    area = float(catchment_area_m2)
    values = [float(v) * area for v in rate]

    attached = False
    for payload in payloads.values():
        if payload.get("runoff") is not None:
            continue  # config already declares the forcing
        payload["runoff"] = {"kind": "values", "values": values, "units": "m3/s"}
        attached = True

    if not attached:
        return False
    flow.sinks_sources["sfr"] = payloads
    return True
