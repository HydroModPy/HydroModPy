"""The ``[mesh]`` section: which engine meshes the model and how fine.

User keys are sizes in metres, a path, or an intention per line family. Every
algorithm setting is a DEV key with a fixed default. Without ``[mesh]`` the
``regular`` engine meshes the model with the DEM pixels. Every number of the
mesh tables must be finite, since the planner and the engines read the sizes
as they are.

A cell size is the side of the square of the same mean area as the cells, for
every engine and every size of the size field (``cell_size``,
``river_cell_size``, the refinement zones, the lake sizes, the gap sizes). A
domain of area ``A`` meshed at a uniform size ``l`` gets about ``A / l^2``
cells, whether its cells are squares, triangles or Voronoi polygons.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyPath, PositiveInt, StripLower
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.spatial.mesh.refinement_config import LakeRefinementConfig, RefinementZoneConfig

__all__ = [
    "MeshConfig",
    "MeshFamiliesConfig",
    "MeshRegularConfig",
    "MeshTriangleConfig",
    "MeshVoronoiConfig",
]

_TRIANGULATED_ENGINES = ("triangle", "voronoi")
"""The engines that start from a triangulation and read ``[mesh.triangle]``."""


class MeshFamiliesConfig(HydroModelBase):
    """What the mesh does on each family of lines."""

    rivers: Annotated[Literal["cell", "none"], StripLower, Profile.USER] = Field(
        default="cell",
        description="How the mesh follows the river network traced from the DEM.",
        json_schema_extra={
            "value_docs": {
                "cell": (
                    "The cells along each river form an ordered chain, from upstream "
                    "to downstream; the river size applies along it."
                ),
                "none": "The mesh ignores the rivers.",
            }
        },
    )
    geology: Annotated[Literal["face", "none"], StripLower, Profile.USER] = Field(
        default="face",
        description=(
            "How the mesh follows the contacts between the zones of the vector geology "
            "map that a flow parameter reads."
        ),
        json_schema_extra={
            "value_docs": {
                "face": "Cell faces lie on the contacts between geology zones.",
                "none": "The mesh ignores the geology contacts.",
            }
        },
    )
    lakes: Annotated[Literal["face", "none"], StripLower, Profile.USER] = Field(
        default="face",
        description="How the mesh follows the shore of each lake of the flow model.",
        json_schema_extra={
            "value_docs": {
                "face": "Cell faces lie on the lake shores.",
                "none": "The mesh ignores the lake shores.",
            }
        },
    )
    barriers: Annotated[Literal["face", "none"], StripLower, Profile.USER] = Field(
        default="face",
        description=(
            "How the mesh follows the flow barriers: the cutoff wall of each lake that "
            "declares one, and the lines of [flow.sinks_sources.flow_barriers]."
        ),
        json_schema_extra={
            "value_docs": {
                "face": (
                    "Cell faces lie on each barrier line, wings and free ends included, and "
                    "the HFB rows go on them. The regular engine takes the staircase of "
                    "faces the line crosses."
                ),
                "none": (
                    "The mesh ignores the barriers; the HFB rows go on the faces each line crosses."
                ),
            }
        },
    )
    watershed_boundary: Annotated[Literal["none", "face"], StripLower, Profile.USER] = Field(
        default="none",
        description="How the mesh follows the boundary of the catchment inside the domain.",
        json_schema_extra={
            "value_docs": {
                "none": "The mesh ignores the catchment boundary.",
                "face": "Cell faces lie on the catchment boundary.",
            }
        },
    )


class MeshTriangleConfig(HydroModelBase):
    """The triangulation the ``triangle`` engine generates, or the file both engines read."""

    path: Annotated[NonEmptyPath | None, Profile.USER] = Field(
        default=None,
        description=(
            "Existing gmsh .msh file (format 2.2) to read instead of generating a "
            "triangulation, relative to the project root (the folder of project.toml). "
            "The line families are derived on the mesh read."
        ),
        examples=["mesh/catchment.msh"],
    )
    algorithm: Annotated[Literal["delaunay", "frontal", "meshadapt"], StripLower, Profile.DEV] = (
        Field(
            default="delaunay",
            description=(
                "Two-dimensional gmsh algorithm that generates the triangles of the triangle "
                "engine. The voronoi engine does not triangulate and ignores it."
            ),
            json_schema_extra={
                "value_docs": {
                    "delaunay": "Gmsh Delaunay (algorithm 5): fast and robust.",
                    "frontal": "Gmsh frontal-Delaunay (algorithm 6): better shaped triangles.",
                    "meshadapt": "Gmsh MeshAdapt (algorithm 1): for complex curved boundaries.",
                }
            },
        )
    )


class MeshVoronoiConfig(HydroModelBase):
    """Settings of the ``voronoi`` engine."""

    model_config = ConfigDict(allow_inf_nan=False)

    seeds: Annotated[Literal["generated", "triangulation"] | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Where the generators of the Voronoi cells come from. Unset, they are the "
            "vertices of the triangulation read from [mesh.triangle] path when a path "
            "is given, and generated by the engine otherwise."
        ),
        json_schema_extra={
            "value_docs": {
                "generated": (
                    "The engine places the generators itself: along the rivers, in mirror "
                    "pairs on the face lines, on the boundary, and freely from the size field."
                ),
                "triangulation": (
                    "The vertices of the triangulation read from [mesh.triangle] path "
                    "are the generators."
                ),
            }
        },
    )
    lloyd_tolerance: Annotated[float, Profile.DEV] = Field(
        default=0.01,
        gt=0.0,
        description=(
            "Stop of the Lloyd relaxation of the generated generators: the root mean "
            "square of the displacements of the free generators in one iteration, as a "
            "share of their local cell size. The relaxation also stops after 25 "
            "iterations, and the mesh QA reports whether the tolerance was reached and "
            "the largest displacement."
        ),
        json_schema_extra={"unit": "-"},
    )


class MeshRegularConfig(HydroModelBase):
    """A regular grid given by its shape rather than by a cell size."""

    shape: Annotated[tuple[PositiveInt, PositiveInt], Profile.DEV] = Field(
        description=(
            "Number of rows and columns [nrow, ncol] of the grid over the DEM extent; "
            "the cells are rectangular when the extent is not square."
        ),
        examples=[[60, 60]],
        json_schema_extra={"unit": "cells"},
    )


class MeshConfig(HydroModelBase):
    """The mesh engine and the sizes it meshes the model with."""

    model_config = ConfigDict(allow_inf_nan=False)

    engine: Annotated[str, Profile.USER] = Field(
        default="regular",
        description=(
            "Mesh engine: 'regular' (one quadrilateral cell per DEM pixel, or per "
            "cell_size), 'triangle' (triangles that follow the lines) or 'voronoi' "
            "(polygons around generators). A string and not a closed choice, since an "
            "installed third-party engine is named the same way."
        ),
        examples=["regular", "triangle", "voronoi"],
    )
    cell_size: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Cell size in metres, the side of the square of the same mean area as the "
            "cells, whatever the engine: a domain of area A gets about A / cell_size^2 "
            "cells, and a regular, a triangle and a voronoi cell of this size have about "
            "the same area. It is the side of the regular grid cells and the background "
            "size of the triangle and voronoi engines. Unset, the DEM pixel size, which is "
            "the pixel of geographic.catchment.dem_resolution when that key is set, else "
            "the pixel of the DEM file. It is the last of the three sizes and reads none "
            "of them back: it changes the cells and not the surface that was delineated."
        ),
        json_schema_extra={"unit": "m"},
    )
    river_cell_size: Annotated[
        float | None, Profile.USER, VisibleWhen("engine", _TRIANGULATED_ENGINES)
    ] = Field(
        default=None,
        gt=0.0,
        description=(
            "Cell size in metres along the rivers, the side of the square of the same "
            "mean area as the cells, as cell_size. Unset, the DEM pixel size; never "
            "finer than the DEM pixel."
        ),
        json_schema_extra={"unit": "m"},
    )
    river_band: Annotated[
        float | None, Profile.USER, VisibleWhen("engine", _TRIANGULATED_ENGINES)
    ] = Field(
        default=None,
        gt=0.0,
        description=(
            "Distance in metres from a river over which the cell size grows back to "
            "cell_size. Unset, twice cell_size."
        ),
        json_schema_extra={"unit": "m"},
    )
    refinement_zone: Annotated[list[RefinementZoneConfig], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Zones of local refinement, one [[mesh.refinement_zone]] table each, with its "
            "own cell size, which has the meaning of cell_size: a vector layer, or the "
            "pixels where a field passes a threshold (the height above the stream traced "
            "from the DEM, or the water-table depth or the seepage of an earlier run). The "
            "triangle and voronoi engines grade their cells on them; the regular engine "
            "does not grade its cells and ignores them, which the mesh QA notes."
        ),
    )
    lake_refinement: Annotated[LakeRefinementConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Local refinement on the lake shoreline band and the hydraulic structures "
            "(cutoff wall, sill, dam outlet), with sizes that have the meaning of "
            "cell_size. The table switches it on."
        ),
    )
    families: Annotated[MeshFamiliesConfig, Profile.USER] = Field(
        default_factory=MeshFamiliesConfig,
        description=(
            "What the mesh does on the rivers, the geology contacts, the lake shores, the "
            "flow barriers and the catchment boundary."
        ),
    )
    triangle: Annotated[
        MeshTriangleConfig | None, Profile.USER, VisibleWhen("engine", _TRIANGULATED_ENGINES)
    ] = Field(
        default=None,
        description="Triangulation the triangle and voronoi engines start from: a file to read, the gmsh algorithm.",
    )
    voronoi: Annotated[MeshVoronoiConfig | None, Profile.DEV, VisibleWhen("engine", "voronoi")] = (
        Field(default=None, description="Generator settings of the voronoi engine.")
    )
    regular: Annotated[MeshRegularConfig | None, Profile.DEV, VisibleWhen("engine", "regular")] = (
        Field(
            default=None,
            description="Grid shape of the regular engine, instead of a cell size.",
        )
    )
    seed: Annotated[int, Profile.DEV] = Field(
        default=0,
        ge=0,
        description="Seed of the random draws of an engine; one seed gives one mesh.",
        json_schema_extra={"unit": "-"},
    )
    outside_factor: Annotated[float, Profile.DEV] = Field(
        default=2.0,
        ge=1.0,
        description=(
            "Cell size outside the catchment, as a multiple of cell_size; the cells there "
            "have about outside_factor^2 times the area of a cell_size cell."
        ),
        json_schema_extra={"unit": "-"},
    )
    transition_distance: Annotated[float, Profile.DEV] = Field(
        default=500.0,
        ge=0.0,
        description="Distance in metres outside the catchment over which the cell size grows to its outside value.",
        json_schema_extra={"unit": "m"},
    )
    max_slope: Annotated[float, Profile.DEV] = Field(
        default=0.5,
        gt=0.0,
        le=1.0,
        description="Largest growth of the cell size per metre of distance, which bounds the size ratio of two neighbours.",
        json_schema_extra={"unit": "m/m"},
    )
    gap_cells: Annotated[float, Profile.DEV, VisibleWhen("engine", _TRIANGULATED_ENGINES)] = Field(
        default=2.0,
        ge=0.0,
        description=(
            "Cells across the gap between two face lines (lake shores, barriers, "
            "geology contacts, catchment boundary) or between one and the domain "
            "outline: the cell size there, with the meaning of cell_size, is the gap "
            "divided by this number, never finer than the DEM pixel. 0 switches it off."
        ),
        json_schema_extra={"unit": "cells"},
    )

    @field_validator("gap_cells")
    @classmethod
    def _check_gap_cells(cls, value: float) -> float:
        """Refuse less than one cell across a gap, except 0 which switches the term off."""
        if 0.0 < value < 1.0:
            raise ValueError(
                f"mesh.gap_cells = {value} asks for less than one cell across a gap: "
                "give 1 or more, or 0 to switch the gap term off."
            )
        return value

    @field_validator("engine", mode="before")
    @classmethod
    def _strip_engine(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("engine")
    @classmethod
    def _check_engine_resolves(cls, value: str) -> str:
        """Refuse an engine this installation cannot serve, while reading the document."""
        from hydromodpy.spatial.mesh import registry as mesh_registry

        if mesh_registry.is_registered(value):
            return value
        served = ", ".join(mesh_registry.list_engine_ids()) or "none"
        raise ValueError(
            f"mesh.engine names {value!r}, and this installation serves {served}. A "
            f"third-party engine joins that list through the {mesh_registry.ENTRY_POINT_GROUP!r} "
            "entry-point group, without a patch to HydroModPy."
        )

    @model_validator(mode="after")
    def _check_engine_tables(self) -> MeshConfig:
        """Refuse a table, a size or a key that the chosen engine never reads."""
        if self.regular is not None and self.engine != "regular":
            raise ValueError(
                f'[mesh.regular] gives the grid shape of the "regular" engine, and mesh.engine '
                f'is {self.engine!r}: remove [mesh.regular] or set engine = "regular".'
            )
        if self.regular is not None and self.cell_size is not None:
            raise ValueError(
                "[mesh.regular] shape and mesh.cell_size both size the regular grid: keep one."
            )
        if self.triangle is not None and self.engine not in _TRIANGULATED_ENGINES:
            raise ValueError(
                f"[mesh.triangle] is read by the triangle and voronoi engines, and mesh.engine "
                f"is {self.engine!r}: remove [mesh.triangle]."
            )
        if self.voronoi is not None and self.engine != "voronoi":
            raise ValueError(
                f"[mesh.voronoi] is read by the voronoi engine, and mesh.engine is "
                f"{self.engine!r}: remove [mesh.voronoi]."
            )
        self._check_voronoi_seeds()
        if (
            self.river_cell_size is not None
            and self.cell_size is not None
            and self.river_cell_size > self.cell_size
        ):
            raise ValueError(
                f"mesh.river_cell_size ({self.river_cell_size} m) is coarser than "
                f"mesh.cell_size ({self.cell_size} m): the rivers would be meshed coarser "
                "than the rest of the domain."
            )
        return self

    def _check_voronoi_seeds(self) -> None:
        """The generators come from the file read exactly when a file is read."""
        if self.engine != "voronoi":
            return
        path = self.triangle.path if self.triangle is not None else None
        seeds = self.voronoi.seeds if self.voronoi is not None else None
        if seeds == "triangulation" and path is None:
            raise ValueError(
                '[mesh.voronoi] seeds = "triangulation" takes the generators from the '
                "triangulation read from [mesh.triangle] path, and no path is given."
            )
        if self.voronoi is not None and self.voronoi.lloyd_tolerance != (
            type(self.voronoi).model_fields["lloyd_tolerance"].default
        ):
            if seeds == "triangulation" or (seeds is None and path is not None):
                raise ValueError(
                    "[mesh.voronoi] lloyd_tolerance relaxes generated generators, and the "
                    "generators are the vertices of the triangulation read: drop it."
                )
        if seeds == "generated" and path is not None:
            raise ValueError(
                '[mesh.voronoi] seeds = "generated" contradicts [mesh.triangle] path: the '
                "generators are the vertices of the file read. Drop seeds or the path."
            )

    def requires_river_trace(self, *, active_bc: Collection[str], synthetic: bool) -> bool:
        """Whether the mesh step needs the river network traced from the DEM.

        Never on a synthetic support and never for the ``regular`` engine. A
        generated mesh needs it when the river family is meshed, or when a
        refinement zone measures the height above the stream; a mesh read
        from ``[mesh.triangle] path`` needs it when a stream boundary is active.
        """
        if synthetic or self.engine == "regular":
            return False
        if self.triangle is not None and self.triangle.path is not None:
            return "stream" in active_bc
        return self.families.rivers == "cell" or self.refines_above_stream()

    def refines_above_stream(self) -> bool:
        """Whether a refinement zone measures the height above the stream traced from the DEM."""
        return any(zone.where == "height_above_stream" for zone in self.refinement_zone)
