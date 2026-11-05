"""Planar cell meshes of the unit square, for the square-domain field demos.

``structured`` is a regular grid of quadrilaterals, row 0 south
(``cell_mesh_from_edges``). The two triangular kinds are the Delaunay
triangulations of a regular node grid and of a random node cloud, with their
vertex means as cell centers.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.tri as mtri
import numpy as np

from hydromodpy.core.state.rng import RngManager
from hydromodpy.spatial.field.field_spatial import get_nested_section
from hydromodpy.spatial.field.mesh_cells import cell_mesh_from_edges
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

SUPPORTED_MESH_KINDS = (
    "structured",
    "triangular_structured",
    "triangular_unstructured",
)

_UNSTRUCTURED_RNG_LABEL = "spatial.field.square.unstructured_points"
_DEFAULT_UNSTRUCTURED_SEED = 42

UNIT_SQUARE_CRS_WKT = (
    'ENGCRS["unit square",EDATUM["unit square"],CS[Cartesian,2],'
    'AXIS["x",east],AXIS["y",north],LENGTHUNIT["metre",1]]'
)
"""The local engineering CRS of the unit square demos."""

_ENGINE_VERSION = "1.0.0"


def _unit_square_edges(n_grid: int) -> np.ndarray:
    # ``_axis_points_from_target_cells`` gives at least 3 points per axis.
    return np.linspace(0.0, 1.0, int(n_grid), dtype=float)


def _axis_points_from_target_cells(target_n_cells: int, *, mesh_kind: str):
    target = max(1, int(target_n_cells))
    if mesh_kind == "structured":
        base = float(target)
    else:
        # Triangular mesh: n_triangles ~= 2*(n_axis-1)^2
        base = float(target) / 2.0
    return max(3, int(np.round(np.sqrt(base))) + 1)


def _build_unstructured_boundary(n_per_edge: int):
    edge = np.linspace(0.0, 1.0, n_per_edge, dtype=float)
    xb = np.concatenate(
        [
            edge,
            np.ones(n_per_edge - 1, dtype=float),
            edge[-2::-1],
            np.zeros(n_per_edge - 2, dtype=float),
        ]
    )
    yb = np.concatenate(
        [
            np.zeros(n_per_edge, dtype=float),
            edge[1:],
            np.ones(n_per_edge - 1, dtype=float),
            edge[-2:0:-1],
        ]
    )
    return xb, yb


def _build_unstructured_points(target_n_cells: int, *, rng: np.random.Generator):
    target = max(8, int(target_n_cells))
    n_per_edge = max(3, int(np.ceil(np.sqrt(float(target)) / 2.0)) + 1)
    xb, yb = _build_unstructured_boundary(n_per_edge)
    n_boundary = int(xb.size)

    # Planar triangulation heuristic: n_triangles ~= 2*n_points - 2 - n_boundary.
    # The boundary holds at most 2*sqrt(target) + 4 nodes, so from target = 8
    # at least one node is drawn inside.
    n_interior = int(np.ceil((float(target) - float(n_boundary) + 2.0) / 2.0))
    xi = rng.uniform(1e-6, 1.0 - 1e-6, size=n_interior)
    yi = rng.uniform(1e-6, 1.0 - 1e-6, size=n_interior)
    return np.concatenate([xb, xi]), np.concatenate([yb, yi])


def _resolve_unstructured_rng(
    rng_manager: RngManager | None,
) -> tuple[np.random.Generator, int]:
    """Return ``(rng, seed)`` for the unstructured-points generator.

    With a manager: seed is derived from ``master_seed`` via blake2b.
    Without a manager: the default seed ``42`` keeps existing fixtures
    deterministic.
    """
    if rng_manager is None:
        return np.random.default_rng(_DEFAULT_UNSTRUCTURED_SEED), _DEFAULT_UNSTRUCTURED_SEED
    seed = rng_manager.child_seed(_UNSTRUCTURED_RNG_LABEL)
    return np.random.default_rng(seed), seed


def _triangle_cell_mesh(
    triangulation: mtri.Triangulation, *, mesh_kind: str, seed: int | None
) -> PlanarCellMesh:
    """Wrap a matplotlib triangulation, its vertex means as cell centers."""
    vertices = np.column_stack((triangulation.x, triangulation.y))
    triangles = np.asarray(triangulation.triangles, dtype=int)
    return build_planar_cell_mesh(
        HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),)),
        vertices[triangles].mean(axis=1),
        center_kind="vertex_mean",
        crs_wkt=UNIT_SQUARE_CRS_WKT,
        identity=MeshIdentity(mesh_kind, _ENGINE_VERSION, "", seed),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
    )


class FieldMeshSquare:
    """Builder of the unit-square planar cell meshes of the field demos."""

    @classmethod
    def from_unit_square(
        cls,
        *,
        target_n_cells: int,
        mesh_kind: str = "structured",
        rng_manager: RngManager | None = None,
    ) -> PlanarCellMesh:
        """Build a unit-square mesh of about ``target_n_cells`` cells.

        ``rng_manager`` seeds the node cloud of ``triangular_unstructured``.
        Without one the seed is 42, so a test fixture stays the same.
        """
        kind_key = str(mesh_kind).strip().lower()
        target = max(1, int(target_n_cells))

        if kind_key == "structured":
            n_axis = _axis_points_from_target_cells(target, mesh_kind=kind_key)
            edges = _unit_square_edges(n_axis)
            return cell_mesh_from_edges(edges, edges, crs_wkt=UNIT_SQUARE_CRS_WKT)

        if kind_key == "triangular_structured":
            n_axis = _axis_points_from_target_cells(target, mesh_kind=kind_key)
            edges = _unit_square_edges(n_axis)
            x2d, y2d = np.meshgrid(edges, edges, indexing="xy")
            triang = mtri.Triangulation(x2d.ravel(), y2d.ravel())
            return _triangle_cell_mesh(triang, mesh_kind=kind_key, seed=None)

        if kind_key == "triangular_unstructured":
            rng, seed_used = _resolve_unstructured_rng(rng_manager)
            x, y = _build_unstructured_points(target, rng=rng)
            triang = mtri.Triangulation(x, y)
            return _triangle_cell_mesh(triang, mesh_kind=kind_key, seed=seed_used)

        allowed = ", ".join(SUPPORTED_MESH_KINDS)
        raise ValueError(f"Unsupported mesh kind '{mesh_kind}'. Allowed: {allowed}")

    @classmethod
    def from_dict(cls, config: Mapping[str, Any]) -> PlanarCellMesh:
        """Build one unit-square mesh from a plain mapping.

        The optional ``rng_seed`` (or ``seed``) entry in ``config`` seeds an
        ad-hoc :class:`RngManager`, so a TOML file stays self-contained when no
        master seed is available.
        """
        if not isinstance(config, Mapping):
            raise TypeError("config must be a mapping")
        mesh_kind = str(config.get("mesh_kind", config.get("kind", "structured")))

        target_n_cells = None
        for key in ("target_n_cells", "approx_n_cells", "target_cell_count"):
            if key in config:
                target_n_cells = int(config[key])
                break

        if target_n_cells is None:
            raise KeyError(
                "Mesh config requires 'target_n_cells' "
                "(aliases: 'approx_n_cells', 'target_cell_count')"
            )

        seed_value = config.get("rng_seed", config.get("seed"))
        rng_manager: RngManager | None = None
        if seed_value is not None:
            rng_manager = RngManager(master_seed=int(seed_value))

        return cls.from_unit_square(
            target_n_cells=target_n_cells,
            mesh_kind=mesh_kind,
            rng_manager=rng_manager,
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path, section: str = "mesh") -> PlanarCellMesh:
        """Build one unit-square mesh from a TOML section, through ``from_dict``."""
        path = Path(toml_path).resolve()
        with path.open("rb") as stream:
            payload = tomllib.load(stream)
        return cls.from_dict(get_nested_section(payload, section))
