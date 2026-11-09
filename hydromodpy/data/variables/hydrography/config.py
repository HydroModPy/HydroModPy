"""Pydantic configuration for hydrography data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.families.timeseries_config import UrlSourceFieldsMixin
from hydromodpy.data.source import registry
from hydromodpy.data.variables.hydrography.api_source import NETWORK_PAYLOAD_KIND


class HydrographySourceConfig(UrlSourceFieldsMixin, HydroModelBase):
    """Configuration for one hydrography data source.

    Hydrography sources describe river-network vector or raster data. Use
    ``file`` for local files, and otherwise the id of a source that serves
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
        examples=["file"],
        json_schema_extra={
            "value_docs": {
                "file": "Loads a river network from a local vector or raster file you provide.",
                "osm": "Downloads waterway geometries from OpenStreetMap.",
                "bdtopage": "Downloads every reach of the French BD Topage network from the "
                "Sandre WFS, each with its permanence, and writes the permanent network too.",
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
        description=(
            "Attribute column whose values are written into the stream raster. A column "
            "the layer lacks, or a column of text, is replaced by a sequential number per "
            "feature."
        ),
    )

    # --- BD Topage (Sandre WFS) ---
    page_size: Annotated[int, Profile.DEV] = Field(
        default=50_000,
        description="WFS pagination page size (BD Topage), in features.",
        json_schema_extra=field_metadata(unit="-"),
    )

    # --- EU-Hydro (EEA REST) ---
    group_name: Annotated[str, Profile.DEV] = Field(
        default="River_Net_lines",
        description="MapServer group name for EU-Hydro layer discovery.",
    )
    euhydro_page_size: Annotated[int, Profile.DEV] = Field(
        default=1000,
        description="Pagination page size for EU-Hydro REST queries.",
        json_schema_extra=field_metadata(unit="-"),
    )

    # --- Cache ---
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Download this source again instead of reading the cache.",
    )

    # --- OSM ---
    waterway_types: Annotated[list[str], Profile.DEV] = Field(
        default_factory=lambda: ["river", "stream"],
        description="OSM waterway tag values to fetch.",
    )

    @model_validator(mode="after")
    def _check_file_requires_path(self) -> HydrographySourceConfig:
        if self.source == "file" and self.path is None:
            raise ValueError("File source requires 'path'.")
        return self

    @field_validator("source")
    @classmethod
    def _check_the_name_is_a_source_that_serves_a_network(cls, source: str) -> str:
        """Refuse a name no source answers to, or one that answers with the wrong shape.

        Both refusals are the registry's, re-raised as ``ValueError`` so the
        fault arrives as a configuration error rather than as an exception type
        a configuration reader has no place for.

        On the **field** and not on the model, although only the model validator
        below needs two values: pydantic locates a field validator's fault at
        ``data.hydrography.sources[i].source`` and a model validator's at
        ``data.hydrography.sources[i]``, and a section carrying nine fields
        deserves to be told which one it got wrong.

        The name is resolved within the section this model serves, so the refusal
        a hydrography section can still meet is the payload kind: a plugin
        registered for river linework that answers with grids would be built,
        contacted, and read as a network. Reading the kind off the declaration
        costs one lazy import of the adapter module, and no adapter pulls
        geopandas, rasterio or xarray at import.
        """
        if source in ("file", "url"):
            # A user file is read by the file reader, and a URL only fills the
            # data cache with the file it names; the reader then reads that
            # file, so neither reaches the payload the registry declares.
            return source
        try:
            source_cls = registry.data_sources.get("hydrography", source)
            if getattr(source_cls, "payload_kind", None) != NETWORK_PAYLOAD_KIND:
                raise DataCapabilityError(
                    f"Source {source!r} serves a {source_cls.payload_kind!r} payload, and "
                    "this section accepts a 'features' payload. A source of another kind "
                    "belongs to another variable."
                )
        except (DataRequestError, DataCapabilityError) as exc:
            raise ValueError(str(exc)) from exc
        return source


class HydrographyConfig(HydroModelBase):
    """Top-level hydrography configuration.

    The section lists stream-network sources used by data loading and boundary
    preparation. It is commonly inferred when ``[flow.bc.stream]`` is declared.

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
        json_schema_extra=field_metadata(site_scoped=True),
    )
