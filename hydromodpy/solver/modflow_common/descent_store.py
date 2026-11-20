"""Hand the descent D the build saved to the run store, for both backends.

The build writes ``<model>.descent.npz`` in the solver folder. The extractors
do not see the model, so they find it there and write it under
``fields.zarr/mesh/`` right after the mesh. Figures and the accumulation of
cell fluxes read it from there. The basin of D at the catchment outlet travels
in the same sidecar and lands beside D as ``mesh/descent_basin``, with its
outlet, and the share of each cell's area inside the delineated polygon as
``mesh/catchment_fraction`` when the run has one. A run without the sidecar
gets no D in its store: its readers rebuild one from the stored top and say
so. A sidecar written before the basin was stored gives a D without a basin,
and its readers name the old support they fall back to.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

import numpy as np

from hydromodpy.catchment.drainage.descent import BASIN_VERSION, BasinRule, Descent, DescentBasin
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.flow_directions import DESCENT_EPSILON_M

__all__ = [
    "descent_sidecar_path",
    "write_descent_sidecar_to_store",
    "DESCENT_SIDECAR_SUFFIX",
    "DescentRecord",
    "read_descent_sidecar",
    "write_descent_sidecar",
]

logger = get_logger(__name__)


def descent_sidecar_path(solver_output_dir: Path) -> Path | None:
    """Return the descent sidecar the build left in the solver folder, None without one."""
    files = sorted(Path(solver_output_dir).glob(f"*{DESCENT_SIDECAR_SUFFIX}"))
    return files[0] if files else None


def write_descent_sidecar_to_store(
    sz: Any,
    solver_output_dir: Path,
    *,
    sim_id: str,
    n_cells: int,
) -> bool:
    """Write the build's descent into ``sz``; return whether it was written.

    Never raises: the mesh is already stored and a bad sidecar must not cost
    it. A missing sidecar is an INFO line (an old scratch, a backend that
    builds no descent); a sidecar that is unreadable or does not match the
    mesh is a warning that names what reads the descent.
    """
    sidecar = descent_sidecar_path(solver_output_dir)
    if sidecar is None:
        logger.info(
            "Run %s: no descent sidecar in %s, so no descent is stored. Readers rebuild one "
            "from the stored top, without channel pins, constant-head seeds or lakes.",
            sim_id,
            solver_output_dir,
        )
        return False
    try:
        record = read_descent_sidecar(sidecar)
        if record is None:
            logger.info("Run %s: %s holds no descent; nothing stored.", sim_id, sidecar.name)
            return False
        if int(record.receiver.size) != int(n_cells):
            raise ValueError(
                f"the descent holds {int(record.receiver.size)} cells, the mesh {int(n_cells)}."
            )
        sz.write_descent(
            receiver=record.receiver,
            surface=record.surface,
            base_level=record.base_level,
            constant_head=record.constant_head,
            raised=record.raised,
            channel=record.channel,
            pinned=record.pinned,
            dam_foot=record.dam_foot,
            basin=record.basin,
            basin_attrs=_basin_attrs(record),
            catchment_fraction=record.catchment_fraction,
            attrs={
                "adjacency": str(record.adjacency),
                "epsilon": float(record.epsilon),
                **record.report(),
                "n_channel": int(record.n_channel),
                "n_pinned": int(record.n_pinned),
            },
        )
    except Exception:
        logger.warning(
            "Could not store the descent of run %s from %s; the flow direction map and the "
            "accumulation fluxes of this run rebuild one without channel pins.",
            sim_id,
            sidecar.name,
            exc_info=True,
        )
        return False
    return True


def _basin_attrs(record: DescentRecord) -> dict[str, object] | None:
    """Return the attributes of ``mesh/descent_basin``, ``None`` without a basin."""
    if record.basin is None:
        return None
    return {
        "descent_outlet": int(record.basin_outlet),
        "basin_rule": str(record.basin_rule),
        "basin_area_m2": float(record.basin_area_m2),
        "basin_seeded_at_outlet": bool(record.basin_seeded_at_outlet),
        "basin_version": int(BASIN_VERSION),
    }


DESCENT_SIDECAR_SUFFIX = ".descent.npz"
"""Suffix of the file the build leaves beside the model for the extractor."""

_ADJACENCY_KINDS = ("shared_nodes", "shared_faces")

_REPORT_COUNTS = ("n_raised", "n_lake_flooded", "n_pinned_raised", "n_channel", "n_pinned")

_REPORT_MAXIMA_M = ("max_raise_m", "max_lake_flood_m", "max_pinned_raise_m")

_BASIN_KEYS = ("basin", "basin_outlet", "basin_rule", "basin_area_m2", "basin_seeded_at_outlet")

_FRACTION_KEY = "catchment_fraction"


@dataclass(frozen=True, slots=True)
class DescentRecord:
    """D as the run stores it: per-cell arrays and the build report.

    ``receiver`` is -1 at an outlet (off the graph, or a seed with no lower
    neighbor); ``surface`` is the filled copy, NaN off the graph.
    ``constant_head`` flags the declared CHD seeds, ``raised`` the cells the
    flood raised. ``dam_foot`` holds the cell ids below the dams, possibly
    none. ``adjacency`` is ``"shared_nodes"`` or ``"shared_faces"``;
    ``epsilon`` is the flood step in meters.

    ``basin`` is the basin of D at the catchment outlet (outlet included),
    with the fields of :class:`hydromodpy.catchment.drainage.descent.DescentBasin`. It is
    None for a sidecar written before the basin was stored.
    ``catchment_fraction`` is the share of each cell's area inside the
    delineated polygon, None without a polygon.
    """

    receiver: np.ndarray
    surface: np.ndarray
    base_level: np.ndarray
    constant_head: np.ndarray
    raised: np.ndarray
    channel: np.ndarray
    pinned: np.ndarray
    adjacency: str
    epsilon: float
    n_raised: int
    max_raise_m: float
    n_lake_flooded: int
    max_lake_flood_m: float
    n_pinned_raised: int
    max_pinned_raise_m: float
    n_channel: int
    n_pinned: int
    dam_foot: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    basin: np.ndarray | None = None
    basin_outlet: int = -1
    basin_rule: str = ""
    basin_area_m2: float = float("nan")
    basin_seeded_at_outlet: bool = False
    catchment_fraction: np.ndarray | None = None

    def report(self) -> dict[str, int | float]:
        """The build report as plain scalars, counts then maxima in meters."""
        counts: dict[str, int | float] = {name: int(getattr(self, name)) for name in _REPORT_COUNTS}
        counts.update({name: float(getattr(self, name)) for name in _REPORT_MAXIMA_M})
        return counts


def write_descent_sidecar(
    descent: Descent,
    folder: str | Path,
    stem: str,
    *,
    dam_foot_cells: Mapping[str, int] | None = None,
    basin: DescentBasin | None = None,
) -> Path | None:
    """Leave D beside the model as ``<stem>.descent.npz``; return its path.

    ``dam_foot_cells`` are the cells below the dams, one per lake
    (:func:`resolve_dam_foot_cells`); none when the run has no lake.
    ``basin`` is the basin of D at the catchment outlet (:func:`run_basin`).

    A file that cannot be written is a warning, not a failure: the run solves
    without it, and its readers rebuild an unpinned D from the stored top.
    """
    path = Path(folder) / f"{stem}{DESCENT_SIDECAR_SUFFIX}"
    payload: dict[str, np.ndarray] = {
        "receiver": np.asarray(descent.receiver, dtype=np.int64),
        "surface": np.asarray(descent.surface, dtype=np.float64),
        "base_level": np.asarray(descent.base_level, dtype=bool),
        "constant_head": np.asarray(descent.constant_head, dtype=bool),
        "raised": np.asarray(descent.raised, dtype=bool),
        "channel": np.asarray(descent.channel, dtype=bool),
        "pinned": np.asarray(descent.pinned, dtype=bool),
        "adjacency": np.asarray(_ADJACENCY_KINDS[0 if descent.diagonal_neighbors else 1]),
        "epsilon": np.asarray(DESCENT_EPSILON_M, dtype=np.float64),
        "dam_foot": np.asarray(sorted(set((dam_foot_cells or {}).values())), dtype=np.int64),
    }
    for name in _REPORT_COUNTS:
        payload[name] = np.asarray(int(getattr(descent, name)), dtype=np.int64)
    for name in _REPORT_MAXIMA_M:
        payload[name] = np.asarray(float(getattr(descent, name)), dtype=np.float64)
    if basin is not None:
        payload.update(
            {
                "basin": np.asarray(basin.mask, dtype=bool),
                "basin_outlet": np.asarray(int(basin.outlet), dtype=np.int64),
                "basin_rule": np.asarray(str(basin.rule)),
                "basin_area_m2": np.asarray(float(basin.area_m2), dtype=np.float64),
                "basin_seeded_at_outlet": np.asarray(bool(basin.seeded_at_outlet)),
            }
        )
        if basin.catchment_fraction is not None:
            payload[_FRACTION_KEY] = np.asarray(basin.catchment_fraction, dtype=np.float64)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, **payload)
    except OSError:
        logger.warning(
            "Could not write the descent sidecar %s: the run stores no descent, and its "
            "flow direction map and accumulation fluxes rebuild one without pins.",
            path,
            exc_info=True,
        )
        return None
    return path


def read_descent_sidecar(path: str | Path) -> DescentRecord | None:
    """Read the sidecar :func:`write_descent_sidecar` left, None when it is absent.

    Raises
    ------
    ValueError
        When the file lacks an array, its arrays disagree on the cell count,
        its adjacency is not one this module writes, a dam foot is not a cell
        of the mesh, its basin lacks a field, names an unknown rule or an
        outlet outside it, or its catchment fraction comes without a basin or
        leaves [0, 1].
    """
    path = Path(path)
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as payload:
        names = set(payload.files)
        expected = {
            "receiver",
            "surface",
            "base_level",
            "constant_head",
            "raised",
            "channel",
            "pinned",
            "adjacency",
            "epsilon",
            *_REPORT_COUNTS,
            *_REPORT_MAXIMA_M,
        }
        absent = sorted(expected - names)
        if absent:
            raise ValueError(f"the descent sidecar {path.name} lacks {', '.join(absent)}.")
        arrays = {
            "receiver": np.asarray(payload["receiver"], dtype=np.int64).reshape(-1),
            "surface": np.asarray(payload["surface"], dtype=np.float64).reshape(-1),
            "base_level": np.asarray(payload["base_level"], dtype=bool).reshape(-1),
            "constant_head": np.asarray(payload["constant_head"], dtype=bool).reshape(-1),
            "raised": np.asarray(payload["raised"], dtype=bool).reshape(-1),
            "channel": np.asarray(payload["channel"], dtype=bool).reshape(-1),
            "pinned": np.asarray(payload["pinned"], dtype=bool).reshape(-1),
        }
        adjacency = str(payload["adjacency"])
        # Absent from a sidecar written before the dam foot was kept: no foot.
        dam_foot = (
            np.asarray(payload["dam_foot"], dtype=np.int64).reshape(-1)
            if "dam_foot" in names
            else np.empty(0, dtype=np.int64)
        )
        scalars: dict[str, Any] = {"epsilon": float(payload["epsilon"])}
        scalars.update({name: int(payload[name]) for name in _REPORT_COUNTS})
        scalars.update({name: float(payload[name]) for name in _REPORT_MAXIMA_M})
        # Absent from a sidecar written before the basin was stored: no basin.
        basin_fields: dict[str, Any] = {}
        if "basin" in names:
            missing = sorted(set(_BASIN_KEYS) - names)
            if missing:
                raise ValueError(
                    f"the descent sidecar {path.name} holds a basin without {', '.join(missing)}."
                )
            arrays["basin"] = np.asarray(payload["basin"], dtype=bool).reshape(-1)
            basin_fields = {
                "basin_outlet": int(payload["basin_outlet"]),
                "basin_rule": str(payload["basin_rule"]),
                "basin_area_m2": float(payload["basin_area_m2"]),
                "basin_seeded_at_outlet": bool(payload["basin_seeded_at_outlet"]),
            }
        if _FRACTION_KEY in names:
            if "basin" not in names:
                raise ValueError(
                    f"the descent sidecar {path.name} holds a catchment fraction without a basin."
                )
            arrays[_FRACTION_KEY] = np.asarray(payload[_FRACTION_KEY], dtype=np.float64).reshape(-1)
    sizes = {name: int(values.size) for name, values in arrays.items()}
    if len(set(sizes.values())) != 1:
        raise ValueError(f"the descent sidecar {path.name} mixes cell counts: {sizes}.")
    if adjacency not in _ADJACENCY_KINDS:
        raise ValueError(
            f"the descent sidecar {path.name} names adjacency {adjacency!r}, "
            f"not one of {_ADJACENCY_KINDS}."
        )
    if dam_foot.size and (dam_foot.min() < 0 or dam_foot.max() >= next(iter(sizes.values()))):
        raise ValueError(f"the descent sidecar {path.name} holds a dam foot outside the mesh.")
    if "basin" in arrays:
        _check_stored_basin(path.name, arrays["basin"], basin_fields)
    if _FRACTION_KEY in arrays:
        fraction = arrays[_FRACTION_KEY]
        if not np.all((fraction >= 0.0) & (fraction <= 1.0)):
            raise ValueError(
                f"the descent sidecar {path.name} holds a catchment fraction outside [0, 1]."
            )
    return DescentRecord(
        **arrays, dam_foot=dam_foot, adjacency=adjacency, **scalars, **basin_fields
    )


def _check_stored_basin(name: str, mask: np.ndarray, fields: Mapping[str, Any]) -> None:
    """Raise unless the stored basin names a known rule and holds its own outlet."""
    if fields["basin_rule"] not in get_args(BasinRule):
        raise ValueError(
            f"the descent sidecar {name} names basin rule {fields['basin_rule']!r}, "
            f"not one of {get_args(BasinRule)}."
        )
    outlet = int(fields["basin_outlet"])
    if not 0 <= outlet < mask.size or not mask[outlet]:
        raise ValueError(f"the descent sidecar {name} holds a basin outlet outside its basin.")
