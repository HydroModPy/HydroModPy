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

    Returns
    -------
    tuple[int, np.ndarray]
        ``(timestep_key, values)`` — the resolved integer timestep key
        and the corresponding spatial array.
    """
    # --- Try the store first -------------------------------------------------
    if store is not None and sim_id is not None:
        try:
            data = store.query_field(sim_id, observable_name, timestep)
            resolved_ts = timestep
            # When the caller asked for the last timestep via -1, try to
            # resolve the actual integer key from the Zarr array shape.
            if timestep < 0:
                try:
                    grp = store.open_zarr_group(sim_id)
                    for loc in (grp, grp.get("derived"), grp.get("budget")):
                        if loc is not None and observable_name in loc:
                            n_ts = loc[observable_name].shape[0]
                            resolved_ts = n_ts + timestep  # e.g. n-1 for -1
                            break
                except Exception:
                    resolved_ts = timestep
            return int(resolved_ts), np.asarray(data, dtype=float)
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
