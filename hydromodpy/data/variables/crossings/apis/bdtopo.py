"""Roads and railways of the IGN BD TOPO, from the Geoplateforme WFS.

Source: ``https://data.geopf.fr/wfs/ows``, layers ``BDTOPO_V3:troncon_de_route``
and ``BDTOPO_V3:troncon_de_voie_ferree``, answered as GeoJSON in EPSG:2154.
Licence: Licence Ouverte Etalab 2.0 (IGN open data since 2021).

What the layers say about a structure, measured on the live service on
2026-10-05 over the upper Ille (Flume) and Rennes:

- ``position_par_rapport_au_sol`` is a signed integer in a string. ``0`` is on
  the ground (98 % of the segments), ``1`` and ``2`` are above it (a bridge or
  a viaduct), ``-1`` and ``-2`` are below it (a tunnel). The road layer has no
  attribute for a culvert: a road over a culvert is a ground segment, and a
  culvert cannot be told from an embankment here.
- ``etat_de_l_objet`` is ``En service`` on every segment seen; the other
  values are skipped. ``fictif`` marks a segment that is not a real road.
- ``nature`` of a road: ``Route a 1 chaussee``, ``Route empierree``, ``Chemin``,
  ``Sentier``, ``Escalier``, ``Bretelle``, ``Rond-point``, ``Type autoroutier``
  and the ferry. A stair or a ferry lays nothing across a channel and is left out.

So a segment above the ground is a ``bridge``, one below it is ``other`` (a
tunnel, which leaves the surface alone), and the rest is ``road`` or
``railway`` by its layer. Geometries come with a third coordinate, dropped here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.data.variables.crossings import records
from hydromodpy.data.variables.crossings.apis import wfs
from hydromodpy.schema.media_types import JSON_MEDIA_TYPE

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.managers.base_manager_common import SourceContext

SOURCE_ID: Final = "bdtopo"
WFS_URL: Final = "https://data.geopf.fr/wfs/ows"
HOST: Final = "data.geopf.fr"

ROAD_LAYER: Final = "BDTOPO_V3:troncon_de_route"
RAILWAY_LAYER: Final = "BDTOPO_V3:troncon_de_voie_ferree"

_NOT_A_STRUCTURE: Final = ("escalier", "bac ")
"""Road ``nature`` prefixes (lower case) that lay nothing across a channel."""

_ROAD_NAMES: Final = (
    "nom_collaboratif_gauche",
    "nom_collaboratif_droite",
    "cpx_toponyme_route_nommee",
)
_RAILWAY_NAMES: Final = ("cpx_toponyme",)

_PROPERTIES: Final = {
    ROAD_LAYER: (
        "geometrie",
        "position_par_rapport_au_sol",
        "etat_de_l_objet",
        "fictif",
        "nature",
        *_ROAD_NAMES,
    ),
    RAILWAY_LAYER: ("geometrie", "position_par_rapport_au_sol", "etat_de_l_objet", *_RAILWAY_NAMES),
}
"""The attributes read, asked by name: a page then weighs a fraction of the full one.
The railway layer has no ``fictif``."""


def fetch_pages(
    source_cfg: Any,
    *,
    bbox: tuple[float, float, float, float],
    context: SourceContext,
) -> Iterator[gpd.GeoDataFrame]:
    """The records of the roads and railways touching *bbox*, one page at a time (EPSG:2154)."""
    del context
    page_size = int(source_cfg.page_size)
    for page in layer_pages(ROAD_LAYER, bbox, page_size):
        yield to_records(page, [])
    for page in layer_pages(RAILWAY_LAYER, bbox, page_size):
        yield to_records([], page)


def to_records(
    road_features: list[dict[str, Any]],
    railway_features: list[dict[str, Any]],
) -> gpd.GeoDataFrame:
    """The records of the two layers, in the fixed columns, EPSG:2154."""
    geometry: list = []
    kind: list[str] = []
    name: list[str] = []
    for layer_kind, names, features in (
        ("road", _ROAD_NAMES, road_features),
        ("railway", _RAILWAY_NAMES, railway_features),
    ):
        for feature in features:
            line = _line(feature)
            props = feature.get("properties") or {}
            if line is None or not _is_a_structure(props, layer_kind):
                continue
            geometry.append(line)
            kind.append(_kind(layer_kind, props.get("position_par_rapport_au_sol")))
            name.append(_first_text(props, names))
    return records.build(
        geometry,
        kind=kind,
        source=SOURCE_ID,
        name=name,
        drop_m=[float("nan")] * len(kind),
        crs=wfs.QUERY_CRS,
    )


def layer_pages(
    typename: str, bbox: tuple[float, float, float, float], page_size: int
) -> Iterator[list[dict[str, Any]]]:
    """The GeoJSON features of one layer, a page at a time."""
    return wfs.iter_pages(
        WFS_URL,
        typename,
        bbox,
        page_size=page_size,
        sort_by="cleabs",
        parse_page=_parse_page,
        identify=lambda feature: feature.get("id"),
        output_format=JSON_MEDIA_TYPE,
        properties=_PROPERTIES[typename],
    )


def _parse_page(body: bytes) -> list[dict[str, Any]]:
    return list(json.loads(body).get("features", []))


def _line(feature: dict[str, Any]) -> Any:
    from shapely import force_2d
    from shapely.geometry import shape

    raw = feature.get("geometry")
    if not raw:
        return None
    geometry = shape(raw)
    if geometry.is_empty or geometry.geom_type not in ("LineString", "MultiLineString"):
        return None
    return force_2d(geometry)


def _is_a_structure(props: dict[str, Any], layer_kind: str) -> bool:
    state = props.get("etat_de_l_objet")
    if state is not None and str(state).strip().lower() != "en service":
        return False
    if props.get("fictif") is True:
        return False
    if layer_kind == "road":
        nature = str(props.get("nature") or "").strip().lower()
        if nature.startswith(_NOT_A_STRUCTURE):
            return False
    return True


def _kind(layer_kind: str, position: Any) -> str:
    try:
        level = int(str(position).strip())
    except (TypeError, ValueError):
        return layer_kind
    if level > 0:
        return "bridge"
    if level < 0:
        return "other"
    return layer_kind


def _first_text(props: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
