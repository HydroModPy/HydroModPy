"""MF6 recharge / EVT stress-period data builders."""

from __future__ import annotations

import hashlib
import os
import threading
import warnings
from collections.abc import Iterable, Mapping
from numbers import Real
from pathlib import Path

import numpy as np

from hydromodpy.core.time import validate_recharge_coverage
from hydromodpy.core.units import convert_payload_to_m_per_s
from hydromodpy.physics.forcing.validation import (
    ensure_finite_numeric_payload,
    ensure_non_negative_numeric_payload,
    has_temporal_index,
)
from hydromodpy.solver.modflow_common.recharge_evt_routing import route_negative_recharge_to_evt


def sanitize_numeric_payload(payload: object) -> object:
    """Validate one finite numeric payload and return it unchanged."""
    ensure_finite_numeric_payload(payload, label="recharge payload")
    return payload


def validate_recharge_numeric_payload(
    payload: object,
    *,
    label: str,
    allow_negative: bool = False,
) -> None:
    """Validate one recharge payload before it reaches MF6 stress packages."""
    if allow_negative:
        ensure_finite_numeric_payload(payload, label=label)
    else:
        ensure_non_negative_numeric_payload(payload, label=label)


def _copy_numeric_payload(payload: object) -> object:
    if isinstance(payload, Mapping):
        return {key: _copy_numeric_payload(value) for key, value in payload.items()}
    if isinstance(payload, Real) and not isinstance(payload, bool):
        return float(payload)
    return copy_runtime_payload(payload)


def payload_has_negative_values(payload: object) -> bool:
    """Return True when a recharge payload contains at least one negative value."""
    if isinstance(payload, Mapping):
        return any(payload_has_negative_values(value) for value in payload.values())
    if isinstance(payload, Real) and not isinstance(payload, bool):
        return float(payload) < 0.0
    arr = np.asarray(payload, dtype=float)
    return bool(np.any(arr < 0.0))


def clip_negative_payload(payload: object) -> object:
    """Clip negative recharge values to zero for MF6 RCH compatibility."""
    if isinstance(payload, Mapping):
        return {key: clip_negative_payload(value) for key, value in payload.items()}
    if isinstance(payload, Real) and not isinstance(payload, bool):
        return max(float(payload), 0.0)
    if hasattr(payload, "clip"):
        try:
            return payload.clip(lower=0.0)
        except TypeError:
            pass

    arr = np.asarray(payload, dtype=float)
    if arr.ndim == 0:
        return max(float(arr), 0.0)
    return np.maximum(arr, 0.0)


def copy_runtime_payload(payload: object) -> object:
    """Return a detached copy of one runtime payload when possible."""
    if isinstance(payload, Mapping):
        return {key: copy_runtime_payload(value) for key, value in payload.items()}
    if hasattr(payload, "copy"):
        try:
            return payload.copy()
        except Exception:
            pass
    return payload


def extract_evt_payload_2d(
    rch_data: Mapping[int, object],
    negative_to_evt: bool,
    *,
    steady: object,
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray] | None]:
    """Route negative recharge arrays to EVT and clip RCH to non-negative values.

    Steady periods carry the time-mean deficit; transient periods keep their own
    split (see ``route_negative_recharge_to_evt``). ``steady`` is the per-period
    steady flag (model.steady).
    """
    normalized_rch = {int(kper): np.asarray(value, dtype=float) for kper, value in rch_data.items()}
    if not negative_to_evt:
        return normalized_rch, None

    has_negative = any(np.any(arr < 0.0) for arr in normalized_rch.values())
    if not has_negative:
        return normalized_rch, None

    return route_negative_recharge_to_evt(normalized_rch, steady=steady)


def series_payload_value(payload: object, kper: int, *, first_clim: object) -> float:
    """Resolve one scalar climate value from a scalar/sequence payload."""
    if kper == 0:
        if first_clim == "mean":
            arr = np.asarray(payload, dtype=float)
            return float(np.mean(arr))
        if first_clim == "first":
            if hasattr(payload, "iloc"):
                first = payload.iloc[0]
                if isinstance(first, Real) and not isinstance(first, bool):
                    return float(first)
                first_arr = np.asarray(first, dtype=float).ravel()
                return float(first_arr[0]) if first_arr.size else 0.0
            arr = np.asarray(payload, dtype=float).ravel()
            return float(arr[0]) if arr.size else 0.0
        if isinstance(first_clim, Real) and not isinstance(first_clim, bool):
            return float(first_clim)

    if hasattr(payload, "iloc"):
        idx = min(max(int(kper), 0), len(payload) - 1)
        value = payload.iloc[idx]
        if isinstance(value, Real) and not isinstance(value, bool):
            return float(value)
        value_arr = np.asarray(value, dtype=float).ravel()
        if value_arr.size:
            return float(value_arr[0])
        return 0.0

    arr = np.asarray(payload, dtype=float).ravel()
    if arr.size == 0:
        return 0.0
    idx = min(max(int(kper), 0), int(arr.size) - 1)
    return float(arr[idx])


def extract_evt_payload(
    model,
    payload: object,
    negative_to_evt: bool,
) -> tuple[object, dict[int, object] | None]:
    """Route negative recharge values to EVT and keep RCH non-negative."""
    if not negative_to_evt or not payload_has_negative_values(payload):
        return payload, None

    if isinstance(payload, Mapping):
        return extract_evt_payload_2d(payload, True, steady=model.steady)

    payload_for_rch = copy_runtime_payload(payload)
    evt_payload = copy_runtime_payload(payload)

    if isinstance(payload_for_rch, list):
        payload_for_rch = np.asarray(payload_for_rch, dtype=float)
    if isinstance(evt_payload, list):
        evt_payload = np.asarray(evt_payload, dtype=float)

    if hasattr(evt_payload, "clip"):
        try:
            payload_for_rch = evt_payload.clip(lower=0.0)
        except TypeError:
            payload_for_rch = clip_negative_payload(payload_for_rch)
    else:
        payload_for_rch = clip_negative_payload(payload_for_rch)

    evt_negative = np.asarray(evt_payload, dtype=float)
    evt_negative[evt_negative >= 0.0] = 0.0
    evt_negative = np.abs(evt_negative)

    first_clim = model.first_clim if model.first_clim is not None else "mean"
    steady = model.steady

    def _evt_value(kper: int) -> object:
        if kper < len(steady) and bool(steady[kper]):
            # Steady spin-up carries the time-mean deficit.
            return series_payload_value(evt_negative, 0, first_clim="mean")
        # Transient period keeps its own deficit (period 0 uses its own value).
        policy = "first" if kper == 0 else first_clim
        return series_payload_value(evt_negative, kper, first_clim=policy)

    evt_spd: dict[int, object] = {kper: _evt_value(kper) for kper in range(int(model.nper))}
    return payload_for_rch, evt_spd


def bind_recharge_from_flow(model) -> None:
    """Resolve recharge inputs from the canonical flow recharge configuration."""
    model._evt_rate_payload = None
    model._pending_negative_to_evt = False
    if model.recharge is not None:
        validate_recharge_numeric_payload(
            model.recharge,
            label="model.recharge",
            allow_negative=False,
        )
        model.recharge = _copy_numeric_payload(model.recharge)
        if model.first_clim is None:
            model.first_clim = "mean"
        return

    active = getattr(model.flow, "active_sinks_sources", [])
    if "recharge" not in active:
        model.recharge = 0.0
        if model.first_clim is None:
            model.first_clim = "mean"
        return

    sinks_sources = getattr(model.flow, "sinks_sources", {})
    recharge_cfg = sinks_sources.get("recharge") if isinstance(sinks_sources, Mapping) else None
    if recharge_cfg is None:
        model.recharge = 0.0
        if model.first_clim is None:
            model.first_clim = "mean"
        return

    # Heterogeneous path: gridded FieldRecords or located PointRecords from data
    # managers. Both get discretized onto the solver grid by
    # `resolve_deferred_heterogeneous_recharge` once `solver_mesh` is available.
    het_source = getattr(recharge_cfg, "heterogeneous_source", None)
    if het_source is not None and (
        getattr(het_source, "has_fields", False) or getattr(het_source, "has_points", False)
    ):
        bind_heterogeneous_recharge(model, recharge_cfg)
        return

    payload = copy_runtime_payload(getattr(recharge_cfg, "values", 0.0))
    if has_temporal_index(payload):
        validate_recharge_coverage(
            payload,
            model.time_grid.window if getattr(model, "time_grid", None) is not None else None,
        )
    payload = convert_payload_to_m_per_s(
        payload,
        unit=str(getattr(recharge_cfg, "units", "mm/day")),
        label="flow.sinks_sources.recharge.values",
    )
    negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", False))
    validate_recharge_numeric_payload(
        payload,
        label="flow.sinks_sources.recharge.values",
        allow_negative=negative_to_evt,
    )
    if hasattr(model, "nper"):
        payload, evt_payload = extract_evt_payload(model, payload, negative_to_evt)
        model._evt_rate_payload = evt_payload
    else:
        model._pending_negative_to_evt = negative_to_evt

    model.recharge = payload
    model.first_clim = getattr(
        recharge_cfg,
        "first_clim",
        model.first_clim if model.first_clim is not None else "mean",
    )


def bind_heterogeneous_recharge(model, recharge_cfg: object) -> None:
    """Store heterogeneous source for deferred discretization."""
    model._heterogeneous_recharge_source = recharge_cfg.heterogeneous_source
    model._heterogeneous_negative_to_evt = bool(getattr(recharge_cfg, "negative_to_evt", False))
    model._heterogeneous_interpolation_method = getattr(
        recharge_cfg, "interpolation_method", "nearest"
    )
    # Heterogeneous data comes from data-managers (always mm/day).
    # recharge_cfg.units has been normalized to "m/s" by Flow init.
    model._heterogeneous_source_unit = "mm/day"
    model.recharge = 0.0  # placeholder; replaced after solver_mesh construction
    model.first_clim = getattr(
        recharge_cfg,
        "first_clim",
        model.first_clim if model.first_clim is not None else "mean",
    )


def resolve_deferred_heterogeneous_recharge(model) -> None:
    """Discretize stored heterogeneous recharge after solver_mesh is available."""
    het_source = getattr(model, "_heterogeneous_recharge_source", None)
    if het_source is None:
        return

    sim_window = model.time_grid.window if model.time_grid is not None else None
    interp_method = getattr(model, "_heterogeneous_interpolation_method", "nearest")
    source_unit = getattr(model, "_heterogeneous_source_unit", "mm/day")
    use_structured = bool(getattr(model.solver_mesh, "is_structured", False))
    if use_structured:
        from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import (
            discretize_fields_on_sgrid,
            discretize_points_on_sgrid,
        )
    else:
        from hydromodpy.spatial.mesh.cell_types import CellType
        from hydromodpy.spatial.mesh.gmsh_grid.planar_forcing_discretization import (
            discretize_fields_on_planar_mesh,
            discretize_points_on_planar_mesh,
        )

        solver_planar = model.solver_mesh.planar_mesh
        planar_mesh = getattr(model, "runtime_mesh_planar", None)
        # The runtime_mesh_planar is the triangular seed mesh; on a Voronoi solver grid
        # recharge must discretize onto the actual (POLYGON) solver cells, which the
        # HydroMesh exposes ragged-safe (cell_centroids + n_cells).
        if planar_mesh is None or CellType.POLYGON in getattr(solver_planar, "cell_types", ()):
            planar_mesh = solver_planar

    # Prefer fields; fall back to located points.
    if getattr(het_source, "has_fields", False):
        if use_structured:
            raw_arrays = discretize_fields_on_sgrid(
                load_result=het_source,
                sgrid=model.solver_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
            )
        else:
            raw_arrays = discretize_fields_on_planar_mesh(
                load_result=het_source,
                planar_mesh=planar_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
            )
    elif getattr(het_source, "has_points", False):
        if use_structured:
            raw_arrays = discretize_points_on_sgrid(
                load_result=het_source,
                sgrid=model.solver_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
                source_unit=source_unit,
            )
        else:
            raw_arrays = discretize_points_on_planar_mesh(
                load_result=het_source,
                planar_mesh=planar_mesh,
                nper=int(model.nper),
                simulation_window=sim_window,
                method=interp_method,
                source_unit=source_unit,
            )
    else:
        model._heterogeneous_recharge_source = None
        return

    raw_arrays, evt_payload = extract_evt_payload_2d(
        raw_arrays,
        getattr(model, "_heterogeneous_negative_to_evt", False),
        steady=model.steady,
    )
    validate_recharge_numeric_payload(
        raw_arrays,
        label="flow.sinks_sources.recharge.heterogeneous_source",
        allow_negative=False,
    )

    # `recharge_to_spd` handles Mapping {kper: ndarray(ncpl,)}.
    model.recharge = raw_arrays
    model._evt_rate_payload = evt_payload
    model._heterogeneous_recharge_source = None


def scalar_to_flat(model, value: float) -> np.ndarray:
    """Return flat (ncpl,) array filled with one scalar."""
    return np.full(int(model.ncpl), float(value), dtype=float)


def as_recharge_flat(model, value: object, *, kper: int | None = None) -> np.ndarray:
    """Coerce one recharge value to a flat (ncpl,) array."""
    if isinstance(value, Real) and not isinstance(value, bool):
        return scalar_to_flat(model, float(value))

    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return scalar_to_flat(model, float(arr))
    if arr.ndim == 1:
        if arr.size == int(model.ncpl):
            return arr.astype(float)
        raise ValueError(
            f"recharge array for period {kper} must be scalar or length ncpl "
            f"({int(model.ncpl)}); got {int(arr.size)}."
        )
    if arr.ndim == 2:
        flat = arr.ravel()
        if flat.size == int(model.ncpl):
            return flat.astype(float)
        raise ValueError(
            f"recharge array for period {kper} must flatten to ncpl "
            f"({int(model.ncpl)}); got {int(flat.size)}."
        )
    if arr.ndim >= 3:
        if kper is None or int(kper) < 0 or int(kper) >= int(arr.shape[0]):
            raise ValueError(
                "time-indexed recharge arrays require one leading entry per stress period."
            )
        idx = int(kper)
        flat = np.asarray(arr[idx], dtype=float).ravel()
        if flat.size == int(model.ncpl):
            return flat
        raise ValueError(
            f"recharge array for period {kper} must flatten to ncpl "
            f"({int(model.ncpl)}); got {int(flat.size)}."
        )

    raise ValueError(f"Unsupported recharge payload shape {arr.shape}.")


def series_like_to_scalar(model, kper: int) -> float:
    return series_payload_value(model.recharge, kper, first_clim=model.first_clim)


def _payload_sequence(model) -> np.ndarray:
    payload = model.recharge
    if hasattr(payload, "iloc"):
        values = [payload.iloc[idx] for idx in range(len(payload))]
        return np.asarray(values, dtype=float).reshape(-1)
    return np.asarray(payload, dtype=float)


def recharge_to_spd(model) -> dict[int, np.ndarray]:
    spd: dict[int, np.ndarray] = {}
    if isinstance(model.recharge, Mapping):
        for kper in range(model.nper):
            arr = model.recharge.get(kper)
            if arr is None:
                raise ValueError(f"model.recharge mapping is missing stress period {kper}.")
            spd[kper] = as_recharge_flat(model, arr, kper=kper)
        return spd

    if isinstance(model.recharge, Real) and not isinstance(model.recharge, bool):
        scalar = float(model.recharge)
        for kper in range(model.nper):
            spd[kper] = scalar_to_flat(model, scalar)
        return spd

    arr = _payload_sequence(model)
    if arr.ndim == 0:
        scalar = float(arr)
        for kper in range(model.nper):
            spd[kper] = scalar_to_flat(model, scalar)
        return spd
    if arr.ndim == 1:
        if arr.size == 1:
            scalar = float(arr[0])
            for kper in range(model.nper):
                spd[kper] = scalar_to_flat(model, scalar)
            return spd
        if arr.size == int(model.ncpl):
            flat = as_recharge_flat(model, arr)
            for kper in range(model.nper):
                spd[kper] = flat.copy()
            return spd
        if arr.size == int(model.nper):
            steady = model.steady
            first_clim = model.first_clim if model.first_clim is not None else "mean"
            for kper in range(model.nper):
                if kper < len(steady) and bool(steady[kper]):
                    # Steady spin-up uses the first_clim policy (mean by default).
                    value = series_payload_value(arr, 0, first_clim=first_clim)
                else:
                    value = float(arr[kper])
                spd[kper] = scalar_to_flat(model, float(value))
            return spd
        if int(model.nper) == 1:
            scalar = series_payload_value(model.recharge, 0, first_clim=model.first_clim)
            spd[0] = scalar_to_flat(model, float(scalar))
            return spd
        raise ValueError(
            "model.recharge sequence length must be 1, nper "
            f"({int(model.nper)}), or ncpl ({int(model.ncpl)}); got {int(arr.size)}."
        )
    if arr.ndim == 2 and arr.size == int(model.ncpl):
        flat = as_recharge_flat(model, arr)
        for kper in range(model.nper):
            spd[kper] = flat.copy()
        return spd
    if arr.ndim >= 2 and arr.shape[0] == int(model.nper):
        for kper in range(model.nper):
            spd[kper] = as_recharge_flat(model, arr[kper], kper=kper)
        return spd
    raise ValueError(
        "model.recharge array must be scalar, length nper, length ncpl, "
        "one grid array, or one leading entry per stress period."
    )


def mask_recharge_on_lake_cells(
    spd: dict[int, np.ndarray],
    *,
    lake_cell_ids: Iterable[int],
) -> dict[int, np.ndarray]:
    """Zero aquifer recharge on lake cells to avoid double counting with LAK.

    The lake's own rainfall enters through the LAK package, so applying RCHA on
    the same cells would count it twice. Without the FIXED_CELL option, RCHA does
    NOT drop recharge on an inactive (``idomain == 0``) lake cell: it REASSIGNS it
    to the first active cell below (right under the lake), which is exactly the
    double count this mask prevents. This mask is therefore REQUIRED, not
    belt-and-braces. The arrays are modified per stress period (flat ``ncpl``).
    """
    cells = np.asarray(list(lake_cell_ids), dtype=int)
    if cells.size == 0:
        return spd
    for kper, arr in spd.items():
        flat = np.asarray(arr, dtype=float)
        flat[cells] = 0.0
        spd[kper] = flat
    return spd


RECHARGE_BINARY_MIN_PERIODS = 64


def externalize_recharge_spd(
    spd: dict[int, np.ndarray],
    *,
    basename: str,
    shared_dir: str | os.PathLike[str] | None = None,
) -> dict[int, np.ndarray] | dict[int, dict]:
    """Route long transient recharge stacks to external binary array files.

    FloPy formats INTERNAL arrays value by value, which dominates
    ``write_simulation`` on multi-thousand-period chronicles. External binary
    files are written through numpy and read natively by MF6 via
    ``OPEN/CLOSE <file> (BINARY)``. Short records stay internal so small
    models keep human-readable input files.

    ``shared_dir`` enables the CALIBRATION fast path: the recharge is invariant
    across trials (K / Sy / bedleak do not change it), so the per-period ``.bin``
    are written ONCE to ``shared_dir`` (content-hashed) and every trial merely
    references them (``filename`` without ``data``), instead of re-writing
    thousands of files per trial under the GIL. The write is atomic
    (temp + rename), so concurrent first-generation trials never read a partial
    file.
    """
    if len(spd) < RECHARGE_BINARY_MIN_PERIODS:
        return spd
    if shared_dir is not None:
        return _shared_recharge_spd(spd, Path(shared_dir))
    return {
        kper: {
            "factor": 1.0,
            "data": arr,
            "filename": f"{basename}.rcha.{kper}.bin",
            "binary": True,
        }
        for kper, arr in spd.items()
    }


def _recharge_digest(spd: dict[int, np.ndarray]) -> str:
    """Content hash of the recharge stack, so a changed forcing gets new files."""
    hasher = hashlib.blake2b(digest_size=16)
    for kper in sorted(spd):
        arr = np.ascontiguousarray(np.asarray(spd[kper], dtype=np.float64))
        hasher.update(np.int64(kper).tobytes())
        hasher.update(np.int64(arr.size).tobytes())
        hasher.update(arr.tobytes())
    return hasher.hexdigest()


def _write_shared_recharge_bin(target: Path, arr: np.ndarray, kper: int) -> None:
    """Write one recharge period to ``target`` in the exact MF6 binary format.

    Idempotent and race-safe: skips a complete existing target, and otherwise
    writes a per-writer temp, fsyncs it, then atomically renames it, so a
    concurrent reader (or a re-run after a crash) only ever sees a complete file
    (all writers emit identical bytes). A pre-existing file of the wrong size
    (a zero-length remnant from a crash between write and rename) is rewritten.
    """
    ncpl = int(arr.size)
    expected_size = 52 + 8 * ncpl  # double-precision head header (52 B) + ncpl doubles
    if target.exists() and target.stat().st_size == expected_size:
        return
    from flopy.utils import Util2d
    from flopy.utils.binaryfile import BinaryHeader

    header = BinaryHeader.create(
        bintype="head",
        precision="double",
        text="RECHARGE",
        ncol=ncpl,
        nrow=1,
        ilay=1,
        pertim=1.0,
        totim=1.0,
        kstp=1,
        kper=int(kper) + 1,
    )
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    Util2d.write_bin(
        (1, ncpl), str(tmp), np.ascontiguousarray(arr).reshape(1, ncpl), header_data=header
    )
    fd = os.open(str(tmp), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(target))


def _shared_recharge_spd(spd: dict[int, np.ndarray], shared_dir: Path) -> dict[int, dict]:
    """Write the trial-invariant recharge once and return reference-only specs."""
    shared_dir.mkdir(parents=True, exist_ok=True)
    digest = _recharge_digest(spd)
    out: dict[int, dict] = {}
    for kper, arr in spd.items():
        target = shared_dir / f"rcha_{digest}.{kper}.bin"
        _write_shared_recharge_bin(target, np.asarray(arr, dtype=np.float64), kper)
        out[kper] = {"factor": 1.0, "filename": str(target), "binary": True}
    return out


def empty_recharge_aux(model) -> dict[int, list[np.ndarray]]:
    """Zero AUX concentration for period 0 only; MF6 repeats the last block.

    A single block keeps FloPy's per-period block-header bookkeeping (quadratic
    in the number of provided periods) out of long daily chronicles. Transport
    runs overwrite the data through ``rch.aux.set_data``.
    """
    return {0: [np.zeros(int(model.ncpl), dtype=float)]}


def finalize_pending_recharge_evt(model) -> None:
    """Apply deferred negative-recharge routing once `nper` is known."""
    if not getattr(model, "_pending_negative_to_evt", False):
        return
    model.recharge, model._evt_rate_payload = extract_evt_payload(model, model.recharge, True)
    model._pending_negative_to_evt = False


def build_evt_stress_period_data(
    model,
    solver_mesh,
    *,
    ocean_support_mask: np.ndarray,
    stream_support_mask: np.ndarray,
    lake_cell_ids: Iterable[int] = (),
) -> dict[int, list[list[float]]] | None:
    """Build MF6 EVT stress-period data from recharge negatives routed to EVT.

    ``lake_cell_ids`` are the flat cell2d ids under the lake footprint: aquifer ET
    is skipped there because LAK supplies the open-water evaporation, so it must
    not be double-counted. They are passed explicitly (not read off the model) so
    the masking does not depend on build ordering.
    """
    evt_payload = getattr(model, "_evt_rate_payload", None)
    if evt_payload is None:
        return None

    top_flat = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    ocean_mask_flat = np.asarray(ocean_support_mask, dtype=bool).reshape(-1)
    stream_mask_flat = np.asarray(stream_support_mask, dtype=bool).reshape(-1)
    # evt_extinction_depth in meters; floor only guards a degenerate zero depth.
    evt_depth = max(float(model.modflow_config.process_specific.evt_extinction_depth), 1e-6)
    # Place the EVT sink on the uppermost active layer of each cell, not layer 0.
    # idomain and the skip mask are loop-invariant, so precompute them once.
    ncpl = int(model.ncpl)
    active_by_layer = solver_mesh.idomain() == 1
    has_active = active_by_layer.any(axis=0)
    top_layer_by_cell = np.argmax(active_by_layer, axis=0)  # first active layer per cell
    skip = ocean_mask_flat | stream_mask_flat
    for cid in lake_cell_ids:
        if 0 <= int(cid) < ncpl:
            skip[int(cid)] = True
    keep = ~skip & has_active

    evt_spd: dict[int, list[list[float]]] = {}
    for kper in range(int(model.nper)):
        raw_value = evt_payload.get(kper, 0.0) if isinstance(evt_payload, Mapping) else evt_payload
        rate_flat = as_recharge_flat(model, raw_value, kper=kper)
        period_cells: list[list[float]] = []
        for cid in range(ncpl):
            if not keep[cid]:
                continue
            rate_value = float(rate_flat[cid])
            if rate_value <= 0.0:
                continue
            period_cells.append(
                [int(top_layer_by_cell[cid]), cid, float(top_flat[cid]), rate_value, evt_depth]
            )
        evt_spd[kper] = period_cells

    if any(len(v) > 0 for v in evt_spd.values()):
        warnings.warn(
            "Routed climatic deficit uses a fixed EVT extinction depth of "
            f"{evt_depth} m; a sustained deficit can saturate the water table near "
            "this depth rather than over the full saturated thickness.",
            RuntimeWarning,
            stacklevel=2,
        )
        return evt_spd
    return None


def evt_list_spd_to_array_payload(
    evt_spd: Mapping[int, list[list[float]]],
    *,
    top_flat: np.ndarray,
    ncpl: int,
) -> tuple[dict[int, np.ndarray], np.ndarray, float] | None:
    """Convert list EVT stress-period data to EVTA (array) input, if it is safe.

    The array package writes a compact READARRAY of rates per changed period
    instead of ``O(ncells)`` list records, which dominates ``write_simulation`` on
    long chronicles. It is byte-for-byte equivalent to the list builder ONLY when
    every EVT record targets layer 0: EVTA applies ET to the highest active cell of
    each column, which matches the list builder's ``top_layer_by_cell`` exactly
    while that layer is 0, but diverges when the top layer is inactive (the list
    moves ET down a layer, the array does not). The builder already skips lake
    cells (the usual inactive-top source), so this normally holds; ``None`` here
    tells the caller to keep the list package for the rare case that it does not.

    Returns ``(rate_by_period, surface, depth)``. ``surface`` is the model top for
    every cell (rate is 0 where no EVT, so the surface value is inert there);
    ``depth`` is the builder's single extinction depth. Period keys mirror the
    (already collapsed) input, so MF6 reuses the previous array for gaps.
    """
    top_flat = np.asarray(top_flat, dtype=float).reshape(-1)
    depth: float | None = None
    rate_by_period: dict[int, np.ndarray] = {}
    for kper, records in evt_spd.items():
        rate = np.zeros(ncpl, dtype=float)
        for record in records:
            if int(record[0]) != 0:
                return None
            rate[int(record[1])] = float(record[3])
            if depth is None:
                depth = float(record[4])
        rate_by_period[int(kper)] = rate
    if depth is None:
        return None
    return rate_by_period, top_flat[:ncpl].copy(), float(depth)


__all__ = [
    "as_recharge_flat",
    "bind_heterogeneous_recharge",
    "bind_recharge_from_flow",
    "build_evt_stress_period_data",
    "evt_list_spd_to_array_payload",
    "clip_negative_payload",
    "copy_runtime_payload",
    "empty_recharge_aux",
    "extract_evt_payload",
    "extract_evt_payload_2d",
    "finalize_pending_recharge_evt",
    "mask_recharge_on_lake_cells",
    "payload_has_negative_values",
    "recharge_to_spd",
    "resolve_deferred_heterogeneous_recharge",
    "sanitize_numeric_payload",
    "scalar_to_flat",
    "series_like_to_scalar",
    "series_payload_value",
]
