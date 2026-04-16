"""I/O helpers shared by analytical validation cases and their tests."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from hydromodpy.core.config.toml_loader import load_toml_with_base_config, merge_toml_payloads


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


def load_last_npy_array_on_expected_grid(
    postprocess_dir: Path,
    observable_name: str,
    *,
    case_dir: Path,
    metadata: Mapping[str, object],
    solver: str | None,
    expected_shape: tuple[int, ...],
    x_min_m: float | None = None,
    x_max_m: float | None = None,
    collapse_y_to_x_profile: bool = False,
) -> tuple[int, np.ndarray]:
    """Load one validation output and regrid irregular meshes when needed.

    Structured launcher runs already emit arrays matching ``expected_shape``.
    For irregular-triangle launcher runs, the postprocessed watertable output is
    stored as one cell vector. This helper either projects that vector back onto
    the expected structured grid, or reduces it to one area-weighted x-profile
    when ``collapse_y_to_x_profile`` is requested.
    """

    timestep, values = load_last_npy_array(postprocess_dir, observable_name)
    expected_shape = tuple(expected_shape)
    if not expected_shape or tuple(values.shape) == expected_shape:
        return timestep, values

    normalized_solver = str(solver).strip().lower()
    config_files = metadata.get("config_files")
    if not isinstance(config_files, Mapping) or normalized_solver == "":
        raise AssertionError(
            f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
        )

    config_name = str(config_files.get(normalized_solver, "")).strip()
    if config_name == "":
        raise AssertionError(
            f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
        )

    config_payload = load_case_config(case_dir, config_name)
    mesh_input = config_payload.get("mesh_input")
    if not isinstance(mesh_input, Mapping):
        raise AssertionError(
            f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
        )

    bundle_dir_raw = str(mesh_input.get("bundle_dir", "")).strip()
    if bundle_dir_raw == "" or values.ndim != 1 or len(expected_shape) != 2:
        raise AssertionError(
            f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
        )

    bundle_dir = Path(bundle_dir_raw).expanduser()
    if not bundle_dir.is_absolute():
        bundle_dir = (case_dir / bundle_dir).resolve()

    if collapse_y_to_x_profile:
        cells = np.genfromtxt(
            bundle_dir / "cells.csv",
            delimiter=",",
            names=True,
            dtype=None,
            encoding="utf-8",
        )
        centroid_x = np.asarray(cells["centroid_x"], dtype=float).reshape(-1)
        cell_area = np.asarray(cells["area_m2"], dtype=float).reshape(-1)
        x_min = float(np.min(centroid_x)) if x_min_m is None else float(x_min_m)
        x_max = float(np.max(centroid_x)) if x_max_m is None else float(x_max_m)
        x_edges = np.linspace(x_min, x_max, int(expected_shape[1]) + 1, dtype=float)
        profile = np.full(int(expected_shape[1]), np.nan, dtype=float)
        for col_idx in range(int(expected_shape[1])):
            left = float(x_edges[col_idx])
            right = float(x_edges[col_idx + 1])
            if col_idx == int(expected_shape[1]) - 1:
                mask = (centroid_x >= left) & (centroid_x <= right)
            else:
                mask = (centroid_x >= left) & (centroid_x < right)
            if np.any(mask):
                profile[col_idx] = float(np.average(values[mask], weights=cell_area[mask]))
        if np.isnan(profile).any():
            valid_idx = np.flatnonzero(~np.isnan(profile))
            if valid_idx.size == 0:
                raise AssertionError(
                    f"Unexpected shape for {observable_name}: {values.shape} != {expected_shape}"
                )
            profile = np.interp(
                np.arange(profile.size, dtype=float),
                valid_idx.astype(float),
                profile[valid_idx],
            )
        tiled = np.repeat(profile.reshape(1, -1), int(expected_shape[0]), axis=0)
        return timestep, np.asarray(tiled, dtype=float)

    from validation_cases.shared.gmsh_irregular_strip import (
        interpolate_bundle_history_to_structured_grids,
    )

    regridded = interpolate_bundle_history_to_structured_grids(
        values,
        bundle_dir=bundle_dir,
        nx=int(expected_shape[1]),
        ny=int(expected_shape[0]),
        x_min_m=x_min_m,
        x_max_m=x_max_m,
    )
    return timestep, np.asarray(regridded[0], dtype=float)


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
