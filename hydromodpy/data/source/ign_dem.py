"""The IGN BD ALTI elevation model behind the data-source port.

Wraps ``data/variables/dem/apis/ign_dem_fr.py``. This is the source that makes
the port's central claim checkable: the Geoplateforme is queried in
**EPSG:2154** while the Sandre WFS and Hub'Eau are queried in WGS84, and a
caller asking both for the same basin passes one extent. That knowledge used to
live in the caller -- ``dem/manager.py`` ran its own ``_resolve_bbox_2154``
while ``hydrography/manager.py`` ran a ``_get_bbox_wgs84`` on the same watershed
shapefile, twenty lines apart. Both are gone: a manager now reads the extent in
the CRS the source it resolved declares.

It is also the only one of the six shipped here that writes: it declares
``writes_out_dir = True`` and lands its archives, its extracted tiles and its
merged GeoTIFF under the directory the request names. The conformance suite
reads the directory back on every source, holds the other three to leaving it
untouched, and runs this one's real prologue to check that what it makes lands
under the directory it was given.

Why the unsupported products are refused when the source is built
-----------------------------------------------------------------
``fetch_ign_dem`` raises ``NotImplementedError`` for RGE ALTI, for any
resolution other than 25 m and for any format other than ASC -- after the
output directory has been created, and with an exception the caller cannot tell
apart from a bug. The adapter checks the same three conditions in its
constructor and raises
:class:`~hydromodpy.core.exceptions.DataCapabilityError`, which is the port's
word for "this implementation does not serve that option". Nothing is downloaded
and nothing is written before the refusal.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_period,
    require_selectors,
)

SERVED_DATASET: Literal["bd-alti"] = "bd-alti"
SERVED_RESOLUTION_M = 25.0
SERVED_FILE_FORMAT = "ASC"
"""The one product ``fetch_ign_dem`` assembles, measured at its own guard.

``ign_dem_fr.py:189-197`` refuses everything else with ``NotImplementedError``.
Repeated here so the refusal happens before a directory is made.
"""


class IgnDemSource:
    """BD ALTI 25 m elevation tiles, merged and cropped to the extent."""

    source_id: ClassVar[str] = "ign-bdalti"
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ("data.geopf.fr",)
    writes_out_dir: ClassVar[bool] = True

    def __init__(
        self,
        *,
        dataset: str = SERVED_DATASET,
        resolution_m: float | None = None,
        file_format: str = SERVED_FILE_FORMAT,
        departments: tuple[str, ...] = (),
        product_crs: str | None = None,
        force_refresh: bool = False,
    ) -> None:
        resolved_resolution = SERVED_RESOLUTION_M if resolution_m is None else float(resolution_m)
        refused = []
        if str(dataset).lower() != SERVED_DATASET:
            refused.append(f"dataset={dataset!r}")
        if resolved_resolution != SERVED_RESOLUTION_M:
            refused.append(f"resolution_m={resolved_resolution!r}")
        if str(file_format).upper() != SERVED_FILE_FORMAT:
            refused.append(f"file_format={file_format!r}")
        if refused:
            raise DataCapabilityError(
                f"Source {self.source_id!r} assembles only "
                f"dataset={SERVED_DATASET!r}, resolution_m={SERVED_RESOLUTION_M}, "
                f"file_format={SERVED_FILE_FORMAT!r}; it was asked for {', '.join(refused)}."
            )
        if isinstance(departments, str):
            raise DataRequestError(
                f"departments={departments!r} is a single string, which would be read one "
                "character per department. Pass a sequence."
            )
        self.dataset: Literal["bd-alti"] = SERVED_DATASET
        self.resolution_m = SERVED_RESOLUTION_M
        self.file_format = SERVED_FILE_FORMAT
        self.departments = tuple(departments)
        # Filters the Geoplateforme catalogue, and is NOT the CRS of the
        # extent: fetch_ign_dem calls it `crs` and forwards it to resource
        # discovery, while the extent is in extent_crs whatever this holds.
        self.product_crs = product_crs
        self.force_refresh = bool(force_refresh)
        self.variables: tuple[str, ...] = ("dem",)
        """One elevation model, whatever the catalogue filter selects."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Assemble one GeoTIFF covering the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)

        from hydromodpy.data.variables.dem.apis.ign_dem_fr import fetch_ign_dem

        merged = fetch_ign_dem(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            departments=list(self.departments) or None,
            dataset=self.dataset,
            resolution_m=self.resolution_m,
            file_format=self.file_format,
            crs=self.product_crs,
            force_refresh=self.force_refresh,
        )
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=None,
            files=(merged,),
            metadata={
                "dataset": self.dataset,
                "resolution_m": self.resolution_m,
                "file_format": self.file_format,
            },
        )


__all__ = [
    "SERVED_DATASET",
    "SERVED_FILE_FORMAT",
    "SERVED_RESOLUTION_M",
    "IgnDemSource",
]
