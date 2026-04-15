"""I/O helpers shared by analytical validation cases and their tests."""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.config.toml_loader import load_toml_with_base_config, merge_toml_payloads

if TYPE_CHECKING:
    from hydromodpy.results.store import ResultStore

logger = logging.getLogger(__name__)


def _aggregate_triangles_to_grid(
    data: np.ndarray,
    target_shape: tuple[int, ...],
    store: Any,
    sim_id: str,
) -> np.ndarray:
    """Bin unstructured triangle-cell values to a structured (nrow, ncol) grid.

    Used when the store contains per-cell data from a triangular mesh but
    the comparison expects a structured grid (e.g. piecewise-strip cases).
    """
    if len(target_shape) != 2:
        return data
    nrow, ncol = target_shape
    try:
        sz = store.open_zarr(sim_id)
        vertices = sz.root["mesh"]["vertices"][:]
        connectivity = sz.root["mesh"]["face_node_connectivity"][:]
        centroids_x = np.mean(vertices[connectivity, 0], axis=1).astype(float)
        centroids_y = np.mean(vertices[connectivity, 1], axis=1).astype(float)
        x_min, x_max = float(centroids_x.min()), float(centroids_x.max())
        y_min, y_max = float(centroids_y.min()), float(centroids_y.max())
        dx = (x_max - x_min) / ncol
        dy = (y_max - y_min) / nrow
        if dx <= 0 or dy <= 0:
            return data
        col_idx = np.clip(((centroids_x - x_min) / dx).astype(int), 0, ncol - 1)
        row_idx = np.clip(((centroids_y - y_min) / dy).astype(int), 0, nrow - 1)
        total = np.zeros((nrow, ncol), dtype=float)
        counts = np.zeros((nrow, ncol), dtype=int)
        for i, v in enumerate(data.flat):
            total[row_idx[i], col_idx[i]] += float(v)
            counts[row_idx[i], col_idx[i]] += 1
        mask = counts > 0
        result = np.zeros((nrow, ncol), dtype=float)
        result[mask] = total[mask] / counts[mask]
        return result
    except Exception:
        logger.debug("Triangle-to-grid aggregation failed, returning raw data")
        return data


def _load_toml(path: Path) -> dict:
    """Load one TOML file into a plain dictionary."""
    with path.open("r", encoding="utf-8") as stream:
        return tomllib.loads(stream.read().lstrip("\ufeff"))


def load_case_metadata(case_dir: Path) -> dict:
    """Load metadata for one validation case directory."""
    return _load_toml(case_dir / "metadata.toml")


def load_case_config(case_dir: Path, filename: str) -> dict:
    """Load one case-local config file with optional ``base_config`` support."""
    return load_toml_with_base_config(case_dir / filename)


def merge_case_flow_section(
    case_dir: Path,
    flow_section: Mapping[str, object],
    *,
    config_name: str = "config_boussinesq.toml",
) -> dict[str, object]:
    """Merge ``[flow]`` defaults from one case config into one runtime payload."""
    config_path = case_dir / str(config_name)
    if not config_path.exists():
        return dict(flow_section)

    config_payload = load_case_config(case_dir, str(config_name))
    raw_flow = config_payload.get("flow", {})
    if raw_flow is None:
        raw_flow = {}
    if not isinstance(raw_flow, Mapping):
        raise TypeError(f"{config_path} [flow] section must be a mapping")
    return merge_toml_payloads(dict(raw_flow), dict(flow_section))


def load_case_tolerances(case_dir: Path, solver: str | None = None) -> dict:
    """Load tolerance thresholds for one validation case directory."""
    if solver is not None:
        solver_name = str(solver).strip().lower()
        if solver_name:
            solver_specific = case_dir / f"tolerances_{solver_name}.toml"
            if solver_specific.exists():
                return _load_toml(solver_specific)
    return _load_toml(case_dir / "tolerances.toml")


def load_npy_dict(path: Path) -> dict:
    """Load one HydroModPy dictionary payload serialized in ``.npy`` format."""
    return np.load(path, allow_pickle=True).item()


def load_last_npy_array(postprocess_dir: Path, observable_name: str) -> tuple[int, np.ndarray]:
    """Load the last timestep array from one HydroModPy ``.npy`` dictionary output."""
    payload = load_npy_dict(postprocess_dir / f"{observable_name}.npy")
    assert payload, f"{observable_name}.npy is empty."
    last_key = sorted(payload)[-1]
    return int(last_key), np.asarray(payload[last_key], dtype=float)


def load_field(
    *,
    postprocess_dir: Path | None = None,
    store: Any = None,
    sim_id: str | None = None,
    observable_name: str,
    timestep: int = -1,
    expected_shape: tuple[int, ...] | None = None,
) -> tuple[int, np.ndarray]:
    """Load one spatial field, preferring the ResultStore when available.

    Parameters
    ----------
    postprocess_dir : Path, optional
        Legacy ``_postprocess`` directory containing ``.npy`` files.
    store : ResultStore, optional
        Open :class:`~hydromodpy.results.store.ResultStore` instance.
    sim_id : str, optional
        Simulation identifier inside *store*.
    observable_name : str
        Variable name (e.g. ``"head"``, ``"watertable_elevation"``).
    timestep : int
        Timestep index to load.  ``-1`` (the default) loads the last
        available timestep, matching the legacy ``load_last_npy_array``
        behaviour.
    expected_shape : tuple[int, ...], optional
        When provided and the loaded array has compatible element count
        but a different shape, reshape it.  This bridges the flat
        per-cell vectors returned by the SimulationCatalog with the
        ``(nrow, ncol)`` grids that legacy ``.npy`` files stored.

    Returns
    -------
    tuple[int, np.ndarray]
        ``(timestep_key, values)`` — the resolved integer timestep key
        and the corresponding spatial array.
    """
    resolved_ts: int
    data: np.ndarray

    # --- Try the store first -------------------------------------------------
    if store is not None and sim_id is not None:
        try:
            raw = store.query_field(sim_id, observable_name, timestep)
            resolved_ts = timestep
            if timestep < 0:
                try:
                    grp = store.open_zarr_group(sim_id)
                    for loc in (grp, grp.get("derived"), grp.get("budget")):
                        if loc is not None and observable_name in loc:
                            n_ts = loc[observable_name].shape[0]
                            resolved_ts = n_ts + timestep
                            break
                except Exception:
                    resolved_ts = timestep
            data = np.asarray(raw, dtype=float)
            eff_shape = expected_shape
            if eff_shape is None and data.ndim == 1:
                try:
                    geo_meta = store.read_geographic_metadata(sim_id)
                    nrow = int(geo_meta.get("nrow", 0))
                    ncol = int(geo_meta.get("ncol", 0))
                    if nrow > 0 and ncol > 0 and nrow * ncol == data.size:
                        eff_shape = (nrow, ncol)
                except Exception:
                    pass
            if (
                eff_shape is not None
                and tuple(data.shape) != eff_shape
                and data.size == int(np.prod(eff_shape))
            ):
                data = data.reshape(eff_shape)
            elif (
                eff_shape is not None
                and tuple(data.shape) != eff_shape
                and data.size != int(np.prod(eff_shape))
            ):
                data = _aggregate_triangles_to_grid(
                    data, eff_shape, store, sim_id,
                )
            return int(resolved_ts), data
        except Exception:
            logger.debug(
                "ResultStore query failed for variable '%s' (sim_id=%s), "
                "falling back to legacy .npy loader.",
                observable_name,
                sim_id,
                exc_info=True,
            )

    # --- Fallback to legacy .npy loader --------------------------------------
    if postprocess_dir is None:
        raise ValueError(
            f"Cannot load field '{observable_name}': no store provided and "
            "postprocess_dir is None."
        )
    return load_last_npy_array(postprocess_dir, observable_name)


def load_time_series_fields(
    *,
    postprocess_dir: Path | None = None,
    store: Any = None,
    sim_id: str | None = None,
    observable_name: str,
    expected_spatial_shape: tuple[int, ...] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Load all timesteps for one variable, preferring the store.

    Returns ``(period_indices, stacked_arrays)`` where
    ``stacked_arrays`` has shape ``(n_timesteps, *spatial_shape)``.
    """
    if store is not None and sim_id is not None:
        try:
            grp = store.open_zarr_group(sim_id)
            arr = None
            for loc in (grp, grp.get("derived"), grp.get("budget")):
                if loc is not None and observable_name in loc:
                    arr = loc[observable_name][:]
                    break
            if arr is not None:
                data = np.asarray(arr, dtype=float)
                # Zarr shape is (n_timesteps, n_layers, n_cells) or (n_timesteps, n_cells)
                # Remove singleton layer dim if present
                if data.ndim == 3 and data.shape[1] == 1:
                    data = data[:, 0, :]
                n_ts = data.shape[0]
                indices = np.arange(n_ts, dtype=int)
                # Resolve expected shape from metadata if not provided
                eff_shape = expected_spatial_shape
                if eff_shape is None and data.ndim == 2:
                    try:
                        geo_meta = store.read_geographic_metadata(sim_id)
                        nrow = int(geo_meta.get("nrow", 0))
                        ncol = int(geo_meta.get("ncol", 0))
                        if nrow > 0 and ncol > 0 and nrow * ncol == data.shape[1]:
                            eff_shape = (nrow, ncol)
                    except Exception:
                        pass
                if (
                    eff_shape is not None
                    and tuple(data.shape[1:]) != eff_shape
                    and data[:1].size > 0
                    and int(np.prod(data.shape[1:])) == int(np.prod(eff_shape))
                ):
                    data = data.reshape(n_ts, *eff_shape)
                return indices, data
        except Exception:
            logger.debug(
                "Store Zarr query failed for '%s' (sim_id=%s), "
                "trying DuckDB timeseries.",
                observable_name,
                sim_id,
                exc_info=True,
            )

        # Try DuckDB timeseries (scalar per timestep, e.g. outlet discharge)
        try:
            ts = store.query_timeseries(sim_id, "_catchment", observable_name)
            values = np.asarray(ts.values, dtype=float)
            indices = np.arange(values.shape[0], dtype=int)
            return indices, values
        except Exception:
            pass

        # Derive outlet discharge from budget table (constant head flux_out)
        if "outlet_discharge" in observable_name:
            try:
                budgets = store.query_budget(sim_id)
                if not budgets.empty:
                    chd_names = ("constant head", "chd")
                    chd = budgets[budgets["component"].str.lower().isin(chd_names)]
                    if not chd.empty:
                        chd_sorted = chd.sort_values("timestep")
                        values = np.asarray(chd_sorted["flux_out"].values, dtype=float)
                        indices = np.arange(values.shape[0], dtype=int)
                        return indices, values
            except Exception:
                pass

        logger.debug(
            "Store queries failed for '%s' (sim_id=%s), "
            "falling back to legacy .npy loader.",
            observable_name,
            sim_id,
        )

    if postprocess_dir is None:
        raise ValueError(
            f"Cannot load time-series '{observable_name}': no store provided and "
            "postprocess_dir is None."
        )
    return load_npy_time_series_arrays(postprocess_dir, observable_name)


def load_npy_time_series_arrays(
    postprocess_dir: Path,
    observable_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Load one full HydroModPy ``.npy`` time series as sorted stacked arrays."""
    payload = load_npy_dict(postprocess_dir / f"{observable_name}.npy")
    assert payload, f"{observable_name}.npy is empty."

    ordered_items = sorted((int(key), np.asarray(value, dtype=float)) for key, value in payload.items())
    indices = np.asarray([key for key, _ in ordered_items], dtype=int)
    arrays = np.stack([value for _, value in ordered_items], axis=0)
    return indices, arrays
