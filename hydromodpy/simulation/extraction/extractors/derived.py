"""Derived variable computation from stored simulation fields."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import numpy as np

from hydromodpy.core.field_routing import (
    accumulate_downhill_on_mesh,
    active_surface_mask,
    drain_budget_to_positive_outflow,
    find_drain_budget_key,
)
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
    "release_flux": False,
    "accumulation_flux": False,
    "release_accumulation_flux": False,
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

    if flags.get("release_flux") or flags.get("release_accumulation_flux"):
        _compute_release_flux(sim_id, store, n_timesteps, n_cells)

    if flags.get("accumulation_flux"):
        _compute_accumulation_flux(sim_id, store, n_timesteps, n_cells)

    if flags.get("release_accumulation_flux"):
        _compute_release_accumulation_flux(sim_id, store, n_timesteps, n_cells)

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
    """Seepage mask from explicit surface excess or geometric saturation.

    Boussinesq can persist ``budget/surface_excess`` as the explicit
    surface-release signal. When present, that field is the canonical seepage
    source; otherwise MODFLOW-style runs use ``watertable >= surface_top``.
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
        budget_grp = grp.get("budget")
        surface_excess_stack = None
        if budget_grp is not None and "surface_excess" in budget_grp:
            surface_excess_stack = np.asarray(budget_grp["surface_excess"][:], dtype="float64")

    for t in range(n_timesteps):
        if surface_excess_stack is not None:
            seepage = (_positive_cell_flux(surface_excess_stack[t], n_cells=n_cells) > 0.0).astype(
                "float64"
            )
        else:
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


def _drain_outflow_stack(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> np.ndarray:
    """Read the positive drain outflow as a ``time x cell`` stack."""
    with _zarr_root(store, sim_id) as grp:
        budget_grp = grp.get("budget")
        if budget_grp is None:
            raise KeyError("No budget fields")

        drn_key = find_drain_budget_key(budget_grp)
        if drn_key is None:
            raise KeyError("No DRN budget field")

        if int(n_timesteps) <= 0:
            return np.empty((0, int(n_cells)), dtype="float64")
        return np.stack(
            [
                drain_budget_to_positive_outflow(budget_grp[drn_key][t], n_cells=n_cells)
                for t in range(n_timesteps)
            ]
        ).astype("float64", copy=False)


def _compute_accumulation_flux(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Route positive drain outflow downstream."""
    try:
        drain_stack = _drain_outflow_stack(sim_id, store, n_timesteps, n_cells)
    except KeyError as exc:
        logger.debug("%s, skipping accumulation_flux for sim %s", exc, sim_id)
        return

    _route_cell_flux_stack_with_fallback(
        sim_id,
        store,
        drain_stack,
        "accumulation_flux",
        n_timesteps,
        n_cells,
        local_label="local drain outflow",
    )


def _positive_cell_flux(component_field: Any, *, n_cells: int) -> np.ndarray:
    """Return positive per-cell volumetric outflow from a budget-like field."""
    field = np.asarray(component_field, dtype=float)
    if field.size == 0:
        return np.zeros(int(n_cells), dtype="float64")
    if field.size % int(n_cells) == 0:
        values = field.reshape(-1, int(n_cells))
    elif field.ndim == 1:
        values = field.reshape(1, -1)
    else:
        values = field.reshape(field.shape[0], -1)
    if values.shape[-1] != int(n_cells):
        raise ValueError(
            f"Budget component has {values.shape[-1]} cells after reshape; expected {n_cells}."
        )
    finite = np.isfinite(values) & (values > -9000.0)
    positive = np.where(finite, np.maximum(values, 0.0), 0.0)
    return positive.sum(axis=0).astype("float64", copy=False)


def _release_flux_stack(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> np.ndarray:
    """Read drain plus surface-excess outflow as a solver-neutral stack."""
    with _zarr_root(store, sim_id) as grp:
        budget_grp = grp.get("budget")
        if budget_grp is None:
            raise KeyError("No budget fields")

        drn_key = find_drain_budget_key(budget_grp)
        has_surface_excess = "surface_excess" in budget_grp
        if drn_key is None and not has_surface_excess:
            raise KeyError("No drain or surface_excess budget field")

        frames: list[np.ndarray] = []
        for t in range(n_timesteps):
            release = np.zeros(int(n_cells), dtype="float64")
            if drn_key is not None:
                release += drain_budget_to_positive_outflow(budget_grp[drn_key][t], n_cells=n_cells)
            if has_surface_excess:
                release += _positive_cell_flux(budget_grp["surface_excess"][t], n_cells=n_cells)
            frames.append(release)

    if not frames:
        return np.empty((0, int(n_cells)), dtype="float64")
    return np.stack(frames).astype("float64", copy=False)


def _compute_release_flux(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Total positive groundwater release flux per cell.

    ``release_flux`` is a solver-neutral postprocessing field. It combines
    positive drain outflow and positive saturation/surface-excess outflow when
    those budget components are present. The components are intentionally not
    distinguished in the resulting diagnostic field.
    """
    try:
        release_stack = _release_flux_stack(sim_id, store, n_timesteps, n_cells)
    except KeyError as exc:
        logger.debug("%s, skipping release_flux for sim %s", exc, sim_id)
        return

    _write_derived_stack(
        sim_id,
        store,
        "release_flux",
        release_stack,
        n_timesteps,
        n_cells,
    )
    logger.debug("Derived release_flux for sim %s", sim_id)


def _read_derived_stack(
    store: Any,
    sim_id: str,
    variable: str,
    *,
    n_timesteps: int,
    n_cells: int,
) -> np.ndarray:
    """Read one derived time-face stack directly from the Zarr store."""
    with _zarr_root(store, sim_id) as grp:
        derived = grp.get("derived")
        if derived is None or variable not in derived:
            raise KeyError(f"Missing derived/{variable}")
        stack = np.asarray(derived[variable][:], dtype="float64")
    if stack.ndim == 1:
        stack = stack.reshape(1, -1)
    stack = stack.reshape(stack.shape[0], -1)
    if stack.shape[0] < int(n_timesteps):
        raise ValueError(f"derived/{variable} has {stack.shape[0]} timesteps, expected {n_timesteps}.")
    if stack.shape[1] != int(n_cells):
        raise ValueError(f"derived/{variable} has {stack.shape[1]} cells, expected {n_cells}.")
    return stack[:n_timesteps]


def _write_derived_stack(
    sim_id: str,
    store: Any,
    variable: str,
    stack: np.ndarray,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Write a validated ``time x cell`` stack to ``derived/<variable>``."""
    values = np.asarray(stack, dtype="float64")
    if values.ndim == 1:
        values = values.reshape(1, -1)
    values = values.reshape(values.shape[0], -1)
    if values.shape[0] < int(n_timesteps):
        raise ValueError(f"{variable} has {values.shape[0]} timesteps, expected {n_timesteps}.")
    if values.shape[1] != int(n_cells):
        raise ValueError(f"{variable} has {values.shape[1]} cells, expected {n_cells}.")

    for t in range(n_timesteps):
        field = np.maximum(values[t], 0.0)
        field = np.where(np.isfinite(field), field, 0.0).astype("float64", copy=False)
        store.write_field(
            sim_id,
            variable,
            t,
            field,
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )


def _route_cell_flux_stack_with_fallback(
    sim_id: str,
    store: Any,
    local_stack: np.ndarray,
    output_variable: str,
    n_timesteps: int,
    n_cells: int,
    *,
    local_label: str,
) -> None:
    """Route a positive cell-flux stack, falling back to the local field."""
    try:
        _accumulate_cell_stack_raster_d8(
            sim_id,
            store,
            local_stack,
            output_variable,
            n_timesteps,
            n_cells,
        )
        logger.debug("Derived %s (raster D8 routed) for sim %s", output_variable, sim_id)
        return
    except Exception:
        logger.debug(
            "Raster D8 routing unavailable for %s on sim %s, trying mesh graph routing",
            output_variable,
            sim_id,
            exc_info=True,
        )

    try:
        _accumulate_cell_stack_mesh_graph(
            sim_id,
            store,
            local_stack,
            output_variable,
            n_timesteps,
            n_cells,
        )
        logger.debug("Derived %s (mesh graph routed) for sim %s", output_variable, sim_id)
        return
    except Exception:
        logger.debug(
            "Mesh graph routing unavailable for %s on sim %s, using %s",
            output_variable,
            sim_id,
            local_label,
            exc_info=True,
        )

    _write_derived_stack(
        sim_id,
        store,
        output_variable,
        local_stack,
        n_timesteps,
        n_cells,
    )
    logger.debug("Derived %s (%s) for sim %s", output_variable, local_label, sim_id)


def _compute_release_accumulation_flux(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Route ``release_flux`` downstream and persist it as a separate field."""
    try:
        release_stack = _read_derived_stack(
            store,
            sim_id,
            "release_flux",
            n_timesteps=n_timesteps,
            n_cells=n_cells,
        )
    except Exception:
        logger.debug("Cannot read release_flux for release_accumulation_flux, sim %s", sim_id)
        return

    _route_cell_flux_stack_with_fallback(
        sim_id,
        store,
        release_stack,
        "release_accumulation_flux",
        n_timesteps,
        n_cells,
        local_label="local release_flux",
    )


def _accumulate_cell_stack_raster_d8(
    sim_id: str,
    store: Any,
    local_stack: np.ndarray,
    output_variable: str,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Route a positive cell-flux stack downstream via Whitebox D8 mass flux."""
    import tempfile
    from pathlib import Path

    import rasterio

    from hydromodpy.spatial.delineation import get_whitebox_backend

    with _zarr_root(store, sim_id) as grp:
        mesh = grp.get("mesh")
        if mesh is None or "surface_top" not in mesh:
            raise KeyError("No mesh/surface_top for routing")
        surface_top = np.asarray(mesh["surface_top"][:], dtype="float64")
        if "face_node_connectivity" in mesh:
            raise ValueError("UGRID mesh routing should use mesh graph routing")

    geo_meta = store.read_geographic_metadata(sim_id)
    crs_epsg = _metadata_epsg(geo_meta)
    nrow = int(geo_meta.get("nrow", 0))
    ncol = int(geo_meta.get("ncol", 0))
    if nrow * ncol == n_cells:
        grid_shape = (nrow, ncol)
    else:
        side = int(np.sqrt(n_cells))
        if side * side == n_cells:
            grid_shape = (side, side)
        else:
            raise ValueError(f"Cannot infer 2D grid shape from n_cells={n_cells}")

    wb = get_whitebox_backend()

    with tempfile.TemporaryDirectory(prefix="hmp_accflux_") as tmp:
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
            np.where(np.isfinite(fill_data) & (fill_data > -9000.0), 1.0, -99999),
            -99999.0,
            crs_epsg=crs_epsg,
        )
        _write_bare_tif(
            abs_path,
            np.where(np.isfinite(fill_data) & (fill_data > -9000.0), 0.0, -99999),
            -99999.0,
            crs_epsg=crs_epsg,
        )

        for t in range(n_timesteps):
            local_2d = np.maximum(np.asarray(local_stack[t], dtype="float64"), 0.0).reshape(
                grid_shape
            )
            local_2d[~np.isfinite(local_2d)] = 0.0

            load_path = str(Path(tmp) / "load.tif")
            out_path = str(Path(tmp) / "acc.tif")
            _write_bare_tif(load_path, local_2d, -99999.0, crs_epsg=crs_epsg)
            wb.flow.d8_mass_flux(fill_path, load_path, eff_path, abs_path, out_path)

            with rasterio.open(out_path) as src:
                acc = src.read(1).astype("float64")
            acc[acc < 0] = 0.0

            store.write_field(
                sim_id,
                output_variable,
                t,
                acc.ravel(),
                n_timesteps=n_timesteps if t == 0 else None,
                subgroup="derived",
            )


def _accumulate_cell_stack_mesh_graph(
    sim_id: str,
    store: Any,
    local_stack: np.ndarray,
    output_variable: str,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Route a positive cell-flux stack on a UGRID mesh graph."""
    with _zarr_root(store, sim_id) as grp:
        mesh = grp.get("mesh")
        if mesh is None or "surface_top" not in mesh or "face_node_connectivity" not in mesh:
            raise KeyError("No mesh topology for graph routing")
        surface_top = np.asarray(mesh["surface_top"][:], dtype="float64").reshape(-1)[:n_cells]
        face_node_connectivity = np.asarray(mesh["face_node_connectivity"][:], dtype="int32")
        vertices = np.asarray(mesh["vertices"][:], dtype="float64") if "vertices" in mesh else None

    if surface_top.size != n_cells:
        raise ValueError(f"surface_top has {surface_top.size} cells, expected {n_cells}.")
    inactive = ~active_surface_mask(surface_top)

    for t in range(n_timesteps):
        local = np.maximum(np.asarray(local_stack[t], dtype="float64").reshape(-1), 0.0)
        accumulation = accumulate_downhill_on_mesh(
            local,
            surface_top,
            face_node_connectivity,
            vertices=vertices,
            inactive_mask=inactive,
        )
        store.write_field(
            sim_id,
            output_variable,
            t,
            accumulation.astype("float64"),
            n_timesteps=n_timesteps if t == 0 else None,
            subgroup="derived",
        )


def _compute_outflow_drain(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Positive per-cell drain outflow summed over layers."""
    try:
        drain_stack = _drain_outflow_stack(sim_id, store, n_timesteps, n_cells)
    except KeyError as exc:
        logger.debug("%s, skipping outflow_drain for sim %s", exc, sim_id)
        return

    _write_derived_stack(sim_id, store, "outflow_drain", drain_stack, n_timesteps, n_cells)
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

        drn_key = find_drain_budget_key(budget_grp)

        for t in range(n_timesteps):
            try:
                conc_seep = store.query_field(sim_id, "concentration_seepage", t)
            except KeyError:
                logger.debug("concentration_seepage missing at t=%d, skipping mass_seepage", t)
                return

            if drn_key is not None:
                drn = budget_grp[drn_key][t]
                flux = drain_budget_to_positive_outflow(drn, n_cells=n_cells)
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
