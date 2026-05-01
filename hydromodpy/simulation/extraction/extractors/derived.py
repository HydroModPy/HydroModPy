"""Derived variable computation from stored simulation fields."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


@contextmanager
def _zarr_root(store: Any, sim_id: str):
    """Open a simulation Zarr root and close its handle."""
    sz = store.open_zarr(sim_id)
    try:
        yield sz.root
    finally:
        sz.close()


def _write_bare_tif(
    path: str,
    data: np.ndarray,
    nodata: float = -99999.0,
    *,
    crs_epsg: int | None = None,
) -> None:
    """Write a 2D array as a minimal GeoTIFF for Whitebox routing."""
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds

    nrow, ncol = data.shape
    transform = from_bounds(0, 0, ncol, nrow, ncol, nrow)
    crs = CRS.from_epsg(crs_epsg) if crs_epsg is not None else None
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=nrow,
        width=ncol,
        count=1,
        dtype=data.dtype,
        nodata=nodata,
        transform=transform,
        crs=crs,
    ) as dst:
        dst.write(data, 1)


def _metadata_epsg(metadata: dict[str, object]) -> int | None:
    """Return EPSG code from geographic metadata when available."""
    raw = metadata.get("epsg") or metadata.get("crs_epsg")
    if raw is None:
        return None
    try:
        value = int(str(raw).split(":")[-1])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# Configurable derived variables and their default state. Watertable
# elevation/depth are written by the workflow ``DeriveStep`` registry
# (single canonical writer); this module only handles solver-adjacent or
# transport-specific derivations.
DERIVED_VARIABLES = {
    "seepage_areas": True,
    "groundwater_flux": False,
    "accumulation_flux": False,
    "outflow_drain": False,
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
    store : SimulationCatalog
        Store containing the raw head field.
    config : dict
        Toggles per variable, e.g. ``{"watertable_depth": True}``.
        Missing keys fall back to ``DERIVED_VARIABLES`` defaults.
    """
    flags = {k: config.get(k, v) for k, v in DERIVED_VARIABLES.items()}

    # Determine how many timesteps the head field has
    try:
        with _zarr_root(store, sim_id) as grp:
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

    if flags.get("seepage_areas"):
        _compute_seepage_mask(sim_id, store, n_timesteps, n_cells)

    if flags.get("groundwater_flux"):
        _compute_groundwater_flux(sim_id, store, n_timesteps, n_layers, n_cells)

    if flags.get("accumulation_flux"):
        _compute_accumulation_flux(sim_id, store, n_timesteps, n_cells)

    if flags.get("outflow_drain"):
        _compute_outflow_drain(sim_id, store, n_timesteps, n_cells)

    if flags.get("concentration_seepage"):
        _compute_concentration_seepage(sim_id, store, n_timesteps, n_cells)

    if flags.get("mass_seepage"):
        _compute_mass_seepage(sim_id, store, n_timesteps, n_cells)

    if flags.get("mass_accumulated"):
        _compute_mass_accumulated(sim_id, store, n_timesteps, n_cells)


def _compute_seepage_mask(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Seepage mask = cells where watertable >= surface elevation.

    Requires both ``watertable_elevation`` and ``z_interfaces``.
    """
    with _zarr_root(store, sim_id) as grp:
        if "mesh" not in grp:
            logger.debug("No mesh data, skipping seepage_mask for sim %s", sim_id)
            return

        mesh = grp["mesh"]
        if "surface_top" in mesh:
            top_elev = np.asarray(mesh["surface_top"][:], dtype="float64").ravel()[:n_cells]
        elif "z_interfaces" in mesh:
            z_intf = mesh["z_interfaces"][:]
            top_elev = np.full(n_cells, float(z_intf[0]))
        else:
            logger.debug("No surface elevation data, skipping seepage_mask for sim %s", sim_id)
            return

    for t in range(n_timesteps):
        try:
            wt = store.query_field(sim_id, "watertable_elevation", t)
        except KeyError:
            logger.debug("watertable_elevation missing at t=%d, skipping seepage", t)
            return

        seepage = (wt >= top_elev).astype("float64")
        store.write_field(
            sim_id,
            "seepage_mask",
            t,
            seepage,
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived seepage_mask for sim %s", sim_id)


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
    with _zarr_root(store, sim_id) as grp:
        budget_grp = grp.get("budget")
        if budget_grp is None:
            logger.debug("No budget fields, skipping groundwater_flux for sim %s", sim_id)
            return

        face_keys = []
        for candidate in (
            "flow_right_face",
            "flow_front_face",
            "flow_lower_face",
            "flow-ja-face",
            "flow_ja_face",
        ):
            if candidate in budget_grp:
                face_keys.append(candidate)

        if not face_keys:
            logger.debug("No face-flow budget fields for groundwater_flux, sim %s", sim_id)
            return

        for t in range(n_timesteps):
            sq_sum = np.zeros((n_layers, n_cells), dtype="float64")
            for key in face_keys:
                arr = budget_grp[key][t]
                reshaped = (
                    arr.reshape(n_layers, n_cells) if arr.shape != (n_layers, n_cells) else arr
                )
                sq_sum += reshaped**2
            magnitude = np.sqrt(sq_sum)
            store.write_field(
                sim_id,
                "groundwater_flux",
                t,
                magnitude,
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

    Tries to route via whitebox d8_mass_flux using the geographic fill DEM
    from the store (produces a connected stream network). Falls back to
    simple ``abs(drn)`` per cell if geographic data or whitebox is unavailable.
    """
    with _zarr_root(store, sim_id) as grp:
        budget_grp = grp.get("budget")
        if budget_grp is None:
            logger.debug("No budget fields, skipping accumulation_flux for sim %s", sim_id)
            return

        drn_key = None
        for candidate in ("drn", "drain", "drains", "DRN", "DRAINS"):
            if candidate in budget_grp:
                drn_key = candidate
                break

        if drn_key is None:
            logger.debug("No DRN budget field for accumulation_flux, sim %s", sim_id)
            return

        try:
            _accumulation_flux_routed(
                sim_id,
                store,
                budget_grp,
                drn_key,
                n_timesteps,
                n_cells,
            )
            logger.debug("Derived accumulation_flux (routed) for sim %s", sim_id)
            return
        except Exception:
            logger.debug(
                "Whitebox routing unavailable for sim %s, falling back to abs(drn)",
                sim_id,
            )

        for t in range(n_timesteps):
            drn = budget_grp[drn_key][t]
            if drn.ndim == 2:
                flux = np.abs(drn).sum(axis=0)
            else:
                flux = np.abs(drn)
            store.write_field(
                sim_id,
                "accumulation_flux",
                t,
                flux.astype("float64"),
                n_timesteps=n_timesteps if t == 0 else None,
                subgroup="derived",
            )

    logger.debug("Derived accumulation_flux (simple) for sim %s", sim_id)


def _accumulation_flux_routed(
    sim_id: str,
    store: Any,
    budget_grp: Any,
    drn_key: str,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Route drain outflow downstream via whitebox d8_mass_flux.

    Uses ``mesh/surface_top`` from the simulation store (at the solver
    grid resolution) rather than the geographic fill DEM, so that routing
    works even when the MODFLOW grid is resampled to a different shape.
    """
    import tempfile
    from pathlib import Path

    import rasterio

    from hydromodpy.spatial.delineation import get_whitebox_backend

    # Read surface_top from mesh (solver resolution) and infer 2D shape.
    with _zarr_root(store, sim_id) as grp:
        mesh = grp.get("mesh")
        if mesh is None or "surface_top" not in mesh:
            raise KeyError("No mesh/surface_top for routing")
        surface_top = np.asarray(mesh["surface_top"][:], dtype="float64")

    # Infer 2D grid shape: try geographic metadata first, then assume square.
    geo_meta = store.read_geographic_metadata(sim_id)
    crs_epsg = _metadata_epsg(geo_meta)
    nrow = int(geo_meta.get("nrow", 0))
    ncol = int(geo_meta.get("ncol", 0))
    if nrow * ncol == n_cells:
        grid_shape = (nrow, ncol)
    else:
        # Resampled grid - infer from n_cells (square grids or from DuckDB).
        side = int(np.sqrt(n_cells))
        if side * side == n_cells:
            grid_shape = (side, side)
        else:
            raise ValueError(f"Cannot infer 2D grid shape from n_cells={n_cells}")

    wb = get_whitebox_backend()

    with tempfile.TemporaryDirectory(prefix="hmp_accflux_") as tmp:
        # Fill surface_top with whitebox to get proper D8 routing.
        dem_path = str(Path(tmp) / "dem.tif")
        fill_path = str(Path(tmp) / "fill.tif")

        dem_2d = surface_top.reshape(grid_shape)
        _write_bare_tif(dem_path, dem_2d, -99999.0, crs_epsg=crs_epsg)
        wb.flow.fill_depressions(dem_path, fill_path)

        with rasterio.open(fill_path) as src:
            fill_data = src.read(1)

        eff_path = str(Path(tmp) / "eff.tif")
        abs_path = str(Path(tmp) / "abs.tif")
        _write_bare_tif(
            eff_path,
            np.where(fill_data >= 0, 1.0, -99999),
            -99999.0,
            crs_epsg=crs_epsg,
        )
        _write_bare_tif(
            abs_path,
            np.where(fill_data >= 0, 0.0, -99999),
            -99999.0,
            crs_epsg=crs_epsg,
        )

        for t in range(n_timesteps):
            drn = budget_grp[drn_key][t]
            drain_abs = np.abs(drn).sum(axis=0) if drn.ndim == 2 else np.abs(drn)
            drain_2d = drain_abs.reshape(grid_shape)
            drain_2d[~np.isfinite(drain_2d)] = 0.0

            load_path = str(Path(tmp) / "load.tif")
            out_path = str(Path(tmp) / "acc.tif")
            _write_bare_tif(load_path, drain_2d, -99999.0, crs_epsg=crs_epsg)
            wb.flow.d8_mass_flux(fill_path, load_path, eff_path, abs_path, out_path)

            with rasterio.open(out_path) as src:
                acc = src.read(1).astype("float64")
            acc[acc < 0] = 0.0

            store.write_field(
                sim_id,
                "accumulation_flux",
                t,
                acc.ravel(),
                n_timesteps=n_timesteps if t == 0 else None,
                subgroup="derived",
            )


def _compute_outflow_drain(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Per-cell drain outflow preserving sign convention.

    Like accumulation_flux but keeps the physical sign (negative = outflow).
    """
    with _zarr_root(store, sim_id) as grp:
        budget_grp = grp.get("budget")
        if budget_grp is None:
            logger.debug("No budget fields, skipping outflow_drain for sim %s", sim_id)
            return

        drn_key = None
        for candidate in ("drn", "drain", "drains", "DRN", "DRAINS"):
            if candidate in budget_grp:
                drn_key = candidate
                break

        if drn_key is None:
            logger.debug("No DRN budget field for outflow_drain, sim %s", sim_id)
            return

        for t in range(n_timesteps):
            drn = budget_grp[drn_key][t]
            if drn.ndim == 2:
                flux = drn.sum(axis=0)
            else:
                flux = drn
            store.write_field(
                sim_id,
                "outflow_drain",
                t,
                flux.astype("float64"),
                n_timesteps=n_timesteps if t == 0 else None,
                subgroup="derived",
            )

    logger.debug("Derived outflow_drain for sim %s", sim_id)


def _compute_concentration_seepage(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Concentration at seepage cells only. Zero elsewhere."""
    with _zarr_root(store, sim_id) as grp:
        if "concentration" not in grp:
            logger.debug(
                "No concentration field, skipping concentration_seepage for sim %s", sim_id
            )
            return

        for t in range(n_timesteps):
            try:
                seepage = store.query_field(sim_id, "seepage_mask", t)
            except KeyError:
                logger.debug("seepage_mask missing at t=%d, skipping concentration_seepage", t)
                return

            conc = grp["concentration"][t]
            if conc.ndim == 2:
                conc = conc[0]
            result = np.where(seepage > 0, conc * seepage, np.nan)
            store.write_field(
                sim_id,
                "concentration_seepage",
                t,
                result.astype("float64"),
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
    with _zarr_root(store, sim_id) as grp:
        budget_grp = grp.get("budget")

        if budget_grp is None:
            logger.debug("No budget fields, skipping mass_seepage for sim %s", sim_id)
            return

        drn_key = None
        for candidate in ("drn", "drain", "drains", "DRN", "DRAINS"):
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
                sim_id,
                "mass_seepage",
                t,
                mass.astype("float64"),
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
            sim_id,
            "mass_accumulated",
            t,
            cumul.copy(),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )

    logger.debug("Derived mass_accumulated for sim %s", sim_id)
