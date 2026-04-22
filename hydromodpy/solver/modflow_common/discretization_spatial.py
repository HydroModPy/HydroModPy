"""Common spatial discretization builders for MODFLOW-family solvers."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.solver.modflow_common.grid_context import GridReference, SolverGridContext
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import (
    PlanarGridConfig,
    SolverSGridConfig,
    VerticalGridConfig,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler


def resolve_domain_surfaces(
    *,
    domain: object,
) -> tuple[Surface, Surface]:
    """Validate and return top/substratum surfaces used by spatial gridding."""
    if domain is None:
        raise ValueError("Modflow spatial geometry is domain-only: a Domain object is required.")

    surface_topo = getattr(domain, "surface_topo", None)
    substratum = getattr(domain, "substratum", None)
    if surface_topo is None or substratum is None:
        raise ValueError(
            "Modflow spatial geometry is domain-only: domain.surface_topo "
            "and domain.substratum are required."
        )
    if not isinstance(surface_topo, Surface) or not isinstance(substratum, Surface):
        raise TypeError("Domain surfaces must be Surface instances.")

    top = np.asarray(surface_topo.as_array(), dtype=float)
    bot = np.asarray(substratum.as_array(), dtype=float)
    if top.shape != bot.shape:
        raise ValueError(f"Domain surface mismatch: top{top.shape} != substratum{bot.shape}.")

    surface_topo.assert_same_geographic_domain(substratum)
    return surface_topo, substratum


def project_surfaces_to_planar_grid(
    *,
    top_surface: Surface,
    bottom_surface: Surface,
    planar_config: PlanarGridConfig | None,
    nodata: float,
) -> tuple[Surface, Surface]:
    """Project domain surfaces to the target solver planar grid when requested."""
    if planar_config is None or planar_config.mode == "keep_native":
        return top_surface, bottom_surface

    resampled_top = top_surface.resample_to_shape(
        int(planar_config.ny),
        int(planar_config.nx),
        resampling=str(planar_config.resampling),
        nodata=float(nodata),
        name=top_surface.name,
    )
    resampled_bottom = bottom_surface.resample_to_shape(
        int(planar_config.ny),
        int(planar_config.nx),
        resampling=str(planar_config.resampling),
        nodata=float(nodata),
        name=bottom_surface.name,
    )
    resampled_top.assert_same_geographic_domain(resampled_bottom)
    return resampled_top, resampled_bottom


def _coerce_vertical_config(
    vertical_config: VerticalGridConfig | Mapping[str, object] | None,
) -> VerticalGridConfig:
    if vertical_config is None:
        return VerticalGridConfig()
    if isinstance(vertical_config, VerticalGridConfig):
        return vertical_config
    if isinstance(vertical_config, Mapping):
        return VerticalGridConfig.from_mapping(vertical_config)
    raise TypeError("vertical_config must be None, VerticalGridConfig, or a mapping of values.")


def _compute_layer_proportions(
    *,
    genmtd_lay: str,
    nlay: int | None,
    lay_decay: float | None,
    lay_proportions: list[float] | None,
) -> tuple[np.ndarray, int]:
    if genmtd_lay == "list":
        arr = np.asarray(lay_proportions, dtype=float)
        return np.cumsum(arr), int(arr.size)
    if genmtd_lay == "constant":
        nlay_int = int(nlay)
        return np.arange(1, nlay_int + 1, dtype=float) / nlay_int, nlay_int
    if genmtd_lay == "decay":
        nlay_int = int(nlay)
        decay = float(lay_decay)
        idx = np.arange(1, nlay_int + 1, dtype=float)
        allp = (1 - decay**idx) / (1 - decay**nlay_int)
        return allp, nlay_int
    raise ValueError(f"Unsupported genmtd_lay '{genmtd_lay}'. Allowed: list, constant, decay.")


def _assert_bottom_below_top(
    *,
    top: np.ndarray,
    bot: np.ndarray,
    nodata: float,
) -> None:
    valid = np.isfinite(top) & np.isfinite(bot) & (top > float(nodata)) & (bot > float(nodata))
    if not np.any(valid):
        raise ValueError("No finite overlapping valid cells found between top and bottom surfaces.")
    violations = bot[valid] >= top[valid]
    if np.any(violations):
        n_bad = int(np.count_nonzero(violations))
        total = int(violations.size)
        max_delta = float(np.max(bot[valid] - top[valid]))
        raise ValueError(
            "Bottom surface must be strictly below top surface on valid cells "
            f"({n_bad}/{total} violations, max(bot-top)={max_delta:.6g})."
        )


def _build_extruded_solver_mesh_from_runtime_planar(
    *,
    planar_mesh: object,
    top_surface: Surface,
    bottom_surface: Surface,
    vertical_config: VerticalGridConfig | None,
    nodata: float,
) -> SolverMesh:
    mesh_2d = planar_mesh
    hydro_mesh = (
        planar_mesh.to_hydro_mesh() if hasattr(planar_mesh, "to_hydro_mesh") else planar_mesh
    )

    x_centers, y_centers = mesh_2d.cell_centroids()
    top_sampler = PreparedSurfaceSampler.from_surface(top_surface)
    bottom_sampler = PreparedSurfaceSampler.from_surface(bottom_surface)
    top_flat = np.asarray(top_sampler.sample(x_centers, y_centers), dtype=float).reshape(-1)
    bottom_flat = np.asarray(bottom_sampler.sample(x_centers, y_centers), dtype=float).reshape(-1)

    cfg = _coerce_vertical_config(vertical_config)
    invalid = (
        ~np.isfinite(top_flat)
        | ~np.isfinite(bottom_flat)
        | (top_flat <= float(nodata))
        | (bottom_flat <= float(nodata))
    )
    top_flat = np.where(invalid, float(nodata), top_flat)
    bottom_flat = np.where(invalid, float(nodata), bottom_flat)
    _assert_bottom_below_top(top=top_flat, bot=bottom_flat, nodata=nodata)

    allp, nlay = _compute_layer_proportions(
        genmtd_lay=cfg.genmtd_lay,
        nlay=cfg.nlay,
        lay_decay=cfg.lay_decay,
        lay_proportions=cfg.lay_proportions,
    )
    botm = top_flat[None, :] - ((top_flat - bottom_flat)[None, :] * allp[:, None])
    botm[:, invalid] = float(nodata)
    inactive_mask = np.tile(invalid.reshape(1, -1), (nlay, 1))
    return SolverMesh(
        planar_mesh=hydro_mesh,
        top=top_flat,
        botm=botm,
        inactive_mask=inactive_mask,
    )


def build_spatial_discretization(
    *,
    domain: object,
    sgrid_config: SolverSGridConfig | None,
    runtime_planar_mesh: object | None = None,
    runtime_mesh_support: object | None = None,
) -> SolverGridContext:
    """Build normalized spatial discretization from domain surfaces or runtime mesh."""
    del runtime_mesh_support

    vertical_config: VerticalGridConfig | None = None
    planar_config: PlanarGridConfig | None = None
    if sgrid_config is not None:
        vertical_config = sgrid_config.vertical
        planar_config = sgrid_config.planar

    nodata = float(vertical_config.nodata if vertical_config is not None else -9999.0)

    top_surface, bottom_surface = resolve_domain_surfaces(domain=domain)

    if runtime_planar_mesh is None:
        top_surface, bottom_surface = project_surfaces_to_planar_grid(
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            planar_config=planar_config,
            nodata=nodata,
        )
        top = np.asarray(top_surface.as_array(), dtype=float)
        bottom = np.asarray(bottom_surface.as_array(), dtype=float)
        sgrid = StructuredGridBuilder().build_from_surfaces(
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_config,
        )
        zbot = np.asarray(sgrid.botm, dtype=float)
        inactive_mask = (
            ~np.isfinite(top) | ~np.isfinite(bottom) | (top <= nodata) | (bottom <= nodata)
        )
        solver_mesh = SolverMesh.from_sgrid(
            sgrid,
            zbot=zbot,
            inactive_mask=np.asarray(inactive_mask, dtype=bool),
        )
    else:
        solver_mesh = _build_extruded_solver_mesh_from_runtime_planar(
            planar_mesh=runtime_planar_mesh,
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_config,
            nodata=nodata,
        )

    return SolverGridContext(
        grid=GridReference.from_solver_mesh(
            solver_mesh,
            crs=None if top_surface.support is None else getattr(top_surface.support, "crs", None),
            nodata=nodata,
        ),
        solver_mesh=solver_mesh,
        top_surface=top_surface,
        bottom_surface=bottom_surface,
    )


__all__ = [
    "build_spatial_discretization",
    "project_surfaces_to_planar_grid",
    "resolve_domain_surfaces",
]
