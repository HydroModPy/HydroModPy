"""Derived variable computation from stored simulation fields."""

from __future__ import annotations

import logging

import numpy as np

from hydromodpy.simulation.results.store import ResultStore

logger = logging.getLogger(__name__)

# Configurable derived variables and their default state.
DERIVED_VARIABLES = {
    "watertable_elevation": True,
    "watertable_depth": True,
    "seepage_areas": True,
}


def compute_derived(
    sim_id: str,
    store: ResultStore,
    config: dict,
) -> None:
    """Compute all enabled derived variables for a simulation.

    Parameters
    ----------
    sim_id : str
        Simulation UUID.
    store : ResultStore
        Store containing the raw head field.
    config : dict
        Toggles per variable, e.g. ``{"watertable_depth": True}``.
        Missing keys fall back to ``DERIVED_VARIABLES`` defaults.
    """
    flags = {k: config.get(k, v) for k, v in DERIVED_VARIABLES.items()}

    # Determine how many timesteps the head field has
    try:
        import zarr
        root = zarr.open_group(store._zarr_path, mode="r")
        grp = root[sim_id]
        if "head" not in grp:
            logger.debug("No head field stored for sim %s, skipping derived", sim_id)
            return
        head_arr = grp["head"]
        n_timesteps = head_arr.shape[0]
        n_layers = head_arr.shape[1] if head_arr.ndim == 3 else 1
        n_cells = head_arr.shape[-1]
    except Exception:
        logger.debug("Cannot read head field for sim %s", sim_id)
        return

    if flags.get("watertable_elevation"):
        _compute_watertable_elevation(sim_id, store, head_arr, n_timesteps, n_layers, n_cells)

    if flags.get("watertable_depth"):
        _compute_watertable_depth(sim_id, store, head_arr, n_timesteps, n_layers, n_cells)

    if flags.get("seepage_areas"):
        _compute_seepage_areas(sim_id, store, n_timesteps, n_cells)


def _compute_watertable_elevation(
    sim_id: str,
    store: ResultStore,
    head_arr,
    n_timesteps: int,
    n_layers: int,
    n_cells: int,
) -> None:
    """Water table elevation = head at the uppermost saturated layer."""
    try:
        from flopy.utils.postprocessing import get_water_table
    except ImportError:
        get_water_table = None

    for t in range(n_timesteps):
        head = head_arr[t]
        if n_layers == 1:
            wt = head[0] if head.ndim == 2 else head
        elif get_water_table is not None:
            wt = get_water_table(head.reshape(n_layers, -1, 1).squeeze(), hdry=-100.0)
            wt = wt.ravel()[:n_cells]
        else:
            wt = head[0] if head.ndim == 2 else head
        store.write_field(
            sim_id, "watertable_elevation", t,
            wt.astype("float64"),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived watertable_elevation for sim %s", sim_id)


def _compute_watertable_depth(
    sim_id: str,
    store: ResultStore,
    head_arr,
    n_timesteps: int,
    n_layers: int,
    n_cells: int,
) -> None:
    """Water table depth = mesh top elevation - watertable elevation.

    Requires ``watertable_elevation`` already computed and mesh ``z_interfaces``
    in the store. Falls back to a simple top-layer-head approach if mesh data
    is unavailable.
    """
    import zarr
    root = zarr.open_group(store._zarr_path, mode="r")
    grp = root[sim_id]

    # Try to read surface elevation from z_interfaces
    top_elev = None
    if "mesh" in grp and "z_interfaces" in grp["mesh"]:
        z_intf = grp["mesh"]["z_interfaces"][:]
        top_elev = np.full(n_cells, z_intf[0])

    for t in range(n_timesteps):
        try:
            wt = store.query_field(sim_id, "watertable_elevation", t)
        except KeyError:
            head = head_arr[t]
            wt = head[0] if head.ndim == 2 else head

        if top_elev is not None:
            depth = top_elev - wt
        else:
            depth = -wt  # fallback: negative head ≈ depth below datum

        store.write_field(
            sim_id, "watertable_depth", t,
            depth.astype("float64"),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived watertable_depth for sim %s", sim_id)


def _compute_seepage_areas(
    sim_id: str,
    store: ResultStore,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Seepage areas = cells where watertable >= surface elevation.

    Requires both ``watertable_elevation`` and ``z_interfaces``.
    """
    import zarr
    root = zarr.open_group(store._zarr_path, mode="r")
    grp = root[sim_id]

    if "mesh" not in grp or "z_interfaces" not in grp["mesh"]:
        logger.debug("No mesh z_interfaces, skipping seepage_areas for sim %s", sim_id)
        return

    z_intf = grp["mesh"]["z_interfaces"][:]
    top_elev = z_intf[0]

    for t in range(n_timesteps):
        try:
            wt = store.query_field(sim_id, "watertable_elevation", t)
        except KeyError:
            logger.debug("watertable_elevation missing at t=%d, skipping seepage", t)
            return

        seepage = (wt >= top_elev).astype("float64")
        store.write_field(
            sim_id, "seepage_areas", t,
            seepage,
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived seepage_areas for sim %s", sim_id)
