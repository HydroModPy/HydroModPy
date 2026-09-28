"""Store, read and redraw the snapped mapped network of a run.

``[geographic.snap_streams]`` snaps the mapped stream network onto the talwegs
of the criterion graph (:mod:`hydromodpy.core.stream_snap`). A figure has to
draw the map that was scored, so the snapped map is either read back from the
run, where a run that stored it keeps it as one geographic feature, or rebuilt
through the construction the criterion used, from the setting the run sealed
in its configuration.

The feature holds one point per mapped cell of the catchment, placed at the
centre of the cell it moved onto (or at its own centre when it was rejected),
with the raw centre, the displacement in metres, the status and the
accumulation percentile of the chosen cell as attributes. That table is the
snapped geometry and its displacement record in one GeoParquet file.

A run whose setting is ``diagnose`` or ``apply`` stores it when its artefacts
are saved (:func:`persist_snapped_networks`): the maximal map always, the
minimal map when the run carries one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_snap import (
    SNAP_STATUS_LABELS,
    SNAP_UNMAPPED,
    SnapStreamsConfig,
    StreamSnap,
)

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.run import Run

logger = get_logger(__name__)

MapRole = Literal["maximal", "minimal"]

SNAPPED_NETWORK_FEATURES: dict[str, str] = {
    "maximal": "observed_network_snapped",
    "minimal": "observed_network_snapped_minimal",
}
"""The geographic feature a run stores each snapped map under."""

SNAPPED_NETWORK_COLUMNS = (
    "raw_cell",
    "snapped_cell",
    "status",
    "displacement_m",
    "raw_x",
    "raw_y",
    "accumulation_percentile",
)
"""The attribute columns of the stored feature, beside its point geometry."""

_UNREBUILDABLE = (KeyError, ValueError, FileNotFoundError, RuntimeError)
"""What a rebuild raises when a stored input is missing or unreadable.

The index can list a network whose GeoParquet file is gone from disk: the
read then raises ``KeyError`` or ``FileNotFoundError``, not ``ValueError``.
"""


def snap_settings_of_run(sim: Any) -> SnapStreamsConfig | None:
    """Return the ``[geographic.snap_streams]`` setting a run sealed, or None when off.

    A run with no configuration snapshot, or one written before the setting
    existed, did not snap.
    """
    try:
        snapshot = getattr(sim, "config_snapshot", None)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as exc:
        logger.debug("Run %s: no configuration snapshot (%s).", getattr(sim, "sim_id", "?"), exc)
        return None
    if not isinstance(snapshot, dict):
        return None
    payload = (snapshot.get("geographic") or {}).get("snap_streams")
    if payload is None:
        return None
    setting = SnapStreamsConfig.model_validate(payload)
    return setting if setting.enabled else None


def snapped_network_frame(
    snap: StreamSnap, cell_centroids: np.ndarray, *, crs: str | None
) -> gpd.GeoDataFrame:
    """Return the snapped map as one point per mapped cell of the catchment."""
    import geopandas as gpd

    centres = np.asarray(cell_centroids, dtype=float)
    raw_cells = np.flatnonzero(snap.raw)
    targets = snap.target[raw_cells]
    placed_at = np.where(targets >= 0, targets, raw_cells)
    return gpd.GeoDataFrame(
        {
            "raw_cell": raw_cells.astype("int64"),
            "snapped_cell": targets.astype("int64"),
            "status": [SNAP_STATUS_LABELS[int(code)] for code in snap.status[raw_cells]],
            "displacement_m": snap.displacement_m[raw_cells].astype("float64"),
            "raw_x": centres[raw_cells, 0],
            "raw_y": centres[raw_cells, 1],
            "accumulation_percentile": snap.accumulation_percentile[raw_cells].astype("float64"),
        },
        geometry=gpd.points_from_xy(centres[placed_at, 0], centres[placed_at, 1]),
        crs=crs,
    )


def write_snapped_network(
    store: Any,
    sim_id: str,
    snap: StreamSnap,
    cell_centroids: np.ndarray,
    *,
    crs: str | None,
    map_role: MapRole = "maximal",
) -> bool:
    """Store the snapped map with a run, as one geographic feature.

    Returns False when the catchment holds no mapped cell, so nothing is written.
    """
    frame = snapped_network_frame(snap, cell_centroids, crs=crs)
    if frame.empty:
        return False
    store.write_geographic_feature(sim_id, SNAPPED_NETWORK_FEATURES[map_role], frame)
    return True


def persist_snapped_networks(sim: Run, store: Any) -> tuple[MapRole, ...]:
    """Store the snapped maps of a run whose snap is on, and return their roles.

    The snap is rebuilt through the construction the figures redraw it with,
    from the setting the run sealed, so the stored map is the map they draw.
    The maximal map is the ``reference`` network, the minimal one the
    ``reference_permanent`` network when the run carries it. The seepage
    threshold is left at zero: the snap does not read it, and the run is then
    not asked for a recharge budget.

    A map that cannot be rebuilt is logged as a warning and not stored: the
    run itself stays valid, only its record of the snap is missing.
    """
    if snap_settings_of_run(sim) is None:
        return ()
    # Imported here: both modules import this one.
    from hydromodpy.results.derive.stream_extent import MAXIMAL_ROLE, MINIMAL_ROLE
    from hydromodpy.results.derive.stream_network import (
        network_comparison_from_run,
        unavailable_reason_for_comparison,
    )

    stored: list[MapRole] = []
    roles: tuple[tuple[MapRole, str], ...] = (
        ("maximal", MAXIMAL_ROLE),
        ("minimal", MINIMAL_ROLE),
    )
    for map_role, network_role in roles:
        if map_role == "minimal" and not sim.has_hydrographic_network(network_role):
            continue
        reason = unavailable_reason_for_comparison(sim, role=network_role)
        if reason is not None:
            logger.warning(
                "Run %s: the snapped %s map is not stored: %s.", sim.sim_id, map_role, reason
            )
            continue
        try:
            geometry = network_comparison_from_run(
                sim, role=network_role, tau_specific_ratio=0.0
            ).geometry
        except _UNREBUILDABLE as exc:
            logger.warning(
                "Run %s: the snapped %s map is not stored: %s", sim.sim_id, map_role, exc
            )
            continue
        snap = geometry.snap
        if snap is not None and write_snapped_network(
            store,
            sim.sim_id,
            snap,
            geometry.metric.centroids,
            crs=sim.mesh.crs,
            map_role=map_role,
        ):
            stored.append(map_role)
    return tuple(stored)


def stored_snapped_network(sim: Run, *, map_role: MapRole = "maximal") -> gpd.GeoDataFrame | None:
    """Return the snapped map a run stored, or None when it stored none."""
    try:
        frame = sim.geographic(SNAPPED_NETWORK_FEATURES[map_role])
    except (KeyError, ValueError, FileNotFoundError):
        return None
    if frame is None or frame.empty:
        return None
    return frame


def snapped_mask_from_frame(frame: Any, n_cells: int) -> np.ndarray:
    """Return the snapped map a stored feature describes, as a cell mask.

    A placed cell marks the cell it moved onto, a rejected cell its own.
    """
    raw = np.asarray(frame["raw_cell"], dtype=int)
    target = np.asarray(frame["snapped_cell"], dtype=int)
    mask = np.zeros(int(n_cells), dtype=bool)
    mask[np.where(target >= 0, target, raw)] = True
    return mask


def snap_of_comparison(comparison: Any) -> StreamSnap:
    """Return the snap a redrawn comparison carries, or raise when it has none."""
    snap = getattr(comparison.geometry, "snap", None)
    if snap is None:
        raise ValueError("this comparison was rebuilt without a snap: the run's snap is off.")
    return snap


def displacement_by_status(snap: StreamSnap) -> dict[str, np.ndarray]:
    """Return the displacement of the placed mapped cells, grouped by status."""
    grouped: dict[str, np.ndarray] = {}
    for code, label in SNAP_STATUS_LABELS.items():
        if code == SNAP_UNMAPPED:
            continue
        cells = snap.raw & (snap.status == code)
        grouped[label] = snap.displacement_m[cells]
    return grouped


__all__ = (
    "SNAPPED_NETWORK_COLUMNS",
    "SNAPPED_NETWORK_FEATURES",
    "MapRole",
    "displacement_by_status",
    "persist_snapped_networks",
    "snap_of_comparison",
    "snap_settings_of_run",
    "snapped_mask_from_frame",
    "snapped_network_frame",
    "stored_snapped_network",
    "write_snapped_network",
)
