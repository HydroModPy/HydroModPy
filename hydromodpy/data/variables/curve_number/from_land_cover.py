"""The three sources that build a curve number map from land cover.

``land_cover`` reads the user's raster of a named legend, ``worldcover`` the 10 m tiles of
ESA WorldCover, ``ocsge`` the cover polygons of OCS GE. Each one hands its class grid and
the soil group to ``maps.py`` and writes the curve number on the grid of its land cover.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_period,
    require_selectors,
    shipped_hosts,
)
from hydromodpy.data.variables.curve_number.maps import (
    NODATA,
    cache_digest,
    coded,
    crosswalk_of,
    curve_number_grid,
    soil_groups,
    write_grid,
)

if TYPE_CHECKING:
    from hydromodpy.core.runtime.bounds import Bounds

SECTION = "[data.curve_number]"


def fetch_land_cover_curve_number(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    path: Path,
    nomenclature: str,
    hsg: str | None,
    hsg_path: Path | None,
    classes: dict[str, int],
    default_crs: str = "EPSG:2154",
    force_refresh: bool = False,
) -> Path:
    """Write the curve number of the user's land cover raster over ``bbox`` (EPSG:4326)."""
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = cache_digest(bbox, str(path), nomenclature, hsg, classes, hsg_path=hsg_path)
    target = output_dir / f"curve_number_land_cover_{digest}.tif"
    if target.exists() and not force_refresh:
        return target
    with rasterio.open(str(path)) as src:
        crs = str(src.crs) if src.crs else default_crs
        window = from_bounds(*transform_bounds("EPSG:4326", crs, *bbox), src.transform)
        window = window.round_offsets().round_lengths()
        values = src.read(1, window=window, boundless=True, fill_value=src.nodata or 0)
        transform = src.window_transform(window)
        nodata = src.nodata
    labels_grid, labels = coded(values, nodata)
    groups = soil_groups(values.shape, transform, crs, hsg=hsg, hsg_path=hsg_path)
    grid = curve_number_grid(
        labels_grid, labels, crosswalk_of(nomenclature, classes), groups, section=SECTION
    )
    return write_grid(target, grid, transform, crs)


def fetch_worldcover_curve_number(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    year: int,
    hsg: str | None,
    hsg_path: Path | None,
    classes: dict[str, int],
    force_refresh: bool = False,
    bounds: Bounds | None = None,
) -> Path:
    """Write the curve number of ESA WorldCover over ``bbox`` (EPSG:4326)."""
    from hydromodpy.data.common.clients.worldcover import worldcover_classes

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = cache_digest(bbox, year, hsg, classes, hsg_path=hsg_path)
    target = output_dir / f"curve_number_worldcover_{year}_{digest}.tif"
    if target.exists() and not force_refresh:
        return target
    values, transform = worldcover_classes(bbox, year, bounds=bounds)
    labels_grid, labels = coded(values, 0)
    groups = soil_groups(values.shape, transform, "EPSG:4326", hsg=hsg, hsg_path=hsg_path)
    grid = curve_number_grid(
        labels_grid, labels, crosswalk_of("worldcover", classes), groups, section=SECTION
    )
    return write_grid(target, grid, transform, "EPSG:4326")


def fetch_ocsge_curve_number(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    year: int | None,
    hsg: str | None,
    hsg_path: Path | None,
    classes: dict[str, int],
    force_refresh: bool = False,
    bounds: Bounds | None = None,
) -> Path:
    """Write the curve number of OCS GE over ``bbox`` (EPSG:2154), on its 10 m grid."""
    import numpy as np
    import pandas as pd
    from rasterio.features import rasterize

    from hydromodpy.data.common.clients.ocsge import cover_polygons, department_archives, ocsge_grid

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = cache_digest(bbox, year, hsg, classes, hsg_path=hsg_path)
    target = output_dir / f"curve_number_ocsge_{year or 'latest'}_{digest}.tif"
    if target.exists() and not force_refresh:
        return target
    archives, _editions = department_archives(bbox=bbox, year=year, bounds=bounds)
    covers = pd.concat([cover_polygons(archive, bbox) for archive in archives])
    labels = sorted({str(code) for code in covers["code_cs"]})
    index = {label: i for i, label in enumerate(labels)}
    transform, height, width = ocsge_grid(bbox)
    classes_grid = np.full((height, width), -1, dtype=np.int64)
    if not covers.empty:
        classes_grid = rasterize(
            zip(covers.geometry, covers["code_cs"].map(lambda c: index[str(c)]), strict=True),
            out_shape=(height, width),
            transform=transform,
            fill=-1,
            dtype="int32",
        ).astype(np.int64)
    groups = soil_groups((height, width), transform, "EPSG:2154", hsg=hsg, hsg_path=hsg_path)
    grid = curve_number_grid(
        classes_grid, labels, crosswalk_of("ocsge", classes), groups, section=SECTION
    )
    return write_grid(target, grid, transform, "EPSG:2154")


class _LandCoverSource:
    """What the three sources share: the soil group, the overrides, the record they return."""

    section: ClassVar[str] = "curve_number"
    payload_kind: ClassVar[PayloadKind] = "files"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = True
    origin: ClassVar[str] = ""

    def _soil(self, hsg, hsg_path, classes, force_refresh) -> None:
        # The section writes one soil group; a source built without one reads group C.
        self.hsg = hsg if hsg is not None or hsg_path is not None else "C"
        self.hsg_path = None if hsg_path is None else Path(hsg_path)
        self.classes = dict(classes or {})
        self.force_refresh = bool(force_refresh)
        self.variables = ("curve_number",)

    def _result(self, path: Path, extent, metadata: dict) -> FetchResult:
        from hydromodpy.data.contracts.file_record import FileRecord

        record = FileRecord.of(path, state="conditioned", nodata=NODATA, origin=self.origin)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(record,),
            metadata={"hsg": self.hsg, "classes": self.classes, **metadata},
        )


class LandCoverCurveNumber(_LandCoverSource):
    """The user's land cover raster of a named legend, as a source of the curve number."""

    source_id: ClassVar[str] = "land_cover"
    extent_crs: ClassVar[str] = "EPSG:4326"
    origin: ClassVar[str] = "file"

    def __init__(
        self,
        *,
        path: Path | None = None,
        nomenclature: str = "cci",
        hsg: str | None = None,
        hsg_path: Path | None = None,
        classes: dict[str, int] | None = None,
        default_crs: str = "EPSG:2154",
        force_refresh: bool = False,
    ) -> None:
        self.path = None if path is None else Path(path)
        self.nomenclature = nomenclature
        self.default_crs = default_crs
        self._soil(hsg, hsg_path, classes, force_refresh)
        self.hosts: tuple[str, ...] = ()

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Build the curve number of the raster over the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        path = fetch_land_cover_curve_number(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            path=self.path,
            nomenclature=self.nomenclature,
            hsg=self.hsg,
            hsg_path=self.hsg_path,
            classes=self.classes,
            default_crs=self.default_crs,
            force_refresh=self.force_refresh,
        )
        return self._result(path, extent, {"nomenclature": self.nomenclature})


class WorldcoverCurveNumber(_LandCoverSource):
    """ESA WorldCover as a source of the curve number, 10 m, the world."""

    source_id: ClassVar[str] = "worldcover"
    extent_crs: ClassVar[str] = "EPSG:4326"
    origin: ClassVar[str] = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"

    def __init__(
        self,
        *,
        year: int = 2021,
        hsg: str | None = None,
        hsg_path: Path | None = None,
        classes: dict[str, int] | None = None,
        force_refresh: bool = False,
    ) -> None:
        self.year = int(year)
        self._soil(hsg, hsg_path, classes, force_refresh)
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Build the curve number of WorldCover over the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        path = fetch_worldcover_curve_number(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            year=self.year,
            hsg=self.hsg,
            hsg_path=self.hsg_path,
            classes=self.classes,
            force_refresh=self.force_refresh,
            bounds=getattr(request, "bounds", None),
        )
        return self._result(path, extent, {"year": self.year})


class OcsgeCurveNumber(_LandCoverSource):
    """OCS GE of the IGN as a source of the curve number, 10 m, France."""

    source_id: ClassVar[str] = "ocsge"
    extent_crs: ClassVar[str] = "EPSG:2154"
    origin: ClassVar[str] = "https://data.geopf.fr/telechargement/resource/OCSGE"

    def __init__(
        self,
        *,
        year: int | None = None,
        hsg: str | None = None,
        hsg_path: Path | None = None,
        classes: dict[str, int] | None = None,
        force_refresh: bool = False,
    ) -> None:
        self.year = None if year is None else int(year)
        self._soil(hsg, hsg_path, classes, force_refresh)
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Build the curve number of OCS GE over the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        path = fetch_ocsge_curve_number(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            year=self.year,
            hsg=self.hsg,
            hsg_path=self.hsg_path,
            classes=self.classes,
            force_refresh=self.force_refresh,
            bounds=getattr(request, "bounds", None),
        )
        return self._result(path, extent, {"year": self.year})


__all__ = [
    "LandCoverCurveNumber",
    "OcsgeCurveNumber",
    "WorldcoverCurveNumber",
    "fetch_land_cover_curve_number",
    "fetch_ocsge_curve_number",
    "fetch_worldcover_curve_number",
]
