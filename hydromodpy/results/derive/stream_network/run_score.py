"""Score the network criterion of a stored run again, as its calibration trial scored it.

A trial scores the stream network once and keeps the numbers in its journal. This
module gives the same numbers from what the run stored: the release field, the
mesh, the maps, the criterion recharge and the settings of the network output the
run sealed, or the defaults of that output when it sealed none. The geometry is the
one a figure redraws (:func:`~hydromodpy.results.derive.stream_network.comparison.criterion_geometry`),
and the distances come from
:mod:`hydromodpy.results.derive.stream_network.criterion_score`, which the trial
calls too.

A steady run, or an output without ``model.extent``, is scored in one state. A
transient run whose output declares ``model.extent``, or a transient run that
sealed no network output, is scored in the two-bound mode, its release field read
by blocks of timesteps. The geometry of runs that share mesh, maps, recharge and
settings is built once, in the ``geometries`` dict a caller passes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.catchment.algorithms.hydrographic_network import cut_network
from hydromodpy.catchment.stream_network.cost import MAXIMAL_SUFFIX, MINIMAL_SUFFIX
from hydromodpy.catchment.stream_network.extent import (
    YearlyFlowCounts,
    calendar_years,
    dry_steps,
    extent_step_problems,
    flowing_steps,
    parse_extent_duration,
)
from hydromodpy.catchment.stream_network.geometry import share_outside
from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.scoring.stream_defaults import parse_visible_flow
from hydromodpy.results.derive.stream_network.comparison import (
    DrawnGeometry,
    _cut_of_the_map,
    _snapped_outlet_of,
    criterion_geometry,
    has_recharge_source,
    no_recharge_reason,
    unavailable_reason_for_comparison,
)
from hydromodpy.results.derive.stream_network.criterion_score import (
    SHARED_GEOMETRY_KEYS,
    ScoredMap,
    score_extent,
    score_one_state,
)
from hydromodpy.results.derive.stream_network.criterion_settings import (
    NetworkCriterionSettings,
    network_criterion_settings,
    network_outputs_of_run,
)
from hydromodpy.results.derive.stream_network.run_extent import (
    MAXIMAL_ROLE,
    MINIMAL_ROLE,
    block_flow_counts,
    run_step_days,
    run_step_edges,
)
from hydromodpy.results.score_table import NetworkWindowArg, close_window

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.run.view import Run

__all__ = (
    "NETWORK_SCORE_COLUMNS",
    "network_score_table",
)

NETWORK_SCORE_COLUMNS = (
    "sim_id",
    "run",
    "output",
    "mode",
    "window_name",
    "window_start",
    "window_end",
    "bound",
    "year",
    "quantity",
    "value",
)
"""The long table of :func:`network_score_table`, one row per quantity."""

_DATA_LAYER = "data.hydrography"
_ONE_STATE = "one_state"
_TWO_BOUNDS = "two_bounds"
_SHARED_QUANTITIES = ("frac_minimal_outside_maximal",)
"""Keys that end like a bound suffix and qualify no bound."""

_GEOMETRY_SETTINGS = (
    "tau_specific_ratio",
    "diagonal_neighbors",
    "observed_rasterization",
    "observed_position_accuracy_m",
    "heads_snap_radius_m",
    "heads_min_drained_area_km2",
    "clip_map_to_catchment",
)
"""The settings the geometry is built with, and so part of the key it is kept under."""


@dataclass(frozen=True, slots=True)
class _RunMaps:
    """The maps one run is scored against, and the share of the minimal one left out."""

    maximal: ScoredMap
    minimal: ScoredMap | None
    frac_minimal_outside_maximal: float


def network_score_table(
    sim: Run,
    *,
    output: str | None = None,
    window: NetworkWindowArg = None,
    project_root: Path | None = None,
    geometries: MutableMapping[str, _RunMaps] | None = None,
) -> pd.DataFrame:
    """Return the network criterion of one stored run, in the long form of the columns.

    ``output`` names the sealed network output, None its only one or the defaults.
    ``window`` picks the complete years the two-bound mode scores: None reads the
    window the run was scored with, else the whole run. One state reads the state
    of the output and no window, so its window columns are empty. A map written as
    a file is read from ``project_root`` when its path is relative. ``geometries``
    keeps the built maps across calls, keyed by what they are built from.
    """
    if output is not None and output not in network_outputs_of_run(sim):
        raise NothingThereError(f"run {sim.sim_id} sealed no network output {output!r}.")
    settings = network_criterion_settings(sim, output=output)
    if settings.tau_specific_ratio != 0.0 and not has_recharge_source(sim):
        raise NothingThereError(
            f"network score unavailable for {sim.sim_id}: {no_recharge_reason()}"
        )
    maps = _run_maps(sim, settings, project_root=project_root, geometries=geometries)
    extent = settings.extent
    two_bounds = extent is not None or (settings.output is None and _n_steps(sim) > 1)
    name = settings.output or "network"
    frames: list[pd.DataFrame] = []
    if not two_bounds:
        release = _release_state(sim, settings.timestep, maps.maximal)
        pair, scored = score_one_state(
            release,
            maps.maximal,
            maps.minimal,
            calibrate_on_complete=not settings.scores_permanent_map,
            weighting=settings.weighting,
            validity_length_m=settings.validity_length_m,
        )
        frames.append(_rows(scored, pair, maps, mode=_ONE_STATE, window=(None, None, None)))
    else:
        edges = run_step_edges(sim)
        for window_name, bounds in _windows(window, settings):
            pair, scored = _score_two_bounds(sim, name, settings, maps, bounds)
            shown = (window_name, *_shown_bounds(bounds, edges))
            frames.append(_rows(scored, pair, maps, mode=_TWO_BOUNDS, window=shown))
    table = pd.concat(frames, ignore_index=True)
    table.insert(0, "output", settings.output)
    table.insert(0, "run", Path(sim.dir).name)
    table.insert(0, "sim_id", str(sim.sim_id))
    return table[list(NETWORK_SCORE_COLUMNS)]


def _n_steps(sim: Run) -> int:
    """Return how many states the run stored, one when it cannot say."""
    return max(1, int(getattr(sim, "n_timesteps", 0) or 0))


def _windows(
    window: NetworkWindowArg, settings: NetworkCriterionSettings
) -> list[tuple[str, tuple[pd.Timestamp | None, pd.Timestamp | None]]]:
    """Return the named windows of the two-bound mode, naive, either bound None when open."""
    if window is None:
        if settings.window is not None:
            return [("calibration", settings.window)]
        return [("all", (None, None))]
    items = list(window.items()) if isinstance(window, Mapping) else [("window", window)]
    named = []
    for window_name, (start, end) in items:
        named.append((str(window_name), (_naive(start), _naive(end))))
    return named


def _shown_bounds(
    bounds: tuple[pd.Timestamp | None, pd.Timestamp | None], edges: np.ndarray | None
) -> tuple[date | None, date | None]:
    """Return a window as the dates ``Run.score`` writes, an open bound closed on the run.

    An open start is the start of the first period, an open end the last stamp, so
    the rows join the rows of ``Run.score`` on the same window.
    """
    start, end = bounds
    first = None if edges is None else pd.Timestamp(edges[0]).date()
    last = None if edges is None else pd.Timestamp(edges[-1]).date()
    return close_window(
        None if start is None else start.date(),
        None if end is None else end.date(),
        first,
        last,
    )


def _naive(value: Any) -> pd.Timestamp | None:
    """Return a window bound as a naive timestamp on its wall clock, or None."""
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    return stamp.tz_localize(None) if stamp.tz is not None else stamp


def _release_state(sim: Run, timestep: int, maximal: ScoredMap) -> np.ndarray:
    """Return the release field of the one state scored, refused on another mesh."""
    release = np.asarray(sim.field("release_flux", time=timestep), dtype=float).reshape(-1)
    n_cells = int(maximal.geometry.metric.graph.active.size)
    if release.size != n_cells:
        raise ValueError(
            f"release_flux holds {release.size} cells and the mesh holds {n_cells}; "
            "they were not written for the same run."
        )
    return release


def _score_two_bounds(
    sim: Run,
    name: str,
    settings: NetworkCriterionSettings,
    maps: _RunMaps,
    window: tuple[pd.Timestamp | None, pd.Timestamp | None],
) -> tuple[list[float], dict[str, float]]:
    """Score the extents of the complete years ``window`` holds, as a trial does."""
    where = f"network score of {sim.sim_id}"
    rules = settings.extent_rules
    edges = run_step_edges(sim)
    if edges is None:
        raise NothingThereError(f"{where}: the run has no time axis to split into years.")
    bounds = None if window == (None, None) else window
    years = calendar_years(edges, window=bounds)
    if not years.years:
        raise NothingThereError(
            f"{where}: the window {window[0] or 'open'} to {window[1] or 'open'} holds no "
            f"complete calendar year of the run (outside: {list(years.outside_window)}, "
            f"incomplete: {list(years.incomplete)})."
        )
    step_days = run_step_days(sim)
    if step_days is None:
        raise NothingThereError(
            f"{where}: the run sealed no timestep (simulation.time.step_value) to count "
            "the extent durations in."
        )
    maximal_steps = flowing_steps(parse_extent_duration(rules.maximal_flowing_duration), step_days)
    dry = dry_steps(parse_extent_duration(rules.minimal_dry_duration), step_days)
    problems = extent_step_problems(
        years.n_steps, maximal_flowing_steps=maximal_steps, minimal_dry_steps=dry
    )
    if problems:
        raise ValueError(f"{where}: the extent rules cannot be read: " + "; ".join(problems))
    visible = parse_visible_flow(rules.visible_flow)
    blocks = block_flow_counts(sim, maps.maximal.geometry, years.steps, visible_flow=visible)
    counts = YearlyFlowCounts(
        years=years.years, n_steps=years.n_steps, flowing=blocks.flowing, seepage=blocks.seepage
    )
    return score_extent(
        name,
        counts,
        years,
        maps.maximal,
        maps.minimal,
        maximal_flowing_steps=maximal_steps,
        minimal_dry_steps=dry,
        year_quorum=rules.year_quorum,
        weights=settings.bound_weights,
        weighting=settings.weighting,
        validity_length_m=settings.validity_length_m,
        step_days=step_days,
        visible=visible,
    )


def _rows(
    scored: Mapping[str, float],
    pair: list[float],
    maps: _RunMaps,
    *,
    mode: str,
    window: tuple[str | None, pd.Timestamp | None, pd.Timestamp | None],
) -> pd.DataFrame:
    """Return the components of one score as rows of bound, year and quantity."""
    geometry = maps.maximal.geometry
    shared = {
        **{key: float(geometry.diagnostics[key]) for key in SHARED_GEOMETRY_KEYS},
        "n_bounds_scored": float(len(pair) // 2),
        "cell_spacing_m": float(geometry.h_obs_m),
    }
    if maps.minimal is not None:
        shared["frac_minimal_outside_maximal"] = maps.frac_minimal_outside_maximal
    suffixed = {key for key in scored if _bound_of(key)[1] is not None}
    records: list[dict[str, Any]] = []
    for key, value in {**scored, **shared}.items():
        quantity, bound, year = _bound_of(key)
        if (
            bound is None
            and year is None
            and any(
                f"{quantity}{suffix}" in suffixed for suffix in (MAXIMAL_SUFFIX, MINIMAL_SUFFIX)
            )
        ):
            # One bound publishes its distances twice, bare and suffixed: keep the suffixed.
            continue
        records.append(
            {
                "mode": mode,
                "window_name": window[0],
                "window_start": window[1],
                "window_end": window[2],
                "bound": bound,
                "year": year,
                "quantity": quantity,
                "value": float(value),
            }
        )
    frame = pd.DataFrame.from_records(records)
    frame["year"] = frame["year"].astype("Int64")
    return frame


def _bound_of(key: str) -> tuple[str, str | None, int | None]:
    """Split ``J_signed_minimal_y2001`` into ``("J_signed", "minimal", 2001)``."""
    year: int | None = None
    stem = key
    if len(stem) > 6 and stem[-6:-4] == "_y" and stem[-4:].isdigit():
        year = int(stem[-4:])
        stem = stem[:-6]
    if stem in _SHARED_QUANTITIES:
        return stem, None, year
    for suffix in (f"{MAXIMAL_SUFFIX}_validation", f"{MINIMAL_SUFFIX}_validation"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)], suffix[1:], year
    for suffix in (MAXIMAL_SUFFIX, MINIMAL_SUFFIX):
        if stem.endswith(suffix):
            return stem[: -len(suffix)], suffix[1:], year
    return stem, None, year


def _run_maps(
    sim: Run,
    settings: NetworkCriterionSettings,
    *,
    project_root: Path | None,
    geometries: MutableMapping[str, _RunMaps] | None,
) -> _RunMaps:
    """Return the maps of the run, built once per key in ``geometries``."""
    reason = unavailable_reason_for_comparison(sim, role=None)
    if reason is not None:
        raise NothingThereError(f"network score unavailable for {sim.sim_id}: {reason}")
    complete, complete_clipped = _map_of(
        sim, settings.complete_map, MAXIMAL_ROLE, settings, project_root
    )
    permanent: gpd.GeoDataFrame | None = None
    if settings.permanent_map is not None:
        permanent, permanent_clipped = _map_of(
            sim, settings.permanent_map, MINIMAL_ROLE, settings, project_root
        )
    key = _maps_key(sim, settings, complete, permanent)
    if geometries is not None and key in geometries:
        return geometries[key]
    build = {name: getattr(settings, name) for name in _GEOMETRY_SETTINGS}
    if permanent is None:
        drawn = criterion_geometry(sim, [complete], **build)
        maps = _RunMaps(
            maximal=_scored(drawn, complete_clipped),
            minimal=None,
            frac_minimal_outside_maximal=np.nan,
        )
    else:
        # The maximal map is scored on the union of the two, as a trial scores it.
        union = criterion_geometry(sim, [complete, permanent], **build)
        minimal = criterion_geometry(sim, [permanent], **build)
        own = criterion_geometry(sim, [complete], **build).geometry.observed
        maps = _RunMaps(
            maximal=_scored(union, complete_clipped),
            minimal=_scored(minimal, permanent_clipped),
            frac_minimal_outside_maximal=share_outside(
                minimal.geometry.observed, own, union.geometry
            ),
        )
    if geometries is not None:
        geometries[key] = maps
    return maps


def _scored(drawn: DrawnGeometry, clipped: bool) -> ScoredMap:
    """Return one map with the facts a trial publishes beside it."""
    return ScoredMap(
        geometry=drawn.geometry,
        facts={
            "observed_network_clipped": 1.0 if clipped else 0.0,
            "n_observed_cells": float(int(np.asarray(drawn.geometry.observed).sum())),
            "n_observed_features_fallback": float(drawn.n_fallback_parts),
        },
    )


def _map_of(
    sim: Run,
    source: str | None,
    role: str,
    settings: NetworkCriterionSettings,
    project_root: Path | None,
) -> tuple[gpd.GeoDataFrame, bool]:
    """Return one map the output scores, and whether the data layer cut it.

    ``data.hydrography`` and the defaults read the network the run stored under
    ``role``. A file is read and cut as the trial cut it: to the watershed the run
    stored, unless ``map.clip_to_catchment = false`` or the file declares no CRS. A
    file a trial cut to ``[data.hydrography] mask_path`` is refused, since the run
    does not store that mask.
    """
    where = f"network score of {sim.sim_id}"
    if source is None or source == _DATA_LAYER:
        if not sim.has_hydrographic_network(role):
            raise NothingThereError(f"{where}: the run stored no {role!r} hydrographic network.")
        network = sim.hydrographic_network(role)
        if network is None or network.empty:
            raise NothingThereError(f"{where}: the {role!r} network of the run holds no feature.")
        return network, True
    import geopandas as gpd

    path = Path(source)
    if not path.is_absolute():
        path = (project_root if project_root is not None else Path(sim.dir)) / path
    if not path.is_file():
        raise NothingThereError(f"{where}: the map file {str(path)!r} is not there any more.")
    network = gpd.read_file(path)
    if network.empty:
        raise NothingThereError(f"{where}: the map file {str(path)!r} holds no feature.")
    if not settings.clip_map_to_catchment or network.crs is None:
        return network, False
    if _mask_path(sim):
        raise NothingThereError(
            f"{where}: the trial cut the map {source!r} to [data.hydrography] mask_path, "
            "which the run does not store. Declare the map under [data.hydrography] so the "
            "run stores it, or write map.clip_to_catchment = false."
        )
    cut = _cut_of_the_map(sim)
    if not cut:
        return network, False
    frame = cut_network(network, cut["cut_outline"], cut["cut_crs"])
    frame = frame[~frame.geometry.is_empty & ~frame.geometry.isna()]
    if frame.empty:
        raise NothingThereError(
            f"{where}: the map {source!r} holds no line inside the watershed of the run."
        )
    return frame, True


def _mask_path(sim: Run) -> Any:
    """Return the ``[data.hydrography] mask_path`` the run sealed, or None."""
    snapshot = getattr(sim, "config_snapshot", None)
    data = snapshot.get("data") if isinstance(snapshot, Mapping) else None
    hydrography = data.get("hydrography") if isinstance(data, Mapping) else None
    return hydrography.get("mask_path") if isinstance(hydrography, Mapping) else None


def _maps_key(
    sim: Run,
    settings: NetworkCriterionSettings,
    complete: gpd.GeoDataFrame,
    permanent: gpd.GeoDataFrame | None,
) -> str:
    """Return what the maps of a run are built from, as one digest.

    The mesh and its top, the cells of open water and of the outline, the outlet,
    the criterion recharge, the lines of each map and the geometry settings.
    """
    digest = hashlib.sha256()
    mesh = sim.mesh
    for array in (
        mesh.vertices,
        mesh.face_node_connectivity,
        mesh.topography,
        mesh.cell_centers(),
        sim.descent.open_water(),
        sim.descent.catchment_cells(),
        sim.descent.dam_foot,
    ):
        digest.update(b"|" if array is None else np.ascontiguousarray(array).tobytes())
    digest.update(repr(_snapped_outlet_of(sim)).encode())
    digest.update(repr(sim.descent.criterion_recharge()).encode())
    digest.update(repr(str(mesh.crs)).encode())
    for network in (complete, permanent):
        if network is not None:
            digest.update(str(network.crs).encode())
            for geometry in network.geometry:
                digest.update(geometry.wkb)
        digest.update(b"#")
    for name in _GEOMETRY_SETTINGS:
        digest.update(f"{name}={getattr(settings, name)!r};".encode())
    return digest.hexdigest()
