"""Pydantic configuration for hydrography data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.source import registry
from hydromodpy.data.variables.hydrography.api_source import NETWORK_PAYLOAD_KIND


class HydrographySourceConfig(HydroModelBase):
    """Configuration for one hydrography data source.

    Hydrography sources describe river-network vector or raster data. Use
    ``custom`` for local files, and otherwise the id of a source that serves
    river linework -- ``osm``, ``bdtopage`` and ``euhydro`` ship here, and a
    third party adds one by registering it on the
    ``hydromodpy.data.source`` entry-point group.

    **The name is not a closed list, and that is the point.** It used to be a
    ``Literal`` of four words, which was the fourth copy of a list the registry
    now owns and the one place a plugin could not reach: a source installed
    beside HydroModPy was resolvable by every caller and nameable by no
    document. It is validated against the registry instead, so the exported
    JSON Schema stays a plain string and does not describe what happens to be
    installed next to the build that exported it.
    """

    source: Annotated[str, Profile.USER] = Field(
        ...,
        description=(
            "Data provider. Any source id this installation resolves and that serves river "
            "linework is accepted, so a third-party source registered on the "
            "'hydromodpy.data.source' entry-point group is named here by its id."
        ),
        examples=["custom"],
        json_schema_extra={
            "value_docs": {
                "custom": "Loads a river network from a local vector or raster file you provide.",
                "osm": "Downloads waterway geometries from OpenStreetMap.",
                "bdtopage": "Downloads the French BD Topage reference network from the Sandre WFS.",
                "euhydro": "Downloads the EEA EU-Hydro continental-scale river network.",
            }
        },
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="hydrography", category="data"),
    ] = Field(
        default=None,
        description="Path to a vector file (SHP/GPKG/GeoJSON), raster (TIF/TIFF), or directory containing one.",
    )
    rasterize_field: Annotated[str, Profile.USER] = Field(
        default="FID",
        description="Attribute field used when rasterising the vector layer.",
    )

    # --- BD Topage (Sandre WFS) ---
    typename: Annotated[str, Profile.DEV] = Field(
        default="sa:CoursEau_FXX_Topage2025",
        description="WFS typename for BD Topage.",
    )
    page_size: Annotated[int, Profile.DEV] = Field(
        default=2000,
        description="WFS pagination page size (BD Topage).",
    )

    # --- EU-Hydro (EEA REST) ---
    group_name: Annotated[str, Profile.DEV] = Field(
        default="River_Net_lines",
        description="MapServer group name for EU-Hydro layer discovery.",
    )
    euhydro_page_size: Annotated[int, Profile.DEV] = Field(
        default=1000,
        description="Pagination page size for EU-Hydro REST queries.",
    )

    # --- Cache ---
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Bypass API cache and re-download data.",
    )

    # --- OSM ---
    waterway_types: Annotated[list[str], Profile.DEV] = Field(
        default_factory=lambda: ["river", "stream"],
        description="OSM waterway tag values to fetch.",
    )

    @model_validator(mode="after")
    def _check_custom_requires_path(self) -> HydrographySourceConfig:
        if self.source == "custom" and self.path is None:
            raise ValueError("Custom source requires 'path'.")
        return self

    @model_validator(mode="after")
    def _check_the_name_is_a_source_that_serves_a_network(self) -> HydrographySourceConfig:
        """Refuse a name no source answers to, or one that answers with the wrong shape.

        Both refusals are the registry's, re-raised as ``ValueError`` so the
        fault names ``data.hydrography.sources[i].source`` instead of arriving
        as an exception type a configuration reader has no place for.

        Checking only that the name resolves would let ``sim2-precipitation``
        into a hydrography section, refused much later by the fetch itself; the
        payload kind is read here for the same reason it is read at the build
        seam, and it costs an import of the adapter module. Measured on this
        tree: 0.2 ms and four modules for the first one, and no adapter pulls
        geopandas, rasterio or xarray at import.
        """
        if self.source == "custom":
            return self
        try:
            registry.get_serving(self.source, NETWORK_PAYLOAD_KIND)
        except (DataRequestError, DataCapabilityError) as exc:
            raise ValueError(str(exc)) from exc
        return self


class HydrographyConfig(HydroModelBase):
    """Top-level hydrography configuration.

    The section lists stream-network sources used by data loading and boundary
    preparation. It is commonly inferred when ``flow.active_bc`` contains a
    stream boundary condition.

    ``mask_path`` sits here and not on a source because the manager concatenates
    every source before clipping **once**: two sources disagreeing on the extent
    would be concatenated and then clipped to one of the two, which is a
    question the section level makes unaskable.
    """

    sources: Annotated[list[HydrographySourceConfig], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one hydrography data source.",
    )
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "SHP/GPKG/GeoJSON/TIF whose shape the network is clipped to and whose "
            "bounds are the box the API sources are asked over. A project run has it "
            "filled in from the delineated watershed; a standalone call names it."
        ),
    )
