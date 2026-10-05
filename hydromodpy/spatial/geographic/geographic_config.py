from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, ValidationInfo, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.tracking import InputFile
from hydromodpy.core.units import UREG, LengthMeters
from hydromodpy.spatial.geographic.synthetic.config import SyntheticGeographicConfig


def _normalize_buff_area(value):
    """Return ``buff_area`` in the one form that says which rule it selects.

    The form, not the type or the magnitude, carries the meaning downstream
    (``catchment_domain.buffer_rule_of``):

    - ``"10%"`` or ``"10 %"`` becomes the string ``"10%"``: the buffered
      catchment covers 10 per cent more area than the catchment;
    - ``"150 m"``, ``"0.15 km"`` or ``"150"`` becomes ``"150.0 m"``: an explicit
      distance, a string with no unit being metres;
    - a bare number stays a float: the legacy v1 rule, which a sealed run
      still carries and must replay.

    A run is re-read from its own sealed config, so this validator reads what
    it wrote: ``normalize(normalize(x)) == normalize(x)``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError("geographic.buff_area cannot be empty.")
        if token.endswith("%"):
            pct = float(token[:-1].strip())
            if pct <= 0.0:
                raise ValueError("geographic.buff_area percent must be > 0.")
            return f"{int(pct)}%" if pct.is_integer() else f"{pct!r}%"
        quantity = UREG(token)
        if not hasattr(quantity, "magnitude"):
            dist_m = float(quantity)
        elif quantity.dimensionless:
            dist_m = float(quantity.magnitude)
        else:
            dist_m = float(quantity.to("m").magnitude)
        if dist_m <= 0.0:
            raise ValueError("geographic.buff_area distance must be > 0.")
        return f"{dist_m!r} m"
    pct = float(value)
    if pct <= 0.0:
        raise ValueError("geographic.buff_area percent must be > 0.")
    return pct


_BUFF_AREA_DESCRIPTION = (
    "Margin around the watershed polygon. A percentage ('10%') enlarges the "
    "catchment AREA by that share, the rule of Abherve et al. (2023): the "
    "distance is solved on the real polygon, then snapped to the DEM grid. A "
    "length ('500 m', '2 km') is an explicit distance. A bare number (10) keeps "
    "the legacy v1 rule, 10 per cent of sqrt(area in km2) km, about 50 per cent "
    "more area on a real catchment, and warns: it lets a sealed run replay its "
    "domain."
)


class _CatchDefBase(HydroModelBase):
    """Common base for catchment definition variants."""

    dem_init_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="dem", category="data"),
    ] = Field(
        default=None,
        description=(
            "Path to the DEM raster used as input. "
            "For 'dem' and 'txt' modes: defines the model domain directly. "
            "For 'from_outlet_coord' and 'from_polyg_shp' modes: regional DEM used for flow analysis. "
            "May be left absent when [data.dem.sources] declares the DEM."
        ),
    )


class DemCatchDef(_CatchDefBase):
    """Model domain defined directly from a DEM raster."""

    catch_def: Annotated[Literal["dem"], Profile.USER] = Field(
        default="dem",
        description="Catchment defined by the DEM raster extent.",
    )


class TxtCatchDef(_CatchDefBase):
    """Model domain defined from an XYZ text grid plus a cell size."""

    catch_def: Annotated[Literal["txt"], Profile.USER] = Field(
        default="txt",
        description="Catchment defined from an XYZ text grid (cell_size required).",
    )
    cell_size: Annotated[LengthMeters, Profile.USER] = Field(
        gt=0,
        description=(
            "Grid cell size in metres used to rasterise the XYZ point cloud. "
            "Accepts inline units (e.g. '25 m', '0.025 km')."
        ),
    )


class OutletCatchDef(_CatchDefBase):
    """Watershed delineated from an outlet coordinate."""

    catch_def: Annotated[Literal["from_outlet_coord"], Profile.USER] = Field(
        default="from_outlet_coord",
        description="Watershed delineated from outlet coordinates on a regional DEM.",
    )
    x_outlet: Annotated[float, Profile.USER] = Field(
        description="X coordinate of the watershed outlet in the projected CRS.",
    )
    y_outlet: Annotated[float, Profile.USER] = Field(
        description="Y coordinate of the watershed outlet in the projected CRS.",
    )
    snap_dist: Annotated[LengthMeters, Profile.USER] = Field(
        gt=0.0,
        description=(
            "Maximum snapping distance (metres) to move the outlet to the nearest stream cell. "
            "Accepts inline units (e.g. 50, '50 m', '0.05 km')."
        ),
    )
    buff_area: Annotated[str | float, Profile.USER] = Field(description=_BUFF_AREA_DESCRIPTION)

    @field_validator("buff_area", mode="before")
    @classmethod
    def _normalize_buff_area_field(cls, value):
        return _normalize_buff_area(value)


class PolygonCatchDef(_CatchDefBase):
    """Watershed delineated from a polygon shapefile."""

    catch_def: Annotated[Literal["from_polyg_shp"], Profile.USER] = Field(
        default="from_polyg_shp",
        description="Watershed delineated from a polygon shapefile plus a regional DEM.",
    )
    polyg_shp_path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="watershed_polygon", category="geometry"),
    ] = Field(
        description="Path to the watershed polygon shapefile.",
    )
    buff_area: Annotated[str | float, Profile.USER] = Field(description=_BUFF_AREA_DESCRIPTION)

    @field_validator("buff_area", mode="before")
    @classmethod
    def _normalize_buff_area_field(cls, value):
        return _normalize_buff_area(value)


CatchDef: TypeAlias = Annotated[
    DemCatchDef | TxtCatchDef | OutletCatchDef | PolygonCatchDef,
    Field(discriminator="catch_def", description="Catchment definition discriminator."),
]
"""Discriminated union of catchment definition variants."""


class RiverNetworkConfig(HydroModelBase):
    """Optional DEM-based river network extraction settings.

    Enable this block when geographic preprocessing must derive streams from
    flow accumulation. Thresholds can be expressed as contributing area
    (``area_km2``) or contributing cell count (``cells``), with optional
    pruning and Strahler/link rasters for downstream diagnostics.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Enable DEM-based river-network extraction from flow accumulation "
            "during geographic preprocessing."
        ),
    )
    threshold_mode: Annotated[Literal["area_km2", "cells"], Profile.USER] = Field(
        default="area_km2",
        description=(
            "Stream-initiation threshold selector. "
            "'area_km2' uses contributing area in km^2. "
            "'cells' uses contributing-cell count directly."
        ),
    )
    threshold_area_km2: Annotated[
        float | None,
        Profile.USER,
        VisibleWhen("threshold_mode", "area_km2"),
    ] = Field(
        default=None,
        description=(
            "Contributing area threshold (km^2), required when threshold_mode='area_km2'."
        ),
    )
    threshold_cells: Annotated[
        float | None,
        Profile.USER,
        VisibleWhen("threshold_mode", "cells"),
    ] = Field(
        default=None,
        description=("Contributing-cell threshold, required when threshold_mode='cells'."),
    )
    prune_short_streams: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="If true, remove short stream segments after extraction.",
    )
    min_stream_length_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Minimum stream length (metres) used by short-segment pruning. "
            "Accepts inline units (e.g. 0, 250, '250 m', '0.5 km')."
        ),
    )
    compute_strahler_order: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute Strahler order raster from extracted streams.",
    )
    compute_stream_links: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute stream-link identifier raster from extracted streams.",
    )
    all_vertices: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Forwarded to Whitebox raster_streams_to_vector. False keeps a lighter vector geometry."
        ),
    )

    @model_validator(mode="after")
    def _validate_threshold_payload(self) -> RiverNetworkConfig:
        if not bool(self.enabled):
            return self

        mode = str(self.threshold_mode)
        if mode == "area_km2":
            if self.threshold_area_km2 is None:
                raise ValueError(
                    "geographic.river_network.threshold_mode='area_km2' requires "
                    "geographic.river_network.threshold_area_km2."
                )
            if float(self.threshold_area_km2) <= 0.0:
                raise ValueError("geographic.river_network.threshold_area_km2 must be > 0.")
            if self.threshold_cells is not None:
                raise ValueError(
                    "geographic.river_network.threshold_cells must be omitted when "
                    "threshold_mode='area_km2'."
                )
            return self

        if self.threshold_cells is None:
            raise ValueError(
                "geographic.river_network.threshold_mode='cells' requires "
                "geographic.river_network.threshold_cells."
            )
        if float(self.threshold_cells) <= 0.0:
            raise ValueError("geographic.river_network.threshold_cells must be > 0.")
        if self.threshold_area_km2 is not None:
            raise ValueError(
                "geographic.river_network.threshold_area_km2 must be omitted when "
                "threshold_mode='cells'."
            )
        return self


class LakeEnforcementConfig(HydroModelBase):
    """Hydro-enforce lakes into the ROUTING DEM before D8 flow routing.

    A topographic breach/fill is lake-blind: on a dammed reservoir it carves a
    thalweg that misses the flat water body, so streams dead-end short of the lake
    and the outlet-delineated catchment excludes the reservoir. When enabled, the
    lake footprints are carved (a gentle ramp toward the outlet plus an outlet
    notch) into a SEPARATE routing DEM used only for delineation; the model grid
    top stays on the raw DEM, so the lake-aquifer geometry is untouched. It reuses
    the lake footprint polygons already supplied for LAK cells -- no river source.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Carve the lake footprints into the routing DEM before D8 so streams "
            "converge into the lakes and drain to the outlet through them."
        ),
    )
    lake_geometry_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_enforcement_geometry", category="geometry"),
    ] = Field(
        default=None,
        description=(
            "Lake footprint polygons (gpkg/shp) to carve. A bare filename resolves "
            "against <workspace>/data/lake_geometry/. Required when enabled."
        ),
    )
    slope: Annotated[float, Profile.USER] = Field(
        default=0.003,
        gt=0.0,
        description=(
            "Ramp gradient (m per m of distance to the outlet). Small and positive "
            "so each lake slopes gently toward the outlet with no flat depression "
            "(a flat sink would make the breach crawl)."
        ),
    )
    buffer_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=15.0,
        ge=0.0,
        description=(
            "Buffer (metres) applied to each lake footprint to bridge inter-lake "
            "sills and knit the shoreline into the carve."
        ),
    )
    capture_radius_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.0,
        ge=0.0,
        description=(
            "If > 0, run a SECOND delineation pass: any stream that dead-ends within "
            "this distance of a lake (a near-miss over a flat forebay) is carved to "
            "the lake and re-delineated, so its channel reaches the shoreline. 0 "
            "disables the capture pass (lake carve only)."
        ),
    )
    capture_max_streams: Annotated[int, Profile.EXPERT] = Field(
        default=8,
        ge=1,
        description=(
            "Capture pass: cap on how many near-miss stream terminals are carved to "
            "lakes per pass (kept by decreasing flow accumulation)."
        ),
    )
    capture_min_acc_fraction: Annotated[float, Profile.EXPERT] = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Capture pass: keep only near-miss terminals whose flow accumulation is at "
            "least this fraction of the largest, so a tiny rivulet is not carved."
        ),
    )


class DamCarveConfig(HydroModelBase):
    """Optional dam structure-carve of the ground.

    A raw DEM samples the concrete dam crest as terrain, so the aquifer column
    under the dam is lifted to the crest (~87 m on the Cheze 5 m DEM) and a
    cutoff-wall HFB band lands above the real seepage. This carves ONLY the dam
    footprint of the ground down to the surrounding valley floor, so the
    cutoff wall can sit on the surveyed axis at the dam (not shifted downstream).

    The ground is the DEM plus the corrections declared here and in
    ``[geographic.crossings]``. Both the routing chain and the model top start
    from it, so the carved dam is seen by the flow routing and by the aquifer
    alike.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Carve the dam footprint of the ground down to the local valley "
            "floor, so the routing chain and the model top both see the dam "
            "removed and the cutoff wall sits at the true dam on a raw DEM."
        ),
    )
    line_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="dam_carve_line", category="geometry"),
    ] = Field(
        default=None,
        description=(
            "Dam trace (gpkg/shp/csv) along which the ground is carved. A bare "
            "filename resolves against <workspace>/data/cutoff_wall/. Usually the "
            "same surveyed voile axis as the cutoff_wall. Required when enabled."
        ),
    )
    buffer_m: Annotated[LengthMeters, Profile.USER] = Field(
        default=40.0,
        gt=0.0,
        description=(
            "Half-width (metres) of the carved corridor around the dam trace. "
            "Make it a bit wider than one DEM/cell size so the whole dam body is "
            "brought to the valley floor."
        ),
    )
    search_radius_m: Annotated[LengthMeters | None, Profile.USER] = Field(
        default=None,
        gt=0.0,
        description=(
            "Radius (metres) of the neighborhood whose minimum elevation defines "
            "the valley floor the corridor is carved to. When omitted, derives "
            "3 * buffer_m."
        ),
    )


class CrossingNotchConfig(HydroModelBase):
    """Cut the embankments of roads, railways and bridges out of the ground.

    A DEM shows the embankment of a road across a valley as a wall: the flow
    routing then fills behind it or digs through it, and the model top carries
    the wall into the aquifer. The notch lowers the DEM along the channel at each
    crossing to the bed level read on both sides of the structure, and nowhere
    else. It is a correction of the ground: the routing chain and the model top
    both start from the notched ground.

    The notch follows the channel tree of ``[geographic.river_network]``, which
    is delineated a first time on the ground, notched, and delineated again.
    Weirs and dams are not notched: a weir is a drop of the bed, not a wall. A
    road laid on a dam crest is not notched either: a crossing with a dam or a
    weir of the file within ``snap_radius``, a ``[geographic.dam_carve]`` line
    within ``snap_radius``, or a ``[geographic.enforce_lakes]`` polygon on its
    channel reach is left alone and reported as ``dam_or_weir``.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Notch the ground at the crossings of the channel tree with the "
            "declared structures, then delineate again on the notched ground. "
            "Needs [geographic.river_network] enabled."
        ),
    )
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="crossings_notch", category="geometry"),
    ] = Field(
        default=None,
        description=(
            "Vector file of the structures, with the columns 'kind', 'source', "
            "'name' and 'drop_m' of the crossings data variable. When left empty "
            "and enabled, it is filled from [[data.crossings.sources]], so the "
            "structures are named once. Required when enabled, from one of the "
            "two."
        ),
    )
    kinds: Annotated[list[Literal["road", "railway", "bridge"]], Profile.USER] = Field(
        default_factory=lambda: ["road", "railway", "bridge"],
        min_length=1,
        description=("Structure kinds to notch. Weirs and dams are never notched."),
    )
    notch_width: Annotated[LengthMeters, Profile.USER] = Field(
        default=10.0,
        gt=0.0,
        description=(
            "Width of the notch across the embankment, in metres. The channel pixel "
            "itself is always lowered, so a width below the cell size cuts one "
            "pixel. The width is applied along the embankment only, the run of "
            "channel pixels that stand above the bed line, never to the two pixels "
            "where the bed is read. Accepts inline units (e.g. 10, '10 m')."
        ),
    )
    bed_reach: Annotated[LengthMeters, Profile.USER] = Field(
        default=50.0,
        gt=0.0,
        description=(
            "Distance along the channel, on each side of the crossing, where the "
            "bed level is read, in metres. The embankment is assumed narrower "
            "than twice this. The notch is the straight line between the two bed "
            "levels. A bed end that falls on the embankment of another crossing is "
            "read further along the channel, beyond it. Accepts inline units "
            "(e.g. 50, '50 m')."
        ),
    )
    max_depth: Annotated[LengthMeters, Profile.USER] = Field(
        default=3.0,
        gt=0.0,
        description=(
            "Largest lowering of any pixel, in metres. A pixel that would be "
            "lowered more is lowered by this and counted as capped in the "
            "report: the embankment is then higher than the cap allows for, "
            "or the crossing sits on a ridge. Accepts inline units (e.g. 3, "
            "'3 m')."
        ),
    )
    snap_radius: Annotated[LengthMeters, Profile.USER] = Field(
        default=30.0,
        gt=0.0,
        description=(
            "A point structure (a bridge of the ROE) farther than this from the "
            "channel tree is ignored, and so is a channel pixel farther than "
            "this from its crossing, in metres. A dam or a weir of the file, or a "
            "dam_carve line, within this distance of a crossing stops its notch. "
            "Accepts inline units (e.g. 30, '30 m')."
        ),
    )


class CappedBreachConfig(HydroModelBase):
    """Limits of the ``capped_breach`` DEM conditioning, in metres.

    Read only when ``[geographic] dem_correc_type = "capped_breach"``. Least-cost
    breaching digs a path through the barrier that closes a depression. These two
    limits bound that digging, and whatever they refuse is filled instead. Both
    are given in metres but the tool counts along the cells of a path (a sum of
    lowerings, a number of cells), so a given value does not mean the same thing
    at every grid resolution: see each field.
    """

    max_depth: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.5,
        gt=0.0,
        description=(
            "Largest cumulative lowering, in metres, of one breach path (the "
            "'max_cost' of Whitebox): the lowering summed over the cells of the "
            "path, not the depth of one cell. Measured on the Flume at 25 m with "
            "8-cell paths, the realised maximum lowering of a cell follows it within "
            "0.01 m. On a finer grid a thick embankment spreads the cost over more "
            "cells, so it is filled instead of dug: the same value does not give the "
            "same landscape at every resolution. A depression whose cheapest breach "
            "costs more is filled. Paths overlap, so the lowering of a cell can "
            "exceed it (Nancon 75 m: 0.56 m for 0.5 m). The realised depth is "
            "measured after the call, logged, and warned about when it exceeds "
            "this value. Accepts inline units (e.g. 0.5, '0.5 m')."
        ),
    )
    max_distance: Annotated[LengthMeters, Profile.USER] = Field(
        default=200.0,
        gt=0.0,
        description=(
            "Longest breach path, in metres. Translated to the DEM grid as "
            "ceil(max_distance / cell size) cells, at least one, and counted in "
            "cells along the path: a diagonal step counts one cell, so a diagonal "
            "breach can be up to 1.41 times longer than max_distance. A depression "
            "with no way out within this length is filled. Accepts inline units "
            "(e.g. 200, '0.2 km')."
        ),
    )


class BedRegularizationConfig(HydroModelBase):
    """Least-change regularisation of the channel bed in the model top.

    A DEM read along its own channel rises downstream at many pixels: a deck, a
    hedge, a resampling artefact. A drain or a stream cell on such a rise cannot
    drain into the next one. On the pixels of the generated channel tree only,
    the regularisation fits the bed closest to the ground in least squares that
    never rises downstream (the isotonic regression on a tree of Pardalos and
    Xue, 1999), raising and lowering alike, then gives every pooled flat a
    minimum drop centred on its level. The pixels a crossing notch lowered are
    gaps: interpolated along the channel, never pulling the fit. A declared
    weir or dam cuts the tree, so its drop is kept, and a declared lake is left
    out with its surface.

    It writes a regularised copy of the ground, and the model top and the SFR
    bed read it, so drains and stream reaches see one bed. The routing DEM, the
    channel tree, the catchment and the mesh never read that copy.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Regularise the channel bed of the model top: the least-change fit of "
            "the ground that never rises downstream along the channel tree, with "
            "the crossing notches as gaps and the declared weirs and dams as "
            "drops. Needs [geographic.river_network] enabled."
        ),
    )
    min_slope: Annotated[float, Profile.USER] = Field(
        default=1.0e-4,
        ge=0.0,
        description=(
            "Minimum drop of the fitted bed per metre along the channel (m/m), "
            "given to the flats the fit pools. The SFR default slope."
        ),
    )


class GeographicConfig(HydroModelBase):
    """Geographic configuration for watershed delineation.

    This model stores parameters used to extract and prepare the physical domain
    (watershed geometry and rasters) based on various possible input definitions.

    Standard mode uses an external DEM with one of the catchment definitions:
    direct DEM, XYZ text grid, outlet coordinate, or polygon shapefile.
    Synthetic mode builds an analytical support and bypasses external DEM
    delineation.
    """

    model_retired_keys = frozenset({"bottom_path"})
    """``bottom_path`` named a bottom raster that nothing read.

    The raster a run reads is ``[data.substratum]``, with
    ``[domain.depth_model] kind = "raster_substratum"`` or ``"raster_thickness"``. ``from_toml`` moves the path there;
    a loader that skips the migration still accepts the key and ignores it.
    """

    source_mode: Annotated[Literal["standard", "synthetic"], Profile.USER] = Field(
        default="standard",
        description=(
            "Geographic runtime mode. "
            "'standard' keeps the historical DEM/outlet/polygon workflow. "
            "'synthetic' builds one analytical support from [geographic.synthetic]."
        ),
    )
    catchment: Annotated[
        CatchDef | None,
        Profile.USER,
        VisibleWhen("source_mode", "standard"),
    ] = Field(
        default=None,
        description=(
            "Catchment definition payload used when source_mode='standard'. "
            "Discriminated by 'catch_def' on the nested table: "
            "'dem' | 'txt' | 'from_outlet_coord' | 'from_polyg_shp'."
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
            "Optional lake hydro-enforcement of the routing DEM: carve the lake "
            "footprints so streams route into the lakes and drain to the outlet, "
            "without touching the model grid top."
        ),
    )
    dam_carve: Annotated[DamCarveConfig, Profile.USER] = Field(
        default_factory=DamCarveConfig,
        description=(
            "Optional dam structure-carve of the ground: lower the dam footprint "
            "to the valley floor, for the routing chain and the model top alike, "
            "so a cutoff wall sits at the dam on a raw DEM."
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

        The same refusal the ``terrain-delineate`` capability performs on
        ``inputs.engine``, at the other door. It happens here rather than at the
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
    def _check_crossings_section(self) -> GeographicConfig:
        """Refuse a notch that has no channel tree, no DEM to cut, or a shared flow."""
        if not self.crossings.enabled:
            return self
        if not self.river_network.enabled:
            raise ValueError(
                "[geographic.crossings] enabled = true needs [geographic.river_network] "
                "enabled = true: the notch follows the channel tree the DEM generates, "
                "so without it there is no channel to cut."
            )
        if self.uses_synthetic_geographic() or self.catch_def == "dem":
            raise ValueError(
                "[geographic.crossings] cuts a delineated catchment: it needs "
                "catch_def = 'from_outlet_coord' or 'from_polyg_shp', not "
                f"{'a synthetic support' if self.uses_synthetic_geographic() else 'catch_def = dem'}."
            )
        return self

    @model_validator(mode="after")
    def _check_bed_regularization_section(self) -> GeographicConfig:
        """Refuse a bed regularisation that has no channel tree to follow."""
        if not self.bed_regularization.enabled:
            return self
        if not self.river_network.enabled:
            raise ValueError(
                "[geographic.bed_regularization] enabled = true needs "
                "[geographic.river_network] enabled = true: the bed is fitted along "
                "the channel tree the DEM generates, so without it there is no bed."
            )
        if self.uses_synthetic_geographic() or self.catch_def == "dem":
            raise ValueError(
                "[geographic.bed_regularization] fits the bed of a delineated catchment: "
                "it needs catch_def = 'from_outlet_coord' or 'from_polyg_shp', not "
                f"{'a synthetic support' if self.uses_synthetic_geographic() else 'catch_def = dem'}."
            )
        return self

    @model_validator(mode="after")
    def _check_ground_with_shared_flow(self) -> GeographicConfig:
        """Refuse a declared correction of the ground under a shared regional flow job.

        The job was routed on the raw DEM and is checked against the DEM it is
        handed, so a corrected ground can never match it.
        """
        if self.reg_fold is None:
            return self
        declared = [
            name
            for name, section in (("dam_carve", self.dam_carve), ("crossings", self.crossings))
            if section.enabled
        ]
        if declared:
            raise ValueError(
                f"[geographic] reg_fold shares a regional flow routed on the raw DEM, and "
                f"[geographic.{declared[0]}] corrects the ground the routing starts from: "
                "remove one of them."
            )
        return self

    @model_validator(mode="after")
    def _check_source_mode_payload(self, info: ValidationInfo) -> GeographicConfig:
        """Enforce mode-level invariants between source_mode and catchment."""
        if self.uses_synthetic_geographic():
            return self
        if self.catchment is None:
            raise ValueError(
                "geographic.catch_def is required when geographic.source_mode='standard'."
            )
        context = info.context or {}
        allow_dem_bootstrap = bool(context.get("allow_dem_bootstrap"))
        if self.catchment.dem_init_path is None and not allow_dem_bootstrap:
            raise ValueError(
                f"catch_def='{self.catchment.catch_def}' requires 'dem_init_path' "
                "(path to the DEM raster or XYZ text file)."
            )
        return self


__all__ = [
    "BedRegularizationConfig",
    "CappedBreachConfig",
    "CatchDef",
    "CrossingNotchConfig",
    "DemCatchDef",
    "GeographicConfig",
    "OutletCatchDef",
    "PolygonCatchDef",
    "RiverNetworkConfig",
    "TxtCatchDef",
]
