"""Common spatial discretization builders for MODFLOW-family solvers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.catchment.surface import Surface
from hydromodpy.catchment.surface_sampling import PreparedSurfaceSampler
from hydromodpy.core.fields.grid_reference import GridReference
from hydromodpy.core.logging import get_logger
from hydromodpy.model.domain.cell_column import (
    CellColumn,
    resample_to_mesh_shape,
    resolve_domain_surfaces,
)
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.layering import (
    assert_bottom_below_top,
    coerce_vertical_config,
    layer_stack,
)
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

if TYPE_CHECKING:
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh

__all__ = [
    "StructuredGridBuilder",
    "StructuredGridSpec",
    "build_spatial_discretization",
    "resolve_layer_bases",
    "SolverGridContext",
    "grid_reference_from_solver_mesh",
]

logger = get_logger(__name__)


def resolve_layer_bases(
    *,
    domain: Domain,
    vertical_config: VerticalGridConfig | None,
) -> dict[str, Surface]:
    """Return the base surfaces the layering reads, by name, from ``domain.layer_bases``.

    Only a layering by surfaces reads any. A name the domain does not hold is
    refused when the layers are built, with the names it holds.
    """
    names = () if vertical_config is None else vertical_config.base_surface_names
    held = getattr(domain, "layer_bases", None) or {}
    return {name: held[name] for name in names if name in held}


# A valid cell thicker than this multiple of the median, and thicker than the floor
# below, is reported. Both bounds are needed: the multiple alone fires on a legitimate
# variable-thickness substratum, the floor alone fires on a genuinely deep aquifer.
_THICKNESS_OUTLIER_FACTOR = 10.0

_THICKNESS_OUTLIER_FLOOR_M = 500.0


def _warn_on_outlier_thickness(*, top: np.ndarray, bot: np.ndarray, valid: np.ndarray) -> None:
    """Report aquifer columns far thicker than the rest of the mesh.

    A raster NODATA sentinel that reaches the sampler as an ordinary elevation is
    interpolated as if it were terrain, so a cell whose stencil straddles the mask
    edge ends up kilometers deep with a perfectly clean top and an active idomain.
    Nothing downstream notices: the model converges and its mass balance closes,
    while those cells carry a transmissivity and a storage several hundred times the
    nominal ones. This check does not change the mesh; it makes the symptom visible
    whatever its cause.
    """
    if not np.any(valid):
        return
    thickness = (top - bot)[valid]
    median = float(np.median(thickness))
    if median <= 0.0:
        return
    limit = max(_THICKNESS_OUTLIER_FACTOR * median, _THICKNESS_OUTLIER_FLOOR_M)
    outliers = thickness > limit
    if not np.any(outliers):
        return
    logger.warning(
        "Aquifer thickness outliers: %d of %d valid cells are thicker than %.4g m "
        "(median thickness %.4g m, worst %.4g m). A cell kilometres deep usually means a "
        "raster NODATA sentinel was sampled as an elevation; check the substratum raster "
        "and the domain extent.",
        int(np.count_nonzero(outliers)),
        int(thickness.size),
        limit,
        median,
        float(thickness.max()),
    )


def _build_extruded_solver_mesh_from_runtime_planar(
    *,
    cell_mesh: PlanarCellMesh,
    column: CellColumn,
    vertical_config: VerticalGridConfig | None,
    nodata: float,
    base_surfaces: dict[str, Surface] | None = None,
) -> SolverMesh:
    """Extrude an unstructured cell mesh: the column and the layer bases sampled at the cell centers."""
    x_centers, y_centers = cell_mesh.centers.T
    cfg = coerce_vertical_config(vertical_config)
    top_flat, bottom_flat = column.top, column.bottom

    invalid = (
        ~np.isfinite(top_flat)
        | ~np.isfinite(bottom_flat)
        | (top_flat <= float(nodata))
        | (bottom_flat <= float(nodata))
    )
    assert_bottom_below_top(top=top_flat, bot=bottom_flat, nodata=nodata)
    _warn_on_outlier_thickness(top=top_flat, bot=bottom_flat, valid=~invalid)

    bases = {
        name: np.asarray(
            PreparedSurfaceSampler.from_surface(surface).sample(x_centers, y_centers), dtype=float
        ).reshape(-1)
        for name, surface in (base_surfaces or {}).items()
    }
    stack = layer_stack(
        top=top_flat,
        bottom=bottom_flat,
        invalid=invalid,
        vertical_config=cfg,
        bases=bases,
        nodata=nodata,
    )
    return SolverMesh(cell_mesh=cell_mesh, top=top_flat, botm=stack.botm, idomain=stack.idomain)


@dataclass(frozen=True)
class StructuredGridSpec:
    """The vertical part of a structured grid: top, layer bottoms and ``idomain``.

    ``top`` has the shape of the surfaces, ``botm`` and ``idomain`` one more
    axis for the layers. ``idomain`` is 1 active, 0 outside the domain, -1 a
    pinched cell of a layering by surfaces.
    """

    top: np.ndarray
    botm: np.ndarray
    nlay: int
    idomain: np.ndarray


class StructuredGridBuilder:
    """Build the vertical part of a regular grid from two absolute-elevation surfaces.

    ``top_surface`` and ``bottom_surface`` are absolute altitudes in the same
    datum, and the builder never adds one to the other. The geometry is metric.
    The planar grid is not built here. It is the mesh of the regular engine, and
    ``Surface.resample_to_shape(...)`` resamples the surfaces to its shape
    beforehand. The builder checks that the surfaces describe the same domain,
    asks :func:`hydromodpy.model.domain.layering.layer_stack`, which the
    unstructured extrusion calls too, for the layer bottoms and the ``idomain``,
    and returns them with the top in a :class:`StructuredGridSpec`.
    """

    def __init__(self):
        # No hidden state: deterministic transformations only.
        pass

    def build_from_surfaces(
        self,
        top_surface: Surface,
        bottom_surface: Surface,
        vertical_config: VerticalGridConfig | Mapping[str, object] | None = None,
        base_surfaces: Mapping[str, Surface] | None = None,
    ) -> StructuredGridSpec:
        """
        Build one structured grid from two absolute-elevation surfaces.

        The method intentionally separates three steps:
        1. Validate horizontal/geometric compatibility of inputs.
        2. Build `botm` and `idomain` with :func:`layer_stack`.
        3. Return a `StructuredGridSpec`.

        ``base_surfaces`` holds the layer bases a layering by surfaces reads, on
        the grid of ``top_surface``.
        """
        cfg = coerce_vertical_config(vertical_config)

        # 1) Horizontal compatibility checks.
        #    "Same geographic domain" means same CRS + same spatial extent.
        top_surface.assert_same_geographic_domain(bottom_surface)

        support = top_surface.support
        if support is None:
            raise ValueError("Top surface must carry a RasterSupport.")
        support.assert_complete_domain()

        top = np.asarray(top_surface.as_array(), dtype=float)
        bot = np.asarray(bottom_surface.as_array(), dtype=float)
        if top.shape != bot.shape:
            raise ValueError(
                "top_surface and bottom_surface must have the same discretization "
                f"before vertical grid construction: top{top.shape} != bottom{bot.shape}. "
                "Use Surface.resample_to_shape(...) beforehand."
            )

        nodata = float(cfg.nodata)

        # Mask invalid cells consistently in both surfaces.
        invalid = ~np.isfinite(top) | ~np.isfinite(bot) | (top <= nodata) | (bot <= nodata)
        top = np.array(top, dtype=float, copy=True)
        bot = np.array(bot, dtype=float, copy=True)
        top[invalid] = nodata
        bot[invalid] = nodata

        assert_bottom_below_top(top=top, bot=bot, nodata=nodata)

        # 2) Layer bottoms and idomain from config.
        bases = {}
        for name, surface in (base_surfaces or {}).items():
            values = np.asarray(surface.as_array(), dtype=float)
            if values.shape != top.shape:
                raise ValueError(
                    f"The layer base {name!r} has shape {values.shape}, the top {top.shape}."
                )
            bases[name] = values
        stack = layer_stack(
            top=top, bottom=bot, invalid=invalid, vertical_config=cfg, bases=bases, nodata=nodata
        )

        # The planar grid is the mesh's, the steps of the support are only checked.
        width = float(support.xmax) - float(support.xmin)
        height = float(support.ymax) - float(support.ymin)
        dx = float(support.dx) if support.dx is not None else width / int(support.ncols)
        dy = float(support.dy) if support.dy is not None else height / int(support.nrows)
        if dx <= 0 or dy <= 0:
            raise ValueError(f"Invalid support cell sizes: dx={dx}, dy={dy}.")

        return StructuredGridSpec(
            top=top,
            botm=stack.botm,
            nlay=int(stack.botm.shape[0]),
            idomain=stack.idomain,
        )


def _build_structured_solver_mesh(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    bottom_surface: Surface,
    vertical_config: VerticalGridConfig | None,
    nodata: float,
    column: CellColumn,
    base_surfaces: dict[str, Surface] | None = None,
) -> tuple[SolverMesh, Surface, Surface]:
    """Extrude a regular mesh on its column, with the layer bases resampled to its shape.

    The planar grid is the mesh's. The column gives the top and the bottom, the surfaces
    give the layer bases and the support. Returns the solver mesh and the top and bottom
    surfaces at the resolution of the mesh.
    """
    nrow, ncol = cell_mesh.structured_shape
    base_surfaces = dict(base_surfaces or {})
    if np.asarray(top_surface.as_array()).shape != (nrow, ncol):
        top_surface = resample_to_mesh_shape(top_surface, cell_mesh, nodata)
        bottom_surface = resample_to_mesh_shape(bottom_surface, cell_mesh, nodata)
        base_surfaces = {
            name: resample_to_mesh_shape(surface, cell_mesh, nodata)
            for name, surface in base_surfaces.items()
        }
    top_surface = Surface(
        name=top_surface.name, values=column.top.reshape(nrow, ncol), support=top_surface.support
    )
    bottom_surface = Surface(
        name=bottom_surface.name,
        values=column.bottom.reshape(nrow, ncol),
        support=bottom_surface.support,
    )

    # The builder gives the vertical part only, the planar grid is the mesh's.
    spec = StructuredGridBuilder().build_from_surfaces(
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        vertical_config=vertical_config,
        base_surfaces=base_surfaces,
    )
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=spec.top.reshape(-1),
        botm=spec.botm.reshape(spec.nlay, -1),
        idomain=spec.idomain.reshape(spec.nlay, -1),
    )
    return solver_mesh, top_surface, bottom_surface


def build_spatial_discretization(
    *,
    domain: Domain,
    vertical_config: VerticalGridConfig | None,
    cell_mesh: PlanarCellMesh,
    column: CellColumn,
) -> SolverGridContext:
    """Extrude a planar cell mesh on its column into the solver grid.

    The planar part is ``cell_mesh``: a regular grid (``structured_shape`` set) or
    any unstructured one. The top and the bottom are ``column``, which
    ``modflow_column`` builds from ``domain.surface_topo`` and ``domain.substratum`` at
    ``prepare_solver``. This function adds the layers of ``vertical_config``, the
    ``[domain.layers]`` table that every solver reads; a layering by surfaces also reads
    ``domain.layer_bases``, and its pinched cells get ``idomain`` -1. A regular mesh whose
    shape differs from the surfaces gets the layer bases resampled to it.

    The interfaces are checked once built: an active cell with a top at or
    below its bottom raises. The solver warns about active cells in more than one
    connected group once its grid is final (``active_connectivity``).
    """
    nodata = float(vertical_config.nodata if vertical_config is not None else -9999.0)

    top_surface, bottom_surface = resolve_domain_surfaces(domain=domain)
    base_surfaces = resolve_layer_bases(domain=domain, vertical_config=vertical_config)

    if cell_mesh.structured_shape is not None:
        solver_mesh, top_surface, bottom_surface = _build_structured_solver_mesh(
            cell_mesh=cell_mesh,
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_config,
            nodata=nodata,
            column=column,
            base_surfaces=base_surfaces,
        )
    else:
        solver_mesh = _build_extruded_solver_mesh_from_runtime_planar(
            cell_mesh=cell_mesh,
            column=column,
            vertical_config=vertical_config,
            nodata=nodata,
            base_surfaces=base_surfaces,
        )
    solver_mesh.check_interfaces()

    return SolverGridContext(
        grid=grid_reference_from_solver_mesh(
            solver_mesh,
            crs=None if top_surface.support is None else getattr(top_surface.support, "crs", None),
            nodata=nodata,
        ),
        solver_mesh=solver_mesh,
        top_surface=top_surface,
        bottom_surface=bottom_surface,
    )


def grid_reference_from_solver_mesh(
    solver_mesh: SolverMesh,
    *,
    crs: str | None = None,
    nodata: float = -9999.0,
) -> GridReference:
    """Build a GridReference from a SolverMesh."""
    mesh_bounds = solver_mesh.planar_mesh.bounds()
    xmin, ymin = float(mesh_bounds[0]), float(mesh_bounds[1])
    xmax, ymax = float(mesh_bounds[2]), float(mesh_bounds[3])
    return GridReference(
        n_cells=solver_mesh.n_cells,
        bounds=(xmin, ymin, xmax, ymax),
        crs=crs,
        nodata=float(nodata),
        structured_shape=solver_mesh.structured_shape,
        cell_size_hint=float(solver_mesh.characteristic_length),
    )


@dataclass(slots=True)
class SolverGridContext:
    """Runtime bundle for one solver grid (structured or unstructured)."""

    grid: GridReference
    solver_mesh: SolverMesh
    top_surface: Surface
    bottom_surface: Surface
    template_raster_path: str | None = None

    @property
    def top_elevation(self) -> np.ndarray:
        """Top elevation as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.top, dtype=float)

    @property
    def bottom_layer(self) -> np.ndarray:
        """Bottom elevation of deepest layer as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.botm[-1], dtype=float)

    @property
    def nlay(self) -> int:
        return self.solver_mesh.nlay

    @property
    def n_cells(self) -> int:
        return self.solver_mesh.n_cells

    @property
    def is_structured(self) -> bool:
        return self.solver_mesh.is_structured

    @property
    def nrow(self) -> int:
        return self.solver_mesh.nrow

    @property
    def ncol(self) -> int:
        return self.solver_mesh.ncol
