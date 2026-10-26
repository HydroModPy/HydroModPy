"""Head series at the lower, middle and upper part of the compared domain.

The cells come from the surface elevation the reference run stores in its own
``fields.zarr``. The active cells are sorted by elevation and cut in three
groups of equal size, and each group is drawn by its median cell. A run that
stores no surface elevation gets no figure, and the reason is written next to
the figures.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.runtime import (
    RunSource,
    is_nodata_value,
    load_variable_series,
    open_run_source,
)
from hydromodpy.analysis.comparison.visuals_render_series import write_timeseries_figure
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

SKIPPED_FILENAME = "head_domain_figures_skipped.json"
"""Written in the comparison folder when the figures cannot be drawn, with the reason."""

_THIRDS = (
    ("low", "lower domain"),
    ("mid", "middle domain"),
    ("high", "upper domain"),
)


class _CannotDrawError(Exception):
    """The reason the three figures cannot be drawn for this comparison."""


def write_domain_head_figures(
    *,
    root: Path,
    rows: list[dict[str, str]],
    manifest: Mapping[str, Any],
) -> None:
    """Draw the head series of the lower, middle and upper domain of a comparison.

    ``rows`` are the rows of ``observables.csv``. The figures land in
    ``comparison_figures/``. When the cells cannot be placed by elevation, no
    figure is drawn and ``head_domain_figures_skipped.json`` says why.
    """
    figure_root = root / "comparison_figures"
    _remove_previous_outputs(root, figure_root)
    reference_id, active = _reference_active_cells(rows, manifest)
    if active.size < 3:
        return
    try:
        surface = _reference_surface(manifest, reference_id)
        if int(active.max()) >= surface.size:
            raise _CannotDrawError(
                f"the head map of the reference run '{reference_id}' reads cell "
                f"{int(active.max())} but its stored surface has {surface.size} cells"
            )
        picks = pick_domain_thirds(surface, active)
        if not picks:
            raise _CannotDrawError(
                f"fewer than three active cells of the reference run '{reference_id}' "
                "have a surface elevation"
            )
    except _CannotDrawError as exc:
        reason = str(exc)
        (root / SKIPPED_FILENAME).write_text(
            json.dumps(
                {"reference_simulation": reference_id, "reason": reason},
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        logger.warning("Head domain figures not drawn: %s.", reason)
        return
    profiles = _domain_head_series(manifest, picks, n_cells=int(surface.size))
    if not profiles:
        return
    figure_root.mkdir(parents=True, exist_ok=True)
    for profile_id, label, grouped_rows in profiles:
        if not grouped_rows:
            continue
        path = figure_root / f"head_domain_{profile_id}_series__timeseries.png"
        try:
            write_timeseries_figure(
                path=path,
                observable_name=f"head_domain_{profile_id}_series",
                unit="m",
                grouped_rows=grouped_rows,
                point_label=label,
            )
        except Exception as exc:
            logger.warning("Head domain figure '%s' not drawn: %s.", path.name, exc)


def pick_domain_thirds(surface: np.ndarray, cells: np.ndarray) -> list[tuple[str, str, int]]:
    """Return ``(profile_id, label, cell)`` of the median cell of each elevation third.

    ``cells`` are the active cells and ``surface`` the elevation of every cell of
    the run. The cells are sorted by elevation, the lowest first, and cut in
    three groups of equal size. A cell without a finite elevation is left out.
    Returns an empty list when fewer than three cells remain.
    """
    candidates = np.unique(np.asarray(cells, dtype=np.int64))
    candidates = candidates[(candidates >= 0) & (candidates < surface.size)]
    elevation = np.asarray(surface, dtype=float)[candidates]
    usable = np.array([not is_nodata_value(value) for value in elevation.tolist()], dtype=bool)
    candidates, elevation = candidates[usable], elevation[usable]
    if candidates.size < 3:
        return []
    ordered = candidates[np.argsort(elevation, kind="stable")]
    return [
        (profile_id, label, int(group[group.size // 2]))
        for (profile_id, label), group in zip(_THIRDS, np.array_split(ordered, 3), strict=True)
    ]


def _remove_previous_outputs(root: Path, figure_root: Path) -> None:
    (root / SKIPPED_FILENAME).unlink(missing_ok=True)
    if not figure_root.is_dir():
        return
    for path in figure_root.glob("head_domain_*_series__timeseries.png"):
        path.unlink(missing_ok=True)


def _reference_active_cells(
    rows: list[dict[str, str]],
    manifest: Mapping[str, Any],
) -> tuple[str, np.ndarray]:
    """Return the reference run and the cells of its first head map that hold a head."""
    head_map_rows = [
        row
        for row in rows
        if str(row.get("support", "")) == "map"
        and str(row.get("observable", "")).startswith("head_map")
        and _float_or_none(row.get("value")) is not None
        and str(row.get("is_nodata", "")).strip().lower() not in {"true", "1", "yes"}
    ]
    if not head_map_rows:
        return "", np.empty(0, dtype=np.int64)
    reference = str(manifest.get("reference_simulation", "")).strip()
    if not any(str(row.get("simulation_id", "")) == reference for row in head_map_rows):
        reference = str(head_map_rows[0].get("simulation_id", ""))
    reference_rows = [
        row for row in head_map_rows if str(row.get("simulation_id", "")) == reference
    ]
    first_key = min(_profile_time_key(row) for row in reference_rows)
    indices = {
        int(index)
        for row in reference_rows
        if _profile_time_key(row) == first_key
        and (index := _float_or_none(row.get("value_index"))) is not None
    }
    return reference, np.array(sorted(indices), dtype=np.int64)


def _reference_surface(manifest: Mapping[str, Any], reference_id: str) -> np.ndarray:
    """Return the surface elevation of every cell of the reference run, from its store."""
    summary = next(
        (
            item
            for item in manifest.get("simulations", [])
            if isinstance(item, Mapping) and str(item.get("id", "")) == reference_id
        ),
        None,
    )
    source = None if summary is None else open_run_source(summary)
    if source is None:
        raise _CannotDrawError(f"the reference run '{reference_id}' cannot be opened")
    with source:
        return _stored_surface(source, reference_id)


def _stored_surface(source: RunSource, run_id: str) -> np.ndarray:
    """Read ``mesh/topography``, else the top of ``mesh/z_interfaces``, of the run's store."""
    try:
        handle = source.open_zarr(source.sim_id)
    except FileNotFoundError:
        raise _CannotDrawError(f"the run '{run_id}' has no fields.zarr") from None
    try:
        mesh = handle.root.get("mesh")
        if mesh is not None and "topography" in mesh:
            return np.asarray(mesh["topography"][:], dtype=float).reshape(-1)
        if mesh is not None and "z_interfaces" in mesh:
            return np.asarray(mesh["z_interfaces"][0], dtype=float).reshape(-1)
    finally:
        handle.close()
    raise _CannotDrawError(
        f"the run '{run_id}' stores neither mesh/topography nor mesh/z_interfaces in its "
        "fields.zarr, so its cells cannot be ordered by surface elevation"
    )


def _domain_head_series(
    manifest: Mapping[str, Any],
    picks: Sequence[tuple[str, str, int]],
    *,
    n_cells: int,
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """Return the water table of each picked cell for every run on the reference mesh."""
    simulations = manifest.get("simulations", [])
    if not isinstance(simulations, list):
        return []
    profiles: dict[str, tuple[str, list[dict[str, Any]]]] = {
        profile_id: (label, []) for profile_id, label, _ in picks
    }
    for simulation in simulations:
        if not isinstance(simulation, Mapping):
            continue
        if str(simulation.get("status", "")).strip().lower() not in {"completed", "reused"}:
            continue
        source = open_run_source(simulation)
        if source is None:
            continue
        simulation_id = str(simulation.get("id", "") or "")
        simulation_label = str(simulation.get("label", simulation_id) or simulation_id)
        solver = str(simulation.get("solver", "") or "")
        try:
            series = load_variable_series(
                variable="watertable_elevation",
                store=source,
                sim_id=source.sim_id,
            )
            for profile_id, _, cell in picks:
                _, grouped_rows = profiles[profile_id]
                for time_order, time_slice in enumerate(series.slices):
                    values = time_slice.values.ravel()
                    # Another mesh has other cells under the same indices.
                    if int(values.size) != n_cells:
                        continue
                    value = _float_or_none(values[cell])
                    if value is None:
                        continue
                    grouped_rows.append(
                        {
                            "simulation_id": simulation_id,
                            "simulation_label": simulation_label,
                            "solver": solver,
                            "observable": f"head_domain_{profile_id}_series",
                            "support": "point",
                            "time_index": time_slice.time_index,
                            "elapsed_seconds": (
                                ""
                                if time_slice.elapsed_seconds is None
                                else float(time_slice.elapsed_seconds)
                            ),
                            "selection_time_order": time_order,
                            "value_index": 0,
                            "value": value,
                            "unit": "m",
                        }
                    )
        except FileNotFoundError:
            # A run without a stored head has no profile to draw.
            continue
        finally:
            source.close()
    return [
        (profile_id, label, grouped_rows)
        for profile_id, (label, grouped_rows) in profiles.items()
        if _profile_has_two_methods(grouped_rows)
    ]


def _profile_time_key(row: Mapping[str, Any]) -> tuple[float, str]:
    elapsed = _float_or_none(row.get("elapsed_seconds"))
    if elapsed is not None:
        return elapsed, str(row.get("observable", ""))
    time_index = _float_or_none(row.get("time_index"))
    if time_index is not None:
        return time_index, str(row.get("observable", ""))
    return math.inf, str(row.get("observable", ""))


def _profile_has_two_methods(rows: list[Mapping[str, Any]]) -> bool:
    by_simulation: dict[str, int] = {}
    for row in rows:
        if _float_or_none(row.get("value")) is None:
            continue
        simulation_id = str(row.get("simulation_id", "")).strip()
        if not simulation_id:
            continue
        by_simulation[simulation_id] = by_simulation.get(simulation_id, 0) + 1
    return sum(1 for count in by_simulation.values() if count >= 2) >= 2


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


__all__ = ("SKIPPED_FILENAME", "pick_domain_thirds", "write_domain_head_figures")
