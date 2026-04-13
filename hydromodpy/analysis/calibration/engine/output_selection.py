"""Canonical output selection for model-calibration launchers.

The calibration launcher needs a stable boundary between heterogeneous
simulation run states and objective-ready observables. This module owns that
boundary locally to `launchers.model_calibration`:

`run_state -> CanonicalOutputBundle -> selected observable arrays`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import numpy as np

from hydromodpy.analysis.calibration.engine.config import ModelCalibrationConfig

logger = logging.getLogger(__name__)


_RUNTIME_MODEL_VARIABLE_NAMES = (
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "outlet_discharge_east_side_m3_s",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
    "concentration_seepage",
    "mass_seepage",
    "mass_accumulated",
)
_VARIABLE_ALIASES = {
    "outlet_discharge": ("outlet_discharge_east_side_m3_s",),
    "head": ("watertable_elevation",),
    "depth": ("watertable_depth",),
}
_BOUNDARY_VARIABLE_IDS = {
    "outlet_discharge_east_side_m3_s": "east_side",
}


@dataclass(frozen=True, slots=True)
class CanonicalOutputVariable:
    """One canonical simulation output variable."""

    name: str
    payload: Any
    source_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanonicalOutputBundle:
    """Canonical view of outputs exposed by one candidate simulation run."""

    variables: dict[str, CanonicalOutputVariable]
    aliases: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        """Return a variable payload by canonical name or alias."""
        if key in self.variables:
            return self.variables[key].payload
        alias = self.aliases.get(key)
        if alias is not None and alias in self.variables:
            return self.variables[alias].payload
        raise KeyError(f"Unknown canonical output '{key}'")


@dataclass(frozen=True, slots=True)
class PreparedOutputSelector:
    """Prepared observable selector compiled once from launcher config."""

    name: str
    variable: str
    variable_keys: tuple[str, ...]
    source: str
    support: str
    x: float | None = None
    y: float | None = None
    boundary_id: str | None = None
    time: str | None = None
    time_window: tuple[str, str] | None = None
    time_reducer: str | None = None
    reducer: str | None = None


def _try_import_flopy_runtime_readers():
    """Import optional FloPy readers used for direct solver-output selection."""
    try:
        import flopy.utils.binaryfile as bf
        from flopy.utils import postprocessing as pp
    except Exception:
        return None, None
    return bf, pp


def _candidate_output_containers(run_state: Any) -> tuple[tuple[str, Any], ...]:
    """Return possible output containers in lookup priority order."""
    containers: list[tuple[str, Any]] = []
    if isinstance(run_state, dict):
        for key in ("calibration_outputs", "outputs"):
            value = run_state.get(key)
            if value is not None:
                containers.append((key, value))
        containers.append(("run_state", run_state))
        return tuple(containers)

    for attr in ("calibration_outputs", "outputs"):
        value = getattr(run_state, attr, None)
        if value is not None:
            containers.append((attr, value))
    execution = getattr(run_state, "execution", None)
    if execution is not None:
        for attr in ("calibration_outputs", "outputs"):
            value = getattr(execution, attr, None)
            if value is not None:
                containers.append((f"execution.{attr}", value))
    return tuple(containers)


def _lookup_value_in_container(container: Any, key: str) -> tuple[bool, Any]:
    """Lookup one value by key in a dict-like or attribute container."""
    if isinstance(container, dict) and key in container:
        return True, container[key]
    if hasattr(container, key):
        return True, getattr(container, key)
    return False, None


def _iter_container_items(container: Any) -> list[tuple[str, Any]]:
    """Return string-keyed items exposed by one output container."""
    if isinstance(container, dict):
        return [(str(key), value) for key, value in container.items()]
    if hasattr(container, "__dict__"):
        return [
            (str(key), value)
            for key, value in vars(container).items()
            if not str(key).startswith("_")
        ]
    return []


def _sort_time_key(key: Any) -> tuple[int, float | str]:
    """Return a stable sort key for mixed numeric/string time indices."""
    if isinstance(key, (int, float, np.integer, np.floating)):
        return (0, float(key))
    text = str(key)
    try:
        return (0, float(text))
    except ValueError:
        return (1, text)


def _execution_scope(run_state: Any) -> Any:
    """Return the execution registry/scope exposed by one run-state payload."""
    if isinstance(run_state, dict):
        execution = run_state.get("execution")
        if execution is not None:
            return execution
    return getattr(run_state, "execution", None)


def _models_by_run_id(run_state: Any) -> Mapping[str, Any]:
    """Return the produced solver models keyed by run id when available."""
    execution = _execution_scope(run_state)
    if execution is None:
        return {}
    if isinstance(execution, dict):
        models = execution.get("models_by_run_id")
        return models if isinstance(models, Mapping) else {}
    models = getattr(execution, "models_by_run_id", None)
    return models if isinstance(models, Mapping) else {}


def _boundary_id_for_variable(variable_name: str) -> str | None:
    """Return the canonical boundary id exposed by one boundary series."""
    return _BOUNDARY_VARIABLE_IDS.get(str(variable_name).strip())


def _model_postprocess_dir(model: Any) -> Path | None:
    """Resolve the persisted `_postprocess` directory for one solver model."""
    save_file = getattr(model, "save_file", None)
    if save_file:
        save_path = Path(str(save_file)).expanduser()
        if save_path.name == "_postprocess":
            return save_path
    full_path = getattr(model, "full_path", None)
    if full_path:
        return Path(str(full_path)).expanduser() / "_postprocess"
    return None


def _load_npy_payload(path: Path) -> Any:
    """Load one post-process `.npy` payload."""
    payload = np.load(path, allow_pickle=True)
    if getattr(payload, "shape", None) == () and hasattr(payload, "item"):
        item = payload.item()
        if isinstance(item, Mapping):
            return dict(item)
        return item
    return np.asarray(payload, dtype=float)


def _load_mesh_npz_payload(path: Path) -> tuple[dict[Any, Any], np.ndarray | None]:
    """Load one native-mesh `.npz` export as a time-indexed mapping."""
    payload = np.load(path, allow_pickle=True)
    values = np.asarray(payload["values"], dtype=float)
    if "time_index" in payload:
        time_keys = list(payload["time_index"])
    elif "times" in payload:
        time_keys = list(payload["times"])
    else:
        time_keys = list(range(values.shape[0] if values.ndim > 1 else 1))
    cell_ids = (
        np.asarray(payload["cell_ids"], dtype=int).reshape(-1)
        if "cell_ids" in payload
        else None
    )
    if values.ndim <= 1:
        return {time_keys[0]: values.reshape(-1)}, cell_ids
    return {
        time_keys[index]: np.asarray(values[index], dtype=float).reshape(-1)
        for index in range(values.shape[0])
    }, cell_ids


def _try_store_variable(
    result_store: Any,
    sim_id: str,
    variable_name: str,
) -> tuple[Any | None, str | None]:
    """Try to load a variable from a ResultStore (DuckDB + Zarr).

    Returns ``(payload, source_tag)`` on success, ``(None, None)`` when the
    variable is not available in the store. This is the preferred read path;
    callers should fall back to legacy ``.npy`` / runtime-attribute reads
    when this returns ``None``.
    """
    try:
        root = result_store._zarr_root  # noqa: SLF001
        grp = root.get(str(sim_id))
        if grp is None:
            return None, None

        # Check root group, then common subgroups (derived, budget).
        for loc in (grp, grp.get("derived"), grp.get("budget")):
            if loc is not None and variable_name in loc:
                arr = loc[variable_name]
                shape = arr.shape
                if len(shape) == 0:
                    return None, None
                if len(shape) == 1:
                    # Single timestep — return flat array.
                    return np.asarray(arr[:], dtype=float), "result_store"
                # Multiple timesteps — return dict keyed by timestep index.
                payload = {
                    t: np.asarray(arr[t], dtype=float).reshape(-1)
                    for t in range(shape[0])
                }
                return payload, "result_store"
    except Exception:
        logger.debug(
            "ResultStore lookup failed for variable '%s' (sim=%s), "
            "falling back to legacy path",
            variable_name,
            sim_id,
            exc_info=True,
        )
    return None, None


def _cached_xy_coordinates(
    owner: Any,
    *,
    cache_attr: str,
    build: callable,
) -> np.ndarray | None:
    """Return one cached `(n, 2)` coordinate array when the owner supports it."""
    cached = getattr(owner, cache_attr, None)
    if isinstance(cached, np.ndarray) and cached.ndim == 2 and cached.shape[1] >= 2:
        return np.asarray(cached[:, :2], dtype=float)
    coords = build()
    if coords is None:
        return None
    try:
        setattr(owner, cache_attr, coords)
    except Exception:
        try:
            object.__setattr__(owner, cache_attr, coords)
        except Exception:
            pass
    return coords


def _export_array_like_model(model: Any, values: Any) -> np.ndarray:
    """Match the solver export convention when the model exposes one helper."""
    exporter = getattr(model, "_to_export_array", None)
    if callable(exporter):
        try:
            return np.asarray(exporter(values), dtype=float)
        except Exception:
            pass
    return np.asarray(values, dtype=float)


def _modflow6_solver_output_paths(model: Any) -> tuple[Path, Path] | None:
    """Return raw MODFLOW 6 solver output paths when the model exposes them."""
    full_path = getattr(model, "full_path", None)
    model_name = getattr(model, "model_name", None)
    if not full_path or not model_name:
        return None
    model_root = Path(str(full_path)).expanduser()
    return (
        model_root / f"{model_name}.hds",
        model_root / f"{model_name}.cbc",
    )


def _modflow6_raw_payload_cache(model: Any) -> dict[str, Any]:
    """Return one per-model cache used by raw solver-output fallbacks."""
    cache = getattr(model, "_calibration_raw_output_payload_cache", None)
    if isinstance(cache, dict):
        return cache
    cache = {}
    try:
        setattr(model, "_calibration_raw_output_payload_cache", cache)
    except Exception:
        return {}
    return cache


def _modflow6_raw_output_payloads(
    model: Any,
    *,
    variable_names: tuple[str, ...],
) -> dict[str, Any]:
    """Read selected MODFLOW 6 outputs directly from raw solver files."""
    supported = {
        "watertable_elevation",
        "watertable_depth",
        "seepage_areas",
        "outflow_drain",
        "outlet_discharge_east_side_m3_s",
    }
    requested = tuple(
        name for name in variable_names if str(name).strip() in supported
    )
    if not requested:
        return {}

    cache = _modflow6_raw_payload_cache(model)
    missing = tuple(name for name in requested if name not in cache)
    if not missing:
        return {name: cache[name] for name in requested if name in cache}

    bf, pp = _try_import_flopy_runtime_readers()
    paths = _modflow6_solver_output_paths(model)
    if bf is None or pp is None or paths is None:
        return {name: cache[name] for name in requested if name in cache}
    head_path, cbc_path = paths
    if not head_path.is_file():
        return {name: cache[name] for name in requested if name in cache}

    ncpl = int(getattr(model, "ncpl", 0) or 0)
    if ncpl <= 0:
        return {name: cache[name] for name in requested if name in cache}

    dem_mask_flat = np.asarray(getattr(model, "dem_mask", ()), dtype=bool).reshape(-1)
    if dem_mask_flat.size != ncpl:
        dem_mask_flat = np.zeros(ncpl, dtype=bool)
    dem_flat = np.asarray(getattr(model, "dem", ()), dtype=float).reshape(-1)
    if dem_flat.size != ncpl:
        dem_flat = np.zeros(ncpl, dtype=float)

    payloads: dict[str, dict[int, Any]] = {name: {} for name in missing}
    east_side_cell_ids: set[int] = set()
    if "outlet_discharge_east_side_m3_s" in missing:
        east_side_builder = getattr(model, "_east_side_cell_ids", None)
        if callable(east_side_builder):
            try:
                east_side_cell_ids = {int(value) for value in east_side_builder()}
            except Exception:
                east_side_cell_ids = set()

    head_fpu = None
    cbb = None
    try:
        head_fpu = bf.HeadFile(str(head_path))
        if cbc_path.is_file():
            open_budget = getattr(model, "_open_budget_file", None)
            if callable(open_budget):
                cbb = open_budget(str(cbc_path))
            else:
                cbb = bf.CellBudgetFile(str(cbc_path))

        for item, time in enumerate(head_fpu.get_times()):
            wt = None
            if (
                "watertable_elevation" in missing
                or "watertable_depth" in missing
            ):
                head = head_fpu.get_data(totim=time)
                wt = np.asarray(pp.get_water_table(head, -9999), dtype=float).reshape(-1)
                wt[np.isnan(wt)] = -9999.0
                wt[wt <= -1.0e20] = -9999.0

            if "watertable_elevation" in missing and wt is not None:
                wt_out = wt.copy()
                wt_out[dem_mask_flat] = -9999.0
                payloads["watertable_elevation"][item] = _export_array_like_model(
                    model,
                    wt_out,
                )

            if "watertable_depth" in missing and wt is not None:
                wtd = np.where(dem_mask_flat, -9999.0, np.maximum(dem_flat - wt, 0.0))
                payloads["watertable_depth"][item] = _export_array_like_model(
                    model,
                    wtd,
                )

            if (
                cbb is not None
                and (
                    "outflow_drain" in missing
                    or "seepage_areas" in missing
                )
            ):
                drn_getter = getattr(model, "_get_budget_records_or_none", None)
                if callable(drn_getter):
                    drn = drn_getter(cbb, kstpkper=(0, item), text="DRN")
                else:
                    drn = cbb.get_data(kstpkper=(0, item), text="DRN")
                outflow = np.zeros(ncpl, dtype=float)
                seepage = np.zeros(ncpl, dtype=float)
                if drn is not None and len(drn) > 0:
                    rec = drn[0]
                    try:
                        if getattr(rec, "dtype", None) is not None and rec.dtype.names is not None:
                            node_field = "node" if "node" in rec.dtype.names else rec.dtype.names[0]
                            q_field = "q" if "q" in rec.dtype.names else rec.dtype.names[-1]
                            iterator = ((int(r[node_field]), float(r[q_field])) for r in rec)
                        else:
                            iterator = ((int(r[0]), float(r[-1])) for r in rec)
                        for node, q in iterator:
                            if node <= 0:
                                continue
                            layer = (node - 1) // ncpl
                            cell_id = (node - 1) % ncpl
                            if layer == 0:
                                outflow[cell_id] += max(-q, 0.0)
                                seepage[cell_id] = 1.0 if q < 0 else seepage[cell_id]
                    except Exception:
                        pass
                outflow[dem_mask_flat] = -9999.0
                seepage[dem_mask_flat] = -9999.0
                if "outflow_drain" in missing:
                    payloads["outflow_drain"][item] = _export_array_like_model(
                        model,
                        outflow,
                    )
                if "seepage_areas" in missing:
                    payloads["seepage_areas"][item] = _export_array_like_model(
                        model,
                        seepage,
                    )

            if (
                cbb is not None
                and "outlet_discharge_east_side_m3_s" in missing
            ):
                chd_getter = getattr(model, "_get_budget_records_or_none", None)
                discharge_builder = getattr(
                    model,
                    "_compute_chd_outlet_discharge_east_side_m3_s",
                    None,
                )
                if callable(chd_getter) and callable(discharge_builder):
                    chd = chd_getter(cbb, kstpkper=(0, item), text="CHD")
                    discharge = discharge_builder(
                        chd,
                        ncpl=ncpl,
                        east_side_cell_ids=east_side_cell_ids,
                    )
                    payloads["outlet_discharge_east_side_m3_s"][item] = np.asarray(
                        [float(discharge)],
                        dtype=float,
                    )
    except Exception:
        return {name: cache[name] for name in requested if name in cache}
    finally:
        for handle in (head_fpu, cbb):
            closer = getattr(handle, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass

    for name, payload in payloads.items():
        if payload:
            cache[name] = payload
    return {name: cache[name] for name in requested if name in cache}


def _raw_model_variable_payload(
    model: Any,
    *,
    variable_name: str,
    result_store: Any = None,
    store_sim_id: str | None = None,
) -> tuple[Any | None, str | None, np.ndarray | None]:
    """Resolve one variable payload from ResultStore, model memory, or disk.

    Resolution order (first hit wins):
    1. ResultStore (DuckDB + Zarr) — preferred on dev-database branch
    2. Runtime attribute (``model.dict_<variable_name>``)
    3. Legacy ``_postprocess/*.npy`` or ``_postprocess/_mesh/*.npz``
    """
    # --- 1. ResultStore path (progressive migration) -------------------------
    if result_store is not None and store_sim_id is not None:
        payload, source = _try_store_variable(
            result_store, store_sim_id, variable_name,
        )
        if payload is not None:
            return payload, source, None

    # --- 2. Runtime attribute ------------------------------------------------
    attr_name = f"dict_{variable_name}"
    attr_value = getattr(model, attr_name, None)
    if attr_value is not None and (
        not isinstance(attr_value, Mapping) or len(attr_value) > 0
    ):
        return attr_value, "runtime_attribute", None

    # --- 3. Legacy disk fallback ---------------------------------------------
    postprocess_dir = _model_postprocess_dir(model)
    if postprocess_dir is None:
        return None, None, None

    npy_path = postprocess_dir / f"{variable_name}.npy"
    if npy_path.is_file():
        return _load_npy_payload(npy_path), "postprocess_npy", None

    mesh_npz_path = postprocess_dir / "_mesh" / f"flow_{variable_name}.npz"
    if mesh_npz_path.is_file():
        payload, cell_ids = _load_mesh_npz_payload(mesh_npz_path)
        return payload, "postprocess_mesh_npz", cell_ids

    raw_payloads = _modflow6_raw_output_payloads(
        model,
        variable_names=(str(variable_name),),
    )
    if variable_name in raw_payloads:
        return raw_payloads[variable_name], "solver_output_files", None

    return None, None, None


def _coordinates_from_runtime_mesh_support(
    support: Any,
    *,
    cell_ids: np.ndarray | None = None,
) -> np.ndarray | None:
    """Return cell-centroid coordinates from runtime mesh support metadata."""
    if support is None:
        return None

    def _build_support_coordinates() -> np.ndarray | None:
        xs = np.asarray(getattr(support, "cell_centroid_x_m", ()), dtype=float).reshape(-1)
        ys = np.asarray(getattr(support, "cell_centroid_y_m", ()), dtype=float).reshape(-1)
        if xs.size == 0 or ys.size != xs.size:
            return None
        return np.column_stack([xs, ys]).astype(float, copy=False)

    coords = _cached_xy_coordinates(
        support,
        cache_attr="_calibration_cached_coordinates_xy",
        build=_build_support_coordinates,
    )
    if coords is None:
        return None
    if cell_ids is not None and cell_ids.size > 0:
        if np.any(cell_ids < 0) or np.any(cell_ids >= coords.shape[0]):
            return None
        coords = coords[cell_ids]
    return np.asarray(coords, dtype=float)


def _coordinates_from_solver_mesh(
    solver_mesh: Any,
    *,
    cell_ids: np.ndarray | None = None,
) -> np.ndarray | None:
    """Return cell-centroid coordinates from one solver mesh when exposed."""
    if solver_mesh is None or not hasattr(solver_mesh, "cell_centroids"):
        return None
    coords = _cached_xy_coordinates(
        solver_mesh,
        cache_attr="_calibration_cached_coordinates_xy",
        build=lambda: _build_solver_mesh_coordinates(solver_mesh),
    )
    if coords is None:
        return None
    if cell_ids is not None and cell_ids.size > 0:
        if np.any(cell_ids < 0) or np.any(cell_ids >= coords.shape[0]):
            return None
        coords = coords[cell_ids]
    return np.asarray(coords, dtype=float)


def _build_solver_mesh_coordinates(solver_mesh: Any) -> np.ndarray | None:
    """Materialize full solver-mesh `(x, y)` cell coordinates once."""
    try:
        centroids = np.asarray(solver_mesh.cell_centroids(), dtype=float)
    except Exception:
        return None
    if centroids.size == 0:
        return None
    if centroids.ndim == 2 and centroids.shape[1] >= 2:
        return np.asarray(centroids[:, :2], dtype=float)
    try:
        return np.asarray(centroids.reshape(-1, 2), dtype=float)
    except ValueError:
        return None


def _coordinates_from_structured_grid(
    model: Any,
    *,
    cell_ids: np.ndarray | None = None,
) -> np.ndarray | None:
    """Return structured-grid cell centers from legacy solver attributes."""
    nrow = getattr(model, "nrow", None)
    ncol = getattr(model, "ncol", None)
    resolution = getattr(model, "resolution", None)
    xul = getattr(model, "xul", None)
    yul = getattr(model, "yul", None)
    if any(value is None for value in (nrow, ncol, resolution, xul, yul)):
        return None
    nrow = int(nrow)
    ncol = int(ncol)
    resolution = float(resolution)
    xs = float(xul) + (np.arange(ncol, dtype=float) + 0.5) * resolution
    ys = float(yul) - (np.arange(nrow, dtype=float) + 0.5) * resolution
    grid_x, grid_y = np.meshgrid(xs, ys)
    coords = np.column_stack([grid_x.reshape(-1), grid_y.reshape(-1)])
    if cell_ids is not None and cell_ids.size > 0:
        if np.any(cell_ids < 0) or np.any(cell_ids >= coords.shape[0]):
            return None
        coords = coords[cell_ids]
    return np.asarray(coords, dtype=float)


def _model_cell_coordinates(
    model: Any,
    *,
    value_count: int,
    cell_ids: np.ndarray | None = None,
) -> np.ndarray | None:
    """Resolve per-cell coordinates aligned with one flattened model array."""
    if value_count <= 0:
        return None
    support = getattr(model, "runtime_mesh_support", None)
    coords = _coordinates_from_runtime_mesh_support(support, cell_ids=cell_ids)
    if coords is not None and coords.shape[0] == value_count:
        return coords

    solver_mesh = getattr(model, "solver_mesh", None)
    coords = _coordinates_from_solver_mesh(solver_mesh, cell_ids=cell_ids)
    if coords is not None and coords.shape[0] == value_count:
        return coords

    coords = _coordinates_from_structured_grid(model, cell_ids=cell_ids)
    if coords is not None and coords.shape[0] == value_count:
        return coords
    return None


def _canonicalize_model_slice(
    *,
    variable_name: str,
    values: Any,
    model: Any,
    cell_ids: np.ndarray | None = None,
) -> Any:
    """Normalize one solver output slice to the canonical selection payload."""
    boundary_id = _boundary_id_for_variable(variable_name)
    flat_values = np.asarray(values, dtype=float).reshape(-1)
    if boundary_id is not None:
        return {boundary_id: tuple(float(value) for value in flat_values)}

    coordinates = _model_cell_coordinates(
        model,
        value_count=int(flat_values.size),
        cell_ids=cell_ids,
    )
    if coordinates is not None:
        return {
            "coordinates": np.asarray(coordinates, dtype=float),
            "values": flat_values.astype(float, copy=False),
        }
    return flat_values.astype(float, copy=False)


def _canonicalize_model_payload(
    *,
    variable_name: str,
    payload: Any,
    model: Any,
    cell_ids: np.ndarray | None = None,
) -> Any:
    """Convert one raw solver payload to the canonical calibration structure."""
    if isinstance(payload, Mapping):
        return {
            time_key: _canonicalize_model_slice(
                variable_name=variable_name,
                values=time_values,
                model=model,
                cell_ids=cell_ids,
            )
            for time_key, time_values in sorted(
                payload.items(),
                key=lambda item: _sort_time_key(item[0]),
            )
        }
    return _canonicalize_model_slice(
        variable_name=variable_name,
        values=payload,
        model=model,
        cell_ids=cell_ids,
    )


def _iter_runtime_model_variables(
    run_state: Any,
    *,
    variable_names: tuple[str, ...] | None = None,
    result_store: Any = None,
    store_sim_id: str | None = None,
) -> tuple[CanonicalOutputVariable, ...]:
    """Extract canonical variables from produced solver models when available."""
    variables: list[CanonicalOutputVariable] = []
    names = (
        tuple(dict.fromkeys(str(name) for name in variable_names if str(name).strip()))
        if variable_names is not None
        else _RUNTIME_MODEL_VARIABLE_NAMES
    )
    for run_id, model in _models_by_run_id(run_state).items():
        for variable_name in names:
            raw_payload, payload_source, cell_ids = _raw_model_variable_payload(
                model,
                variable_name=variable_name,
                result_store=result_store,
                store_sim_id=store_sim_id,
            )
            if raw_payload is None:
                continue
            variables.append(
                CanonicalOutputVariable(
                    name=variable_name,
                    payload=_canonicalize_model_payload(
                        variable_name=variable_name,
                        payload=raw_payload,
                        model=model,
                        cell_ids=cell_ids,
                    ),
                    source_key=(
                        f"execution.models_by_run_id[{run_id}].{payload_source}"
                    ),
                    metadata={
                        "run_id": str(run_id),
                        "source_kind": str(payload_source),
                    },
                )
            )
    return tuple(variables)


def canonicalize_run_outputs(
    run_state: Any,
    *,
    requested_variable_names: tuple[str, ...] | None = None,
    result_store: Any = None,
    store_sim_id: str | None = None,
) -> CanonicalOutputBundle:
    """Build a canonical output bundle from a heterogeneous run state.

    Parameters
    ----------
    result_store : ResultStore, optional
        When provided, spatial fields are read from the store first before
        falling back to legacy ``.npy`` files. Progressive migration path.
    store_sim_id : str, optional
        Simulation UUID inside the store. Required when *result_store* is set.
    """
    variables: dict[str, CanonicalOutputVariable] = {}
    aliases: dict[str, str] = {}
    for source_name, container in _candidate_output_containers(run_state):
        for key, value in _iter_container_items(container):
            if key not in variables:
                variables[key] = CanonicalOutputVariable(
                    name=key,
                    payload=value,
                    source_key=source_name,
                )
            aliases.setdefault(key, key)

    for variable in _iter_runtime_model_variables(
        run_state,
        variable_names=requested_variable_names,
        result_store=result_store,
        store_sim_id=store_sim_id,
    ):
        if variable.name not in variables:
            variables[variable.name] = variable
        aliases.setdefault(variable.name, variable.name)

    for alias_name, candidate_names in _VARIABLE_ALIASES.items():
        if alias_name in variables:
            aliases.setdefault(alias_name, alias_name)
            continue
        for candidate_name in candidate_names:
            if candidate_name in variables:
                aliases.setdefault(alias_name, candidate_name)
                break

    return CanonicalOutputBundle(variables=variables, aliases=aliases)


def _requested_runtime_variable_names(
    selectors: tuple[PreparedOutputSelector, ...],
) -> tuple[str, ...]:
    """Return the minimal runtime-variable set needed by prepared selectors."""
    names: list[str] = []
    runtime_names = set(_RUNTIME_MODEL_VARIABLE_NAMES)
    for selector in selectors:
        for key in selector.variable_keys:
            text = str(key).strip()
            if text in runtime_names and text not in names:
                names.append(text)
            for alias_name in _VARIABLE_ALIASES.get(text, ()):
                if alias_name in runtime_names and alias_name not in names:
                    names.append(alias_name)
    return tuple(names)


def _lookup_bundle_or_run_state(
    *,
    bundle: CanonicalOutputBundle,
    run_state: Any,
    key: str,
) -> Any:
    """Lookup one key first in the canonical bundle, then by direct container."""
    try:
        return bundle.get(key)
    except KeyError:
        pass
    for _, container in _candidate_output_containers(run_state):
        found, value = _lookup_value_in_container(container, key)
        if found:
            return value
    raise KeyError(f"Could not find calibration output key '{key}'")


def _output_variable_keys(output_cfg: Any) -> tuple[str, ...]:
    """Return variable lookup keys from most semantic to compatibility aliases."""
    keys: list[str] = []
    variable = str(output_cfg.variable).strip()
    if variable:
        keys.append(variable)
    boundary_id = getattr(output_cfg, "boundary_id", None)
    if variable == "outlet_discharge" and boundary_id is not None:
        keys.append(f"outlet_discharge_{boundary_id}_m3_s")
    return tuple(dict.fromkeys(keys))


def prepare_output_selectors(
    cfg: ModelCalibrationConfig,
) -> tuple[PreparedOutputSelector, ...]:
    """Compile stable observable selectors from launcher config."""
    selectors: list[PreparedOutputSelector] = []
    for output_cfg in cfg.model_calibration.output:
        selectors.append(
            PreparedOutputSelector(
                name=str(output_cfg.name),
                variable=str(output_cfg.variable),
                variable_keys=_output_variable_keys(output_cfg),
                source=str(output_cfg.source),
                support=str(output_cfg.support),
                x=output_cfg.x,
                y=output_cfg.y,
                boundary_id=output_cfg.boundary_id,
                time=output_cfg.time,
                time_window=output_cfg.time_window,
                time_reducer=output_cfg.time_reducer,
                reducer=output_cfg.reducer,
            )
        )
    return tuple(selectors)


def _is_spatial_sample_mapping(payload: Any) -> bool:
    """Return True for `{x, y, values}` or `{coordinates, values}` payloads."""
    if not isinstance(payload, dict) or "values" not in payload:
        return False
    return ("x" in payload and "y" in payload) or "coordinates" in payload


def _as_1d_float_tuple(values: Any, *, label: str) -> tuple[float, ...]:
    """Normalize one selected observable payload to a non-empty float tuple."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty")
    return tuple(float(value) for value in arr)


def _reduce_numeric_values(
    values: Any,
    *,
    reducer: str | None,
    label: str,
) -> tuple[float, ...]:
    """Apply a scalar reducer or return all numeric values."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty")
    reducer_key = "identity" if reducer is None else str(reducer).strip().lower()
    if reducer_key in {"identity", "all", "none"}:
        return tuple(float(value) for value in arr)
    if reducer_key == "sum":
        return (float(np.nansum(arr)),)
    if reducer_key == "mean":
        return (float(np.nanmean(arr)),)
    if reducer_key == "min":
        return (float(np.nanmin(arr)),)
    if reducer_key == "max":
        return (float(np.nanmax(arr)),)
    raise ValueError(f"Unsupported reducer '{reducer}' for {label}")


def _weighted_point_interpolation(
    payload: dict[str, Any],
    *,
    x: float,
    y: float,
    reducer: str | None,
    label: str,
) -> tuple[float, ...]:
    """Interpolate spatial samples at one point using inverse-distance weights."""
    values = np.asarray(payload["values"], dtype=float).ravel()
    if "coordinates" in payload:
        coordinates = np.asarray(payload["coordinates"], dtype=float)
        if coordinates.ndim != 2 or coordinates.shape[1] < 2:
            raise ValueError(f"{label}.coordinates must be a Nx2 array")
        xs = coordinates[:, 0].ravel()
        ys = coordinates[:, 1].ravel()
    else:
        xs = np.asarray(payload["x"], dtype=float).ravel()
        ys = np.asarray(payload["y"], dtype=float).ravel()

    if xs.size != ys.size or xs.size != values.size:
        raise ValueError(f"{label} x/y/value arrays must have the same length")
    if values.size == 0:
        raise ValueError(f"{label} cannot be empty")

    distances = np.hypot(xs - float(x), ys - float(y))
    finite_mask = np.isfinite(distances) & np.isfinite(values)
    if not np.any(finite_mask):
        raise ValueError(f"{label} contains no finite interpolation samples")
    distances = distances[finite_mask]
    values = values[finite_mask]

    exact_mask = distances == 0.0
    if np.any(exact_mask):
        return _reduce_numeric_values(
            values[exact_mask],
            reducer="mean",
            label=label,
        )

    reducer_key = "weighted_interpolation" if reducer is None else str(reducer)
    if reducer_key.strip().lower() == "nearest":
        return (float(values[int(np.argmin(distances))]),)
    if reducer_key.strip().lower() != "weighted_interpolation":
        return _reduce_numeric_values(values, reducer=reducer, label=label)

    weights = 1.0 / distances
    return (float(np.average(values, weights=weights)),)


def _mapping_lookup(mapping: dict[Any, Any], key: Any) -> tuple[bool, Any]:
    """Lookup a mapping key by raw value first, then by string representation."""
    if key in mapping:
        return True, mapping[key]
    text_key = str(key)
    for candidate_key, value in mapping.items():
        if str(candidate_key) == text_key:
            return True, value
    return False, None


def _time_selected_payloads(output_cfg: Any, payload: Any) -> list[Any]:
    """Resolve optional time selection over a variable payload."""
    if not isinstance(payload, dict) or _is_spatial_sample_mapping(payload):
        return [payload]
    if output_cfg.support == "boundary" and output_cfg.boundary_id in payload:
        return [payload]

    if output_cfg.time_window is not None:
        start, end = output_cfg.time_window
        selected = [
            value
            for key, value in payload.items()
            if str(start) <= str(key) <= str(end)
        ]
        return selected or list(payload.values())

    if output_cfg.time not in {None, "all"}:
        found, value = _mapping_lookup(payload, output_cfg.time)
        if found:
            return [value]

    return list(payload.values())


def _select_support_value(output_cfg: Any, payload: Any) -> tuple[float, ...]:
    """Apply the configured spatial support and reducer to a variable payload."""
    label = f"simulated variable '{output_cfg.variable}'"
    if output_cfg.support == "point":
        if not _is_spatial_sample_mapping(payload):
            reducer = (
                "identity"
                if str(output_cfg.reducer).strip().lower()
                == "weighted_interpolation"
                else output_cfg.reducer
            )
            return _reduce_numeric_values(payload, reducer=reducer, label=label)
        return _weighted_point_interpolation(
            payload,
            x=output_cfg.x,
            y=output_cfg.y,
            reducer=output_cfg.reducer,
            label=label,
        )
    if output_cfg.support == "boundary":
        values = payload
        if isinstance(payload, dict) and output_cfg.boundary_id is not None:
            found, boundary_values = _mapping_lookup(payload, output_cfg.boundary_id)
            if found:
                values = boundary_values
            elif "values" in payload:
                values = payload["values"]
        return _reduce_numeric_values(values, reducer=output_cfg.reducer, label=label)
    if output_cfg.support == "cell_mask":
        values = (
            payload["values"]
            if isinstance(payload, dict) and "values" in payload
            else payload
        )
        return _reduce_numeric_values(values, reducer=output_cfg.reducer, label=label)
    if output_cfg.support == "map":
        values = (
            payload["values"]
            if isinstance(payload, dict) and "values" in payload
            else payload
        )
        return _reduce_numeric_values(values, reducer="identity", label=label)
    raise KeyError(
        f"Unsupported output support '{output_cfg.support}' for '{output_cfg.name}'"
    )


def _select_variable_output_value(
    *,
    bundle: CanonicalOutputBundle,
    run_state: Any,
    output_cfg: Any,
) -> tuple[float, ...]:
    """Select one observable by variable/support when no explicit name exists."""
    last_error: Exception | None = None
    variable_keys = getattr(output_cfg, "variable_keys", None)
    if variable_keys is None:
        variable_keys = _output_variable_keys(output_cfg)
    for variable_key in variable_keys:
        try:
            payload = _lookup_bundle_or_run_state(
                bundle=bundle,
                run_state=run_state,
                key=variable_key,
            )
        except KeyError as exc:
            last_error = exc
            continue
        selected_parts: list[float] = []
        for time_payload in _time_selected_payloads(output_cfg, payload):
            selected_parts.extend(_select_support_value(output_cfg, time_payload))
        return _reduce_numeric_values(
            selected_parts,
            reducer=output_cfg.time_reducer,
            label=f"simulated output '{output_cfg.name}'",
        )

    if last_error is not None:
        raise KeyError(
            "Could not find calibration output "
            f"'{output_cfg.name}' or variable '{output_cfg.variable}'"
        ) from last_error
    raise KeyError(f"Could not resolve output '{output_cfg.name}'")


def select_candidate_outputs(
    *,
    cfg: ModelCalibrationConfig,
    run_state: Any,
    result_store: Any = None,
    store_sim_id: str | None = None,
) -> dict[str, tuple[float, ...]]:
    """Select configured simulated observables from one run-state payload."""
    selectors = prepare_output_selectors(cfg)
    return select_candidate_outputs_from_selectors(
        selectors=selectors,
        run_state=run_state,
        result_store=result_store,
        store_sim_id=store_sim_id,
    )


def select_candidate_outputs_from_selectors(
    *,
    selectors: tuple[PreparedOutputSelector, ...],
    run_state: Any,
    result_store: Any = None,
    store_sim_id: str | None = None,
) -> dict[str, tuple[float, ...]]:
    """Select configured observables using prepared selectors."""
    bundle = canonicalize_run_outputs(
        run_state,
        requested_variable_names=_requested_runtime_variable_names(selectors),
        result_store=result_store,
        store_sim_id=store_sim_id,
    )
    selected: dict[str, tuple[float, ...]] = {}
    for output_cfg in selectors:
        try:
            value = _lookup_bundle_or_run_state(
                bundle=bundle,
                run_state=run_state,
                key=output_cfg.name,
            )
            selected[output_cfg.name] = _as_1d_float_tuple(
                value,
                label=f"simulated output '{output_cfg.name}'",
            )
        except KeyError:
            selected[output_cfg.name] = _select_variable_output_value(
                bundle=bundle,
                run_state=run_state,
                output_cfg=output_cfg,
            )
    return selected


__all__ = (
    "CanonicalOutputBundle",
    "CanonicalOutputVariable",
    "PreparedOutputSelector",
    "canonicalize_run_outputs",
    "prepare_output_selectors",
    "select_candidate_outputs",
    "select_candidate_outputs_from_selectors",
)
