"""Derived variable computation from stored simulation fields."""

from __future__ import annotations

import logging

import numpy as np

from typing import Any

logger = logging.getLogger(__name__)

# Configurable derived variables and their default state.
DERIVED_VARIABLES = {
    "watertable_elevation": True,
    "watertable_depth": True,
    "seepage_areas": True,
    "groundwater_flux": False,
    "accumulation_flux": False,
    "concentration_seepage": False,
    "mass_seepage": False,
    "mass_accumulated": False,
}


def compute_derived(
    sim_id: str,
    store: Any,
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
        grp = store.open_zarr_group(sim_id, mode="r")
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

    if flags.get("groundwater_flux"):
        _compute_groundwater_flux(sim_id, store, n_timesteps, n_layers, n_cells)

    if flags.get("accumulation_flux"):
        _compute_accumulation_flux(sim_id, store, n_timesteps, n_cells)

    if flags.get("concentration_seepage"):
        _compute_concentration_seepage(sim_id, store, n_timesteps, n_cells)

    if flags.get("mass_seepage"):
        _compute_mass_seepage(sim_id, store, n_timesteps, n_cells)

    if flags.get("mass_accumulated"):
        _compute_mass_accumulated(sim_id, store, n_timesteps, n_cells)


def _compute_watertable_elevation(
    sim_id: str,
    store: Any,
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
    store: Any,
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
    grp = store.open_zarr_group(sim_id, mode="r")

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
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Seepage areas = cells where watertable >= surface elevation.

    Requires both ``watertable_elevation`` and ``z_interfaces``.
    """
    grp = store.open_zarr_group(sim_id, mode="r")

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


def _compute_groundwater_flux(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_layers: int,
    n_cells: int,
) -> None:
    """Magnitude of inter-cell groundwater flux from budget components.

    Reads right-face, front-face, and lower-face flow from the budget
    Zarr subgroup and computes the vector magnitude per cell.
    """
    grp = store.open_zarr_group(sim_id, mode="r")
    budget_grp = grp.get("budget")
    if budget_grp is None:
        logger.debug("No budget fields, skipping groundwater_flux for sim %s", sim_id)
        return

    face_keys = []
    for candidate in ("flow_right_face", "flow_front_face", "flow_lower_face",
                       "flow-ja-face", "flow_ja_face"):
        if candidate in budget_grp:
            face_keys.append(candidate)

    if not face_keys:
        logger.debug("No face-flow budget fields for groundwater_flux, sim %s", sim_id)
        return

    for t in range(n_timesteps):
        sq_sum = np.zeros((n_layers, n_cells), dtype="float64")
        for key in face_keys:
            arr = budget_grp[key][t]
            reshaped = arr.reshape(n_layers, n_cells) if arr.shape != (n_layers, n_cells) else arr
            sq_sum += reshaped ** 2
        magnitude = np.sqrt(sq_sum)
        store.write_field(
            sim_id, "groundwater_flux", t, magnitude,
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived groundwater_flux for sim %s", sim_id)


def _compute_accumulation_flux(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Drain flux routed on the drainage network.

    Reads DRN budget component and accumulates outflow per cell.
    """
    grp = store.open_zarr_group(sim_id, mode="r")
    budget_grp = grp.get("budget")
    if budget_grp is None:
        logger.debug("No budget fields, skipping accumulation_flux for sim %s", sim_id)
        return

    drn_key = None
    for candidate in ("drn", "drain", "DRN"):
        if candidate in budget_grp:
            drn_key = candidate
            break

    if drn_key is None:
        logger.debug("No DRN budget field for accumulation_flux, sim %s", sim_id)
        return

    for t in range(n_timesteps):
        drn = budget_grp[drn_key][t]
        # Sum over layers if 3D
        if drn.ndim == 2:
            flux = np.abs(drn).sum(axis=0)
        else:
            flux = np.abs(drn)
        store.write_field(
            sim_id, "accumulation_flux", t, flux.astype("float64"),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived accumulation_flux for sim %s", sim_id)


def _compute_concentration_seepage(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Concentration at seepage cells only. Zero elsewhere."""
    grp = store.open_zarr_group(sim_id, mode="r")
    derived_grp = grp.get("derived")

    if "concentration" not in grp:
        logger.debug("No concentration field, skipping concentration_seepage for sim %s", sim_id)
        return

    for t in range(n_timesteps):
        try:
            seepage = store.query_field(sim_id, "seepage_areas", t)
        except KeyError:
            logger.debug("seepage_areas missing at t=%d, skipping concentration_seepage", t)
            return

        conc = grp["concentration"][t]
        # Use top layer if 3D
        if conc.ndim == 2:
            conc = conc[0]
        result = conc * seepage
        store.write_field(
            sim_id, "concentration_seepage", t, result.astype("float64"),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived concentration_seepage for sim %s", sim_id)


def _compute_mass_seepage(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Mass flux at seepage cells = concentration_seepage * drain outflow."""
    grp = store.open_zarr_group(sim_id, mode="r")
    budget_grp = grp.get("budget")

    if budget_grp is None:
        logger.debug("No budget fields, skipping mass_seepage for sim %s", sim_id)
        return

    drn_key = None
    for candidate in ("drn", "drain", "DRN"):
        if candidate in budget_grp:
            drn_key = candidate
            break

    for t in range(n_timesteps):
        try:
            conc_seep = store.query_field(sim_id, "concentration_seepage", t)
        except KeyError:
            logger.debug("concentration_seepage missing at t=%d, skipping mass_seepage", t)
            return

        if drn_key is not None:
            drn = budget_grp[drn_key][t]
            flux = np.abs(drn).sum(axis=0) if drn.ndim == 2 else np.abs(drn)
        else:
            flux = np.ones(n_cells, dtype="float64")

        mass = conc_seep * flux
        store.write_field(
            sim_id, "mass_seepage", t, mass.astype("float64"),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived mass_seepage for sim %s", sim_id)


def _compute_mass_accumulated(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Cumulative mass_seepage over time."""
    cumul = np.zeros(n_cells, dtype="float64")

    for t in range(n_timesteps):
        try:
            ms = store.query_field(sim_id, "mass_seepage", t)
        except KeyError:
            logger.debug("mass_seepage missing at t=%d, skipping mass_accumulated", t)
            return

        cumul = cumul + ms
        store.write_field(
            sim_id, "mass_accumulated", t, cumul.copy(),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived mass_accumulated for sim %s", sim_id)
