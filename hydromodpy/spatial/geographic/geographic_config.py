from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.spatial.geographic.bed_regularization_config import BedRegularizationConfig
from hydromodpy.spatial.geographic.capped_breach_config import CappedBreachConfig
from hydromodpy.spatial.geographic.catchment_config import MISSING_CATCHMENT, CatchDef, TxtCatchDef
from hydromodpy.spatial.geographic.crossings_config import CrossingNotchConfig
from hydromodpy.spatial.geographic.enforce_lakes_config import LakeEnforcementConfig
from hydromodpy.spatial.geographic.river_network_config import RiverNetworkConfig
from hydromodpy.spatial.geographic.synthetic_config import SyntheticGeographicConfig

"""Discriminated union of catchment definition variants."""


class GeographicConfig(HydroModelBase):
    """Geographic configuration for watershed delineation.

    This model stores parameters used to extract and prepare the physical domain
    (watershed geometry and rasters) based on various possible input definitions.

    Standard mode uses an external DEM with one of the catchment definitions:
    direct DEM, XYZ text grid, outlet coordinate, or polygon shapefile.
    Synthetic mode builds an analytical support and bypasses external DEM
    delineation.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "dam_carve": (
            "the dam carve of the ground is removed, it flattened a corridor "
            "below the thalweg and the cell drainage D already makes the water "
            "cross the dam; delete the [geographic.dam_carve] table"
        ),
    }

    model_retired_keys = frozenset({"bottom_path"})
    """``bottom_path`` named a bottom raster that nothing read.

    The raster a run reads is ``[data.substratum]``, with
    ``[domain.depth_model] kind = "raster_substratum"`` or ``"raster_thickness"``. ``from_toml`` moves the path there;
    a loader that skips the migration still accepts the key and ignores it.
    """

    source_mode: Annotated[Literal["standard", "synthetic"], Profile.USER] = Field(
        default="standard",
        description=(
            "Where the model domain comes from. "
            "'standard' delineates it from a DEM, an outlet or a polygon ([geographic.catchment]). "
            "'synthetic' builds one analytical support from [geographic.synthetic]."
        ),
    )
    catchment: Annotated[
        CatchDef | None,
        Profile.USER,
        VisibleWhen("source_mode", "standard"),
    ] = Field(
        description=(
            "How the model domain is defined. Required when source_mode='standard', "
            "left out when it is 'synthetic'. The shape is chosen by 'catch_def' on the "
            "nested table: 'dem' | 'txt' | 'from_outlet_coord' | 'from_polyg_shp'."
        ),
    )
    crs_project: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Target projected CRS for all outputs (e.g. 'EPSG:2154'). If not set, derived from the input DEM.",
    )
    dem_correc_type: Annotated[Literal["breach", "fill", "capped_breach"], Profile.USER] = Field(
        default="fill",
        description=(
            "How the DEM is conditioned before the catchment is delineated. 'fill' "
            "(default) only raises cells: each closed depression is raised to its "
            "spill level, then a small gradient on the flats lets every cell drain. "
            "'breach' mostly lowers cells: it carves a path through the barrier "
            "that closes a depression, after raising single-cell pits to their "
            "lowest neighbour, with no limit on length or depth and no fill "
            "afterwards (least-cost breaching, Lindsay 2016); it changes far fewer "
            "cells than 'fill' and can dig deep. 'capped_breach' lowers and raises: "
            "it breaches only within the limits of [geographic.capped_breach] (a "
            "maximum cumulative lowering and a maximum length, in metres), then "
            "fills every depression the limits refused (the hybrid of Lindsay "
            "2016). The depth limit is a sum over the cells of a path, so it does "
            "not give the same landscape at every grid resolution. 'fill' is "
            "the default because it is the tool of the paper behind the network "
            "criterion (FillDepressions, Abherve et al. 2023), and the criterion "
            "itself fills the model top on the mesh by a priority flood: one "
            "conditioning rule from the DEM to the score."
        ),
    )
    capped_breach: Annotated[
        CappedBreachConfig | None,
        Profile.USER,
        VisibleWhen("dem_correc_type", "capped_breach"),
    ] = Field(
        default=None,
        description=(
            "Limits of the 'capped_breach' conditioning: max_depth (default 0.5 m) "
            "and max_distance (default 200 m). Omitted, a 'capped_breach' run uses "
            "those defaults. Declaring it with any other dem_correc_type is refused: "
            "'fill' and 'breach' have no limit to set, and a section that is silently "
            "ignored reads as a limit that was applied."
        ),
    )
    terrain_engine: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Flow-routing engine that conditions the DEM and delineates the catchment. "
            "Unset uses the engine this build defaults to. A string and not an enumeration: "
            "the values that resolve depend on what is installed beside HydroModPy, which is "
            "how a third-party engine is named without a patch."
        ),
    )
    domain_extent: Annotated[Literal["box", "watershed_buff", "watershed"], Profile.USER] = Field(
        default="box",
        description=(
            "Selects the DEM surface used for the domain. 'box' (default) keeps "
            "the full buffered rectangular support. 'watershed' / 'watershed_buff' "
            "select the catchment (optionally with a buffer ring) surface. Note: "
            "the MODFLOW 6 mesh still covers the buffered box (the buffer stays "
            "active for inter-basin exchange); out-of-watershed drainage is kept "
            "out of the catchment discharge by the DRN watershed-routing, not by "
            "an idomain mask. Experimental."
        ),
    )
    reg_fold: Annotated[Path | None, Profile.DEV] = Field(
        default=None,
        description="Folder with pre-computed regional flow rasters. When set, rasters are loaded instead of recomputed.",
    )
    synthetic: Annotated[SyntheticGeographicConfig, Profile.USER] = Field(
        default_factory=SyntheticGeographicConfig,
        description=(
            "Synthetic geographic support used when source_mode='synthetic'. "
            "This analytical mode bypasses watershed delineation from external DEM files."
        ),
    )
    river_network: Annotated[RiverNetworkConfig, Profile.USER] = Field(
        default_factory=RiverNetworkConfig,
        description=(
            "Optional DEM-derived river-network extraction settings. "
            "When disabled, no stream network is generated in geographic preprocessing."
        ),
    )
    enforce_lakes: Annotated[LakeEnforcementConfig, Profile.USER] = Field(
        default_factory=LakeEnforcementConfig,
        description=(
            "Optional lake footprint polygons that the crossing notch and the bed "
            "regularisation leave alone. The routing DEM is not carved at the lakes."
        ),
    )
    crossings: Annotated[CrossingNotchConfig, Profile.USER] = Field(
        default_factory=CrossingNotchConfig,
        description=(
            "Optional notch of the ground at the roads, railways and bridges "
            "that cross the generated channel tree: the embankment is lowered "
            "to the bed level read on both sides, and the catchment is "
            "delineated again on the notched ground."
        ),
    )
    bed_regularization: Annotated[BedRegularizationConfig, Profile.USER] = Field(
        default_factory=BedRegularizationConfig,
        description=(
            "Optional least-change regularisation of the channel bed in the model "
            "top, on the pixels of the generated channel tree: the bed never rises "
            "downstream, crossing notches are gaps and declared weirs are drops."
        ),
    )
    reuse_existing_outputs: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "If true, reuse previously generated geographic artifacts when the "
            "cached fingerprint matches the current DEM, outlet/polygon and "
            "geographic settings. This is useful for profiling repeated "
            "simulation runs in the same workspace."
        ),
    )

    write_intermediates: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description=(
            "Keep intermediate rasters and shapefiles on disk after geographic "
            "preprocessing. When false (default), .hmp/scratch/<run>/_preprocessing/ is "
            "removed after ingestion into the run field store."
        ),
    )

    def uses_synthetic_geographic(self) -> bool:
        """Return True when the analytical synthetic geographic mode is selected."""
        return str(self.source_mode).strip().lower() == "synthetic"

    @property
    def catch_def(self) -> str | None:
        """Discriminator value of the active catchment variant, or None for synthetic."""
        return None if self.catchment is None else self.catchment.catch_def

    @property
    def dem_init_path(self) -> Path | None:
        """DEM input path from the active catchment variant, or None."""
        return None if self.catchment is None else self.catchment.dem_init_path

    @property
    def cell_size(self) -> float | None:
        """Cell size for 'txt' variant, or None otherwise."""
        return getattr(self.catchment, "cell_size", None) if self.catchment is not None else None

    @property
    def dem_resolution(self) -> float | None:
        """Cell size the DEM is aggregated to, in metres, or None to keep its pixel."""
        return None if self.catchment is None else self.catchment.dem_resolution

    @property
    def x_outlet(self) -> float | None:
        """Outlet x coordinate for 'from_outlet_coord' variant, or None otherwise."""
        return getattr(self.catchment, "x_outlet", None) if self.catchment is not None else None

    @property
    def y_outlet(self) -> float | None:
        """Outlet y coordinate for 'from_outlet_coord' variant, or None otherwise."""
        return getattr(self.catchment, "y_outlet", None) if self.catchment is not None else None

    @property
    def snap_dist(self) -> float | None:
        """Outlet snapping distance for 'from_outlet_coord' variant, or None otherwise."""
        return getattr(self.catchment, "snap_dist", None) if self.catchment is not None else None

    @property
    def snap_method(self) -> str:
        """Outlet snap method for 'from_outlet_coord' variant, 'window' otherwise."""
        return getattr(self.catchment, "snap_method", "window")

    @property
    def buff_area(self) -> str | float | None:
        """Watershed buffer for outlet/polygon variants, or None otherwise."""
        return getattr(self.catchment, "buff_area", None) if self.catchment is not None else None

    @property
    def polyg_shp_path(self) -> Path | None:
        """Watershed polygon shapefile for 'from_polyg_shp' variant, or None otherwise."""
        return (
            getattr(self.catchment, "polyg_shp_path", None) if self.catchment is not None else None
        )

    @classmethod
    def from_outlet(
        cls,
        *,
        x: float,
        y: float,
        dem: str | Path,
        snap_dist: float | str = 150.0,
        snap_method: Literal["window", "jenson"] = "window",
        buff_area: float | str = "10%",
        crs_project: str | None = None,
        **overrides,
    ) -> GeographicConfig:
        """Watershed delineated from an outlet coordinate and a DEM raster."""
        return cls(
            source_mode="standard",
            catchment={
                "catch_def": "from_outlet_coord",
                "dem_init_path": Path(dem) if dem is not None else None,
                "x_outlet": float(x),
                "y_outlet": float(y),
                "snap_dist": snap_dist,
                "snap_method": snap_method,
                "buff_area": buff_area,
            },
            crs_project=crs_project,
            **overrides,
        )

    @classmethod
    def from_dem(
        cls,
        dem: str | Path,
        *,
        crs_project: str | None = None,
        **overrides,
    ) -> GeographicConfig:
        """Model domain driven entirely by a DEM raster."""
        return cls(
            source_mode="standard",
            catchment={"catch_def": "dem", "dem_init_path": Path(dem)},
            crs_project=crs_project,
            **overrides,
        )

    @classmethod
    def from_polygon(
        cls,
        polygon: str | Path,
        *,
        dem: str | Path,
        buff_area: float | str = "10%",
        crs_project: str | None = None,
        **overrides,
    ) -> GeographicConfig:
        """Watershed delineated from a polygon shapefile plus a DEM."""
        return cls(
            source_mode="standard",
            catchment={
                "catch_def": "from_polyg_shp",
                "dem_init_path": Path(dem),
                "polyg_shp_path": Path(polygon),
                "buff_area": buff_area,
            },
            crs_project=crs_project,
            **overrides,
        )

    @classmethod
    def synthetic_case(cls, **overrides) -> GeographicConfig:
        """Analytical synthetic geographic support (bypasses DEM delineation)."""
        return cls(source_mode="synthetic", **overrides)

    @field_validator("terrain_engine")
    @classmethod
    def _check_terrain_engine_resolves(cls, value: str | None) -> str | None:
        """Refuse an engine this installation cannot serve, while reading the document.

        It happens here rather than at the
        first delineation because a project that names an engine nobody installed
        is a broken document, and learning that after a DEM has been conditioned
        costs the conditioning.

        ``None`` is not checked: it means "whatever this build defaults to", and
        a default that does not resolve is an environment fault the registry
        reports with its own message.
        """
        if value is None:
            return value
        from hydromodpy.spatial.terrain import registry as terrain_registry

        if terrain_registry.is_registered(value):
            return value
        served = ", ".join(terrain_registry.list_engine_ids()) or "none"
        raise ValueError(
            f"geographic.terrain_engine names {value!r}, and this installation serves "
            f"{served}. A third-party engine joins that list through the "
            f"{terrain_registry.ENTRY_POINT_GROUP!r} entry-point group, without a patch to "
            "HydroModPy."
        )

    @model_validator(mode="after")
    def _check_catchment_is_implemented(self) -> GeographicConfig:
        """Refuse ``catch_def = "txt"``: no code rasterises an XYZ text grid."""
        if isinstance(self.catchment, TxtCatchDef):
            raise ValueError(
                "geographic.catchment.catch_def = 'txt' is not implemented: nothing "
                "rasterises an XYZ text grid. Use 'dem' with a raster, or "
                "'from_outlet_coord' / 'from_polyg_shp' with a regional DEM."
            )
        return self

    @model_validator(mode="after")
    def _check_capped_breach_section(self) -> GeographicConfig:
        """Refuse limits declared for a method that has none."""
        if self.capped_breach is not None and self.dem_correc_type != "capped_breach":
            raise ValueError(
                "[geographic.capped_breach] sets the limits of dem_correc_type = "
                f"'capped_breach', and dem_correc_type is {self.dem_correc_type!r}, which "
                "has none: remove the section or select 'capped_breach'."
            )
        return self

    @model_validator(mode="after")
    def _check_jenson_snap_has_a_network(self) -> GeographicConfig:
        """Refuse a Jenson snap with no threshold to draw its stream network from."""
        if self.snap_method != "jenson":
            return self
        refusal = self.river_network.missing_threshold_refusal(
            needed_by="geographic.catchment.snap_method = 'jenson'"
        )
        if refusal is not None:
            raise ValueError(refusal)
        return self

    @model_validator(mode="after")
    def _check_sections_on_the_channel_tree(self) -> GeographicConfig:
        """Refuse a notch or a bed regularisation with no channel tree or no catchment.

        The texts stay literal: the docs registry links the sections a refusal names.
        """
        if self.crossings.enabled and not self.river_network.enabled:
            raise ValueError(
                "[geographic.crossings] enabled = true needs [geographic.river_network] "
                "enabled = true: the notch follows the channel tree the DEM generates, "
                "so without it there is no channel to cut."
            )
        if self.crossings.enabled and (support := self._undelineated_support()):
            raise ValueError(
                "[geographic.crossings] cuts a delineated catchment: it needs "
                f"catch_def = 'from_outlet_coord' or 'from_polyg_shp', not {support}."
            )
        if self.bed_regularization.enabled and not self.river_network.enabled:
            raise ValueError(
                "[geographic.bed_regularization] enabled = true needs "
                "[geographic.river_network] enabled = true: the bed is fitted along "
                "the channel tree the DEM generates, so without it there is no bed."
            )
        if self.bed_regularization.enabled and (support := self._undelineated_support()):
            raise ValueError(
                "[geographic.bed_regularization] fits the bed of a delineated catchment: "
                f"it needs catch_def = 'from_outlet_coord' or 'from_polyg_shp', not {support}."
            )
        return self

    def _undelineated_support(self) -> str | None:
        """Name the support when it is not a delineated catchment, else None."""
        if self.uses_synthetic_geographic():
            return "a synthetic support"
        if self.catch_def == "dem":
            return "catch_def = dem"
        return None

    @model_validator(mode="after")
    def _check_ground_with_shared_flow(self) -> GeographicConfig:
        """Refuse a declared correction of the ground under a shared regional flow job.

        The job was routed on the raw DEM and is checked against the DEM it is
        handed, so a corrected ground can never match it.
        """
        if self.reg_fold is not None and self.crossings.enabled:
            raise ValueError(
                "[geographic] reg_fold shares a regional flow routed on the raw DEM, and "
                "[geographic.crossings] corrects the ground the routing starts from: "
                "remove one of them."
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _catchment_follows_source_mode(cls, data: Any) -> Any:
        """Let a document leave the catchment, or its DEM, out.

        Neither field has a default, so the reference shows both as required. A
        synthetic support carries no catchment, and a [data.dem] source may give
        the DEM. What is still missing is refused by ``_check_source_mode_payload``
        after the other keys are checked, with a message that names the key.
        """
        if not isinstance(data, Mapping):
            return data
        catchment = data.get("catchment")
        if "catchment" not in data:
            return {**data, "catchment": None}
        if isinstance(catchment, Mapping) and "dem_init_path" not in catchment:
            # Same rule one level down: the dem shape shows its DEM as required,
            # and a [data.dem] source may still supply it.
            return {**data, "catchment": {**catchment, "dem_init_path": None}}
        return data

    @model_validator(mode="after")
    def _check_source_mode_payload(self, info: ValidationInfo) -> GeographicConfig:
        """Enforce mode-level invariants between source_mode and catchment."""
        if self.uses_synthetic_geographic():
            return self
        if self.catchment is None:
            raise ValueError(MISSING_CATCHMENT)
        context = info.context or {}
        allow_dem_bootstrap = bool(context.get("allow_dem_bootstrap"))
        if self.catchment.dem_init_path is None and not allow_dem_bootstrap:
            raise ValueError(
                f"catch_def='{self.catchment.catch_def}' requires 'dem_init_path' "
                "(path to the DEM raster or XYZ text file)."
            )
        return self


__all__ = [
    "GeographicConfig",
]
