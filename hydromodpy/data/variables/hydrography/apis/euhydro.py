"""Fetch hydrography from the EU-Hydro River Network Database (EEA Discomap).

``fetch`` serves the hydrography manager. :class:`EuHydroSource` puts the
same function behind the data-source port. Continental where the
other two ``features`` sources are national, and the one whose request is not a
single call: the adapter's provider function discovers the feature layers of a
MapServer group, then pages each of them. The port sees one question and one
answer, which is what lets a caller ask the three the same way.

``euhydro_page_size`` carries its provider's name because the flat
``[[data.hydrography.sources]]`` section already spent ``page_size`` on BD
Topage, and the generic binder hands a source the section field its constructor
names. The prefix belongs to the section, not to this class, and it goes when
the section becomes a tagged union.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.logging import get_logger
from hydromodpy.data.variables.hydrography.apis.features import FeatureSource

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)

BASE_URL = (
    "https://image.discomap.eea.europa.eu/arcgis/rest/services"
    "/EUHydro/EUHydro_RiverNetworkDatabase/MapServer"
)
_TIMEOUT = 300
_PAGING_GUARD = 2_000_000


def _mapserver_pjson() -> dict:
    r = get_default_client().get(BASE_URL, params={"f": "pjson"}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _feature_layer_ids_in_group(ms: dict, group_name: str) -> list[int]:
    layers = ms.get("layers", [])
    group_ids = {
        ly["id"]
        for ly in layers
        if ly.get("type") == "Group Layer" and ly.get("name") == group_name
    }
    ids: list[int] = []
    for ly in layers:
        if ly.get("type") != "Feature Layer":
            continue
        if ly.get("parentLayerId") in group_ids:
            ids.append(int(ly["id"]))
    # Fallback: any feature layer containing 'Strahler'
    if not ids:
        for ly in layers:
            if ly.get("type") == "Feature Layer" and "Strahler" in (ly.get("name") or ""):
                ids.append(int(ly["id"]))
    return sorted(set(ids))


def _layer_name(layer_id: int) -> str:
    r = get_default_client().get(
        f"{BASE_URL}/{layer_id}",
        params={"f": "pjson"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("name", str(layer_id))


def _query_page_geojson(
    layer_id: int,
    bbox_wgs84: tuple[float, float, float, float],
    offset: int,
    limit: int,
) -> dict:
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    url = f"{BASE_URL}/{layer_id}/query"
    params = {
        "f": "geojson",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "resultOffset": offset,
        "resultRecordCount": limit,
        "orderByFields": "OBJECTID",
    }
    r = get_default_client().get(url, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"ArcGIS error for layer {layer_id}: {data['error']}")
    return data


def _fetch_layer(
    layer_id: int,
    bbox_wgs84: tuple[float, float, float, float],
    page_size: int,
    label: str,
) -> gpd.GeoDataFrame:
    """Download features for a single layer with pagination."""
    import geopandas as gpd

    features: list = []
    offset = 0

    while True:
        data = _query_page_geojson(layer_id, bbox_wgs84, offset, page_size)
        batch = data.get("features", [])
        features.extend(batch)
        got = len(batch)
        logger.debug("[EU-Hydro] %s offset=%d: %d features", label, offset, got)

        if got < page_size and not data.get("exceededTransferLimit", False):
            break
        offset += page_size
        if offset > _PAGING_GUARD:
            raise RuntimeError("Paging guard triggered (too many features).")

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def fetch(
    config: HydrographySourceConfig,
    bbox_wgs84: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Download EU-Hydro features inside *bbox_wgs84*.

    Returns a GeoDataFrame in EPSG:4326.
    """
    import geopandas as gpd
    import pandas as pd

    group_name = config.group_name
    page_size = config.euhydro_page_size

    ms = _mapserver_pjson()
    layer_ids = _feature_layer_ids_in_group(ms, group_name)
    logger.info("[EU-Hydro] feature layers under '%s': %s", group_name, layer_ids)

    if not layer_ids:
        logger.warning("No EU-Hydro feature layers found for group '%s'.", group_name)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    names = {lid: _layer_name(lid) for lid in layer_ids}

    gdfs: list[gpd.GeoDataFrame] = []
    for lid in layer_ids:
        lname = names.get(lid, str(lid))
        gdf = _fetch_layer(lid, bbox_wgs84, page_size, label=lname)
        if not gdf.empty:
            gdf["layer_id"] = lid
            gdf["layer_name"] = lname
            gdfs.append(gdf)

    if not gdfs:
        logger.warning("No EU-Hydro features found in bbox %s", bbox_wgs84)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    combined = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")
    logger.info("[EU-Hydro] fetched %d features total", len(combined))
    return combined


DEFAULT_GROUP_NAME = "River_Net_lines"
DEFAULT_PAGE_SIZE = 1000
"""The two defaults ``HydrographySourceConfig`` declares for this source.

Repeated here rather than imported, for the reason BD Topage gives: the
vocabulary stays importable without pydantic.
``test_the_declared_defaults_match_the_config`` keeps the two in step.
"""


class EuHydroSource(FeatureSource):
    """The EEA EU-Hydro river network, served by the Discomap MapServer."""

    source_id: ClassVar[str] = "euhydro"
    hosts: ClassVar[tuple[str, ...]] = ("image.discomap.eea.europa.eu",)

    def __init__(
        self,
        *,
        group_name: str = DEFAULT_GROUP_NAME,
        euhydro_page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if not isinstance(group_name, str) or not group_name.strip():
            raise DataRequestError(f"EU-Hydro group_name={group_name!r} is empty.")
        if (
            not isinstance(euhydro_page_size, int)
            or isinstance(euhydro_page_size, bool)
            or euhydro_page_size < 1
        ):
            raise DataRequestError(
                f"EU-Hydro euhydro_page_size={euhydro_page_size!r} is not a positive whole "
                "number; a page of zero features never advances and the paging loop would "
                "not end."
            )
        self.group_name = group_name
        self.euhydro_page_size = euhydro_page_size

    def download(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

        config = HydrographySourceConfig(
            source="euhydro",
            group_name=self.group_name,
            euhydro_page_size=self.euhydro_page_size,
        )
        return fetch(config, bbox)

    def metadata(self) -> dict[str, Any]:
        return {"group_name": self.group_name}


__all__ = [
    "DEFAULT_GROUP_NAME",
    "DEFAULT_PAGE_SIZE",
    "EuHydroSource",
    "fetch",
]
