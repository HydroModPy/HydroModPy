"""Derived variable computation from stored simulation fields."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import numpy as np

from hydromodpy.core import progress
from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    active_surface_mask,
    build_downhill_graph,
    drain_budget_stack_to_positive_outflow,
    find_drain_budget_key,
    seepage_mask,
    warn_on_geometric_seepage_fallback,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.nodata import RESULTS_NODATA

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
    nodata: float = RESULTS_NODATA,
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


def _budget_dependency_error(variable: str, sim_id: str, cause: Exception) -> ExtractError:
    """Error raised when a budget-dependent derived field has no budget to read."""
    return ExtractError(
        f"Derived field '{variable}' was requested for sim {sim_id} but the per-cell "
        f"budget it needs is unavailable ({cause}). Set "
        "[simulation.results.budget] spatial_fields = true, or drop "
        f"[simulation.results.derived] {variable}."
    )


def _derived_dependency_error(variable: str, sim_id: str, dependency_flag: str) -> ExtractError:
    """Error raised when a requested derived field misses another derived input."""
    return ExtractError(
        f"Derived field '{variable}' was requested for sim {sim_id} but the "
        f"'{dependency_flag}' field it is built from is not in the store. Set "
        f"[simulation.results.derived] {dependency_flag} = true, or drop "
        f"[simulation.results.derived] {variable}."
    )


def _log_waiting_for_transport(variable: str, sim_id: str) -> None:
    """Report a solute derivation deferred to the solute-transport run.

    Post-run derivation happens after every run, so the flow run of a
    flow-then-transport plan reaches the solute chain before any concentration
    exists. A plan whose only transport run is particle tracking never gets
    here: reconciliation turns those flags off, and says so.
    """
    logger.info(
        "Derived field '%s' waits for the solute transport run of sim %s: the store holds "
        "no concentration field yet.",
        variable,
        sim_id,
    )


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
    store : Catalog
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
            n_cells = head_arr.shape[-1]
    except Exception:
        logger.debug("Cannot read head field for sim %s", sim_id)
        return

    if flags.get("seepage_areas"):
        _compute_seepage_mask(sim_id, store, n_timesteps, n_cells)

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
    source; otherwise MODFLOW-style runs use ``watertable >= topography``.
    """
    with _zarr_root(store, sim_id) as grp:
        existing = grp.get("derived")
        if existing is not None and "seepage_mask" in existing:
            logger.debug("seepage_mask already present, skipping recompute for sim %s", sim_id)
            return
        if "mesh" not in grp:
            logger.debug("No mesh data, skipping seepage_mask for sim %s", sim_id)
            return

        mesh = grp["mesh"]
        if "topography" in mesh:
            top_elev = np.asarray(mesh["topography"][:], dtype="float64").ravel()[:n_cells]
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
        watertable_stack = None
        if surface_excess_stack is None:
            warn_on_geometric_seepage_fallback(grp, sim_id=sim_id)
            derived_grp = grp.get("derived")
            if derived_grp is not None and "watertable_elevation" in derived_grp:
                watertable_stack = np.asarray(
                    derived_grp["watertable_elevation"][:], dtype="float64"
                )
            elif "head" in grp:
                watertable_stack = _watertable_stack_from_head(
                    np.asarray(grp["head"][:], dtype="float64")
                )
            else:
                logger.debug("watertable_elevation missing, skipping seepage for sim %s", sim_id)
                return

    if surface_excess_stack is not None:
        excess = _positive_cell_flux_stack(surface_excess_stack[:n_timesteps], n_cells=n_cells)
        wt = None
    else:
        excess = None
        wt = watertable_stack.reshape(watertable_stack.shape[0], -1)[:n_timesteps, :n_cells]
    seepage = seepage_mask(watertable=wt, topography=top_elev, surface_excess=excess)
    store.write_field_stack(sim_id, "seepage_mask", seepage, subgroup="derived")

    logger.debug("Derived seepage_mask for sim %s", sim_id)


def _watertable_stack_from_head(head_stack: np.ndarray) -> np.ndarray:
    """Water-table elevation per timestep: head at the uppermost finite layer."""
    if head_stack.ndim == 2:
        return head_stack.astype("float64", copy=True)
    n_timesteps, n_layers, n_cells = head_stack.shape
    wt = np.full((n_timesteps, n_cells), np.nan, dtype="float64")
    for layer in range(n_layers):
        mask = np.isfinite(head_stack[:, layer]) & np.isnan(wt)
        wt[mask] = head_stack[:, layer][mask]
    return wt


# Canonical public name of the DRN-TO-MVR budget record (see
# solver.modflow_common.budget_components.canonical_budget_component).
_DRN_TO_MVR_KEYS = ("drain_to_mover",)


def _drn_raw_stack_with_mvr(budget_grp: Any, drn_key: str | None, n_timesteps: int) -> Any:
    """DRN budget stack summed with the DRN-TO-MVR record (same sign convention).

    With ``route_drainage``, the in-watershed drain flux lives in the DRN-TO-MVR
    record, not the plain DRN one, so the derived spatial fields must include
    both to show catchment drainage rather than only the buffer. Returns None
    when neither record is present.
    """
    stacks: list[np.ndarray] = []
    if drn_key is not None:
        stacks.append(np.asarray(budget_grp[drn_key][:], dtype="float64")[:n_timesteps])
    for mvr_key in _DRN_TO_MVR_KEYS:
        if mvr_key in budget_grp:
            stacks.append(np.asarray(budget_grp[mvr_key][:], dtype="float64")[:n_timesteps])
            break
    if not stacks:
        return None
    base = stacks[0]
    for extra in stacks[1:]:
        if extra.shape == base.shape:
            base = base + extra
    return base


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

        if int(n_timesteps) <= 0:
            return np.empty((0, int(n_cells)), dtype="float64")
        drn_key = find_drain_budget_key(budget_grp)
        drn_stack = _drn_raw_stack_with_mvr(budget_grp, drn_key, n_timesteps)
        if drn_stack is None:
            raise KeyError("No DRN or DRN-TO-MVR budget field")
    return drain_budget_stack_to_positive_outflow(drn_stack, n_cells=n_cells)


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
        raise _budget_dependency_error("accumulation_flux", sim_id, exc) from exc

    _route_cell_flux_stack_with_fallback(
        sim_id,
        store,
        drain_stack,
        "accumulation_flux",
        n_timesteps,
        n_cells,
        local_label="local drain outflow",
    )


def _positive_cell_flux_stack(component_stack: Any, *, n_cells: int) -> np.ndarray:
    """Return positive per-cell volumetric outflow from a ``(time, ...)`` stack."""
    stack = np.asarray(component_stack, dtype=float)
    if stack.size == 0:
        return np.zeros((stack.shape[0] if stack.ndim else 0, int(n_cells)), dtype="float64")
    if stack.ndim == 2:
        stack = stack[:, None, :]
    per_step = int(np.prod(stack.shape[1:]))
    if per_step % int(n_cells) == 0:
        values = stack.reshape(stack.shape[0], -1, int(n_cells))
    else:
        values = stack.reshape(stack.shape[0], stack.shape[1], -1)
    if values.shape[-1] != int(n_cells):
        raise ValueError(
            f"Budget component has {values.shape[-1]} cells after reshape; expected {n_cells}."
        )
    finite = np.isfinite(values) & (values > -9000.0)
    positive = np.where(finite, np.maximum(values, 0.0), 0.0)
    return positive.sum(axis=1).astype("float64", copy=False)


#: Persisted budget components that carry groundwater OUT of the aquifer to the
#: surface, beside the drain, each with the sign a value takes when it LEAVES.
#:
#: The two conventions really do meet here. MODFLOW signs a budget from the
#: aquifer's point of view, so ``stream`` (SFR) and ``lake`` (LAK) are negative
#: when the aquifer loses water. The Boussinesq ``surface_excess`` is already an
#: outflow and is positive. Reading them all with one clamp silently dropped
#: whichever half had the other sign, which is how a run with its streams in SFR
#: reported the drain alone.
_SURFACE_RELEASE_BUDGETS: dict[str, float] = {
    "stream": -1.0,
    "lake": -1.0,
    "surface_excess": 1.0,
}


def _release_flux_stack(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> np.ndarray:
    """Sum every path groundwater takes out of the aquifer, as a solver-neutral stack.

    Every path, not the drain alone. A run whose streams are in SFR sends most
    of its water through the stream package: measured on the Nancon, 1.3276 of
    the 2.1018 m3/s left through ``stream`` and 0.7986 through ``drain``, and a
    ``release_flux`` holding the drain alone reported dry land over 63 per cent
    of the outgoing water, exactly where a stream-network criterion aims.

    This union is not the calibration criterion's, and it differs in both
    directions. Persisted here: the drain and DRN-TO-MVR, plus ``stream``
    (SFR), ``lake`` (LAK) and the Boussinesq ``surface_excess``. Read off the
    binary budget by the calibration extractor: DRN, DRN-TO-MVR, SFR and a CHD
    restricted to its stream-role cells. So a lake enters this field and never
    the criterion, and a stream-role constant head enters the criterion and
    never this field.

    The two cannot become one declaration as they stand. A persisted
    ``constant_head`` component carries no role, so adding it here would count
    every constant head the run declares, an ocean or a lateral boundary
    included, as groundwater released to the surface. And ``simulation`` may
    not import ``solver``, so this list cannot read the criterion's; the
    reverse edge is allowed, so a shared declaration would have to live below
    both. Scoring this field against a mapped network therefore measures a
    neighbouring quantity, not the one the criterion balanced.
    """
    with _zarr_root(store, sim_id) as grp:
        budget_grp = grp.get("budget")
        if budget_grp is None:
            raise KeyError("No budget fields")

        drn_key = find_drain_budget_key(budget_grp)
        extra = [name for name in _SURFACE_RELEASE_BUDGETS if name in budget_grp]
        if drn_key is None and not extra:
            raise KeyError(
                "No release budget field: expected a drain component or one of "
                f"{sorted(_SURFACE_RELEASE_BUDGETS)}."
            )

        if int(n_timesteps) <= 0:
            return np.empty((0, int(n_cells)), dtype="float64")
        release = np.zeros((int(n_timesteps), int(n_cells)), dtype="float64")
        drn_stack = _drn_raw_stack_with_mvr(budget_grp, drn_key, n_timesteps)
        if drn_stack is not None:
            release += drain_budget_stack_to_positive_outflow(drn_stack, n_cells=n_cells)
        for name in extra:
            stack = np.asarray(budget_grp[name][:], dtype="float64")
            outward = stack[:n_timesteps] * _SURFACE_RELEASE_BUDGETS[name]
            release += _positive_cell_flux_stack(outward, n_cells=n_cells)
    return release


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
        raise _budget_dependency_error("release_flux", sim_id, exc) from exc

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
        raise ValueError(
            f"derived/{variable} has {stack.shape[0]} timesteps, expected {n_timesteps}."
        )
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

    stack = np.maximum(values[:n_timesteps], 0.0)
    stack = np.where(np.isfinite(stack), stack, 0.0).astype("float64", copy=False)
    store.write_field_stack(sim_id, variable, stack, subgroup="derived")


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
    except (KeyError, ValueError) as exc:
        raise _budget_dependency_error("release_accumulation_flux", sim_id, exc) from exc

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
        if mesh is None or "topography" not in mesh:
            raise KeyError("No mesh/topography for routing")
        topography = np.asarray(mesh["topography"][:], dtype="float64")
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

        dem_2d = topography.reshape(grid_shape)
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

        acc_stack = np.empty((int(n_timesteps), int(n_cells)), dtype="float64")
        for t in progress.track(range(int(n_timesteps)), "Routing surface flow"):
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
            acc_stack[t] = acc.ravel()

        store.write_field_stack(sim_id, output_variable, acc_stack, subgroup="derived")


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
        if mesh is None or "topography" not in mesh or "face_node_connectivity" not in mesh:
            raise KeyError("No mesh topology for graph routing")
        topography = np.asarray(mesh["topography"][:], dtype="float64").reshape(-1)[:n_cells]
        face_node_connectivity = np.asarray(mesh["face_node_connectivity"][:], dtype="int32")
        vertices = np.asarray(mesh["vertices"][:], dtype="float64") if "vertices" in mesh else None

    if topography.size != n_cells:
        raise ValueError(f"topography has {topography.size} cells, expected {n_cells}.")
    inactive = ~active_surface_mask(topography)

    # The receiver graph only depends on the static topography: build it once
    # and route every timestep through it in a single vectorized pass.
    graph = build_downhill_graph(
        topography,
        face_node_connectivity,
        vertices=vertices,
        inactive_mask=inactive,
    )
    local = np.maximum(np.asarray(local_stack, dtype="float64").reshape(int(n_timesteps), -1), 0.0)
    accumulation = accumulate_on_downhill_graph(graph, local)
    store.write_field_stack(
        sim_id,
        output_variable,
        accumulation.astype("float64", copy=False),
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
        raise _budget_dependency_error("outflow_drain", sim_id, exc) from exc

    _write_derived_stack(sim_id, store, "outflow_drain", drain_stack, n_timesteps, n_cells)
    logger.debug("Derived outflow_drain for sim %s", sim_id)


def _seepage_mask_stack(grp: Any, sim_id: str, n_timesteps: int, n_cells: int) -> np.ndarray:
    """Read or derive the full seepage-mask stack, mirroring the virtual field."""
    derived_grp = grp.get("derived")
    if derived_grp is not None and "seepage_mask" in derived_grp:
        stack = np.asarray(derived_grp["seepage_mask"][:], dtype="float64")
        return stack.reshape(stack.shape[0], -1)[:n_timesteps, :n_cells]

    budget_grp = grp.get("budget")
    if budget_grp is not None and "surface_excess" in budget_grp:
        excess = np.asarray(budget_grp["surface_excess"][:], dtype="float64")[:n_timesteps]
        flat = excess.reshape(excess.shape[0], -1)[:, :n_cells]
        return seepage_mask(surface_excess=flat)

    mesh = grp.get("mesh")
    if mesh is None or "head" not in grp:
        raise KeyError("seepage_mask unavailable")
    warn_on_geometric_seepage_fallback(grp, sim_id=sim_id)
    if "topography" in mesh:
        top = np.asarray(mesh["topography"][:], dtype="float64").reshape(-1)[:n_cells]
    elif "z_interfaces" in mesh:
        top = np.full(n_cells, float(mesh["z_interfaces"][:][0]), dtype="float64")
    else:
        raise KeyError("seepage_mask unavailable")
    wt = _watertable_stack_from_head(np.asarray(grp["head"][:], dtype="float64"))
    wt = wt[:n_timesteps, :n_cells]
    return seepage_mask(watertable=wt, topography=top)


def _compute_concentration_seepage(
    sim_id: str,
    store: Any,
    n_timesteps: int,
    n_cells: int,
) -> None:
    """Concentration at seepage cells only. Zero elsewhere."""
    with _zarr_root(store, sim_id) as grp:
        if "concentration" not in grp:
            _log_waiting_for_transport("concentration_seepage", sim_id)
            return

        try:
            seepage = _seepage_mask_stack(grp, sim_id, n_timesteps, n_cells)
        except KeyError as exc:
            raise _derived_dependency_error(
                "concentration_seepage", sim_id, "seepage_areas"
            ) from exc

        conc = np.asarray(grp["concentration"][:], dtype="float64")[:n_timesteps]
        if conc.ndim == 3:
            conc = conc[:, 0]
        result = np.where(seepage > 0, conc * seepage, np.nan)
    store.write_field_stack(
        sim_id,
        "concentration_seepage",
        result.astype("float64", copy=False),
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
            raise _budget_dependency_error("mass_seepage", sim_id, KeyError("No budget fields"))

        derived_grp = grp.get("derived")
        if derived_grp is None or "concentration_seepage" not in derived_grp:
            if "concentration" not in grp:
                _log_waiting_for_transport("mass_seepage", sim_id)
                return
            raise _derived_dependency_error("mass_seepage", sim_id, "concentration_seepage")
        conc_seep = np.asarray(derived_grp["concentration_seepage"][:], dtype="float64")
        conc_seep = conc_seep[:n_timesteps]

        drn_key = find_drain_budget_key(budget_grp)
        if drn_key is not None:
            drn_stack = np.asarray(budget_grp[drn_key][:], dtype="float64")[:n_timesteps]
            flux = drain_budget_stack_to_positive_outflow(drn_stack, n_cells=n_cells)
        else:
            flux = np.ones((int(n_timesteps), int(n_cells)), dtype="float64")

        mass = conc_seep * flux
    store.write_field_stack(
        sim_id,
        "mass_seepage",
        mass.astype("float64", copy=False),
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
    with _zarr_root(store, sim_id) as grp:
        derived_grp = grp.get("derived")
        if derived_grp is None or "mass_seepage" not in derived_grp:
            if "concentration" not in grp:
                _log_waiting_for_transport("mass_accumulated", sim_id)
                return
            raise _derived_dependency_error("mass_accumulated", sim_id, "mass_seepage")
        mass_seepage = np.asarray(derived_grp["mass_seepage"][:], dtype="float64")[:n_timesteps]

    store.write_field_stack(
        sim_id,
        "mass_accumulated",
        np.cumsum(mass_seepage, axis=0),
        subgroup="derived",
    )

    logger.debug("Derived mass_accumulated for sim %s", sim_id)
