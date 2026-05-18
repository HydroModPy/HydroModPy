"""STAC Item 1.0 generator for HydroModPy simulations (https://stacspec.org).

Each simulation maps to one ``Item`` with:

- ``bbox`` and ``geometry`` taken from the catalog ``bbox_xmin..bbox_ymax``;
- ``datetime`` set to the period midpoint, plus ``start_datetime`` /
  ``end_datetime`` when the period covers more than one instant;
- ``assets`` describing the Zarr store, every Parquet table, the lockfile
  and any COG produced by the GeoTIFF exporter (when present on disk);
- ``properties.proj:epsg`` and ``properties.proj:wkt2`` from the catalog
  ``crs_epsg`` / ``crs_wkt`` columns.

The payload is a plain ``dict`` so callers can serialise it without
``pystac``; the optional :func:`validate_item` helper relies on
``pystac.Item.from_dict`` when the library is installed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.results.export.context import (
    AssetEntry,
    FairExportContext,
    _is_missing,
    build_context,
    to_json,
)

_LICENSE_URL_TO_SPDX = {
    "https://creativecommons.org/licenses/by/4.0/": "CC-BY-4.0",
    "https://creativecommons.org/licenses/by-sa/4.0/": "CC-BY-SA-4.0",
    "https://creativecommons.org/publicdomain/zero/1.0/": "CC0-1.0",
    "https://spdx.org/licenses/MIT": "MIT",
    "https://spdx.org/licenses/Apache-2.0": "Apache-2.0",
    "https://spdx.org/licenses/etalab-2.0": "etalab-2.0",
    "https://spdx.org/licenses/LicenseRef-proprietary": "proprietary",
}


def _stac_license(url: str) -> str:
    spdx = _LICENSE_URL_TO_SPDX.get(url)
    if spdx:
        return spdx
    if url.startswith(("http://", "https://")):
        return "other"
    return url


STAC_VERSION = "1.0.0"
STAC_EXTENSIONS = ("https://stac-extensions.github.io/projection/v1.1.0/schema.json",)


def _bbox_to_polygon(bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    xmin, ymin, xmax, ymax = bbox
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [xmin, ymin],
                [xmax, ymin],
                [xmax, ymax],
                [xmin, ymax],
                [xmin, ymin],
            ]
        ],
    }


def _to_utc_iso(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _midpoint(start: str | None, end: str | None) -> str:
    if start and end:
        try:
            s = datetime.fromisoformat(start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=UTC)
            if e.tzinfo is None:
                e = e.replace(tzinfo=UTC)
            mid = (s + (e - s) / 2).astimezone(UTC)
            return mid.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return _to_utc_iso(start)
    if start:
        return _to_utc_iso(start)
    if end:
        return _to_utc_iso(end)
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _asset_dict(asset: AssetEntry) -> dict[str, Any]:
    media_type = asset.media_type
    if media_type == "application/zip" and asset.relative_path.endswith(".zarr.zip"):
        media_type = "application/zip; application=zarr"
    payload: dict[str, Any] = {
        "href": asset.relative_path,
        "type": media_type,
        "roles": list(asset.roles),
    }
    if asset.description:
        payload["title"] = asset.description
    extra: dict[str, Any] = {}
    if asset.sha256:
        extra["sha256"] = asset.sha256
    if asset.size_bytes is not None:
        extra["file:size"] = int(asset.size_bytes)
    if asset.key:
        extra["hydromodpy:assetKey"] = asset.key
    if extra:
        payload["extra_fields"] = extra
        payload.update(extra)
    return payload


def build_stac_item(context: FairExportContext) -> dict[str, Any]:
    """Return one STAC ``Item`` for the simulation referenced in *context*."""
    sim_row = context.sim_row
    bbox = context.bbox
    geometry = _bbox_to_polygon(bbox) if bbox is not None else None

    period_start = context.period_start
    period_end = context.period_end
    item_datetime = _midpoint(period_start, period_end)

    def _pick(key: str) -> Any:
        val = sim_row.get(key)
        if _is_missing(val):
            return None
        return val

    properties: dict[str, Any] = {
        "datetime": item_datetime,
        "title": str(_pick("name") or context.sim_id),
        "description": str(_pick("description") or _pick("notes") or ""),
        "license": _stac_license(context.license_url),
        "hydromodpy:simId": context.sim_id,
        "hydromodpy:project": _pick("project"),
        "hydromodpy:solverId": _pick("solver_id"),
        "hydromodpy:simName": _pick("name"),
        "hydromodpy:nCells": _pick("n_cells"),
        "hydromodpy:nLayers": _pick("n_layers"),
        "hydromodpy:nTimesteps": _pick("n_timesteps"),
    }
    if period_start:
        properties["start_datetime"] = _to_utc_iso(period_start)
    if period_end:
        properties["end_datetime"] = _to_utc_iso(period_end)
    crs_epsg = _pick("crs_epsg")
    if crs_epsg is not None:
        properties["proj:epsg"] = int(crs_epsg)
    crs_wkt = _pick("crs_wkt")
    if crs_wkt is not None:
        properties["proj:wkt2"] = str(crs_wkt)
    if context.creator_name:
        properties["created_by"] = context.creator_name
    doi = _pick("doi")
    if doi is not None:
        properties["doi"] = str(doi)

    properties = {
        k: (int(v) if hasattr(v, "__index__") and not isinstance(v, bool) else v)
        for k, v in properties.items()
        if v not in (None, "") and not _is_missing(v)
    }

    assets: dict[str, Any] = {asset.key: _asset_dict(asset) for asset in context.assets}

    links: list[dict[str, Any]] = [
        {
            "rel": "self",
            "href": f"{context.sim_id}.json",
            "type": "application/geo+json",
        }
    ]
    if sim_row.get("project"):
        links.append(
            {
                "rel": "collection",
                "href": "../collection.json",
                "type": "application/json",
                "title": str(sim_row["project"]),
            }
        )

    item: dict[str, Any] = {
        "type": "Feature",
        "stac_version": STAC_VERSION,
        "stac_extensions": list(STAC_EXTENSIONS),
        "id": context.sim_id,
        "collection": str(_pick("project") or "hydromodpy"),
        "geometry": geometry,
        "bbox": list(bbox) if bbox is not None else None,
        "properties": properties,
        "assets": assets,
        "links": links,
    }
    if item["bbox"] is None:
        del item["bbox"]
    if item["geometry"] is None:
        # STAC 1.0 §item-spec allows ``geometry: null`` when bbox is also
        # missing. Keep the field present and explicitly null in that case
        # so validators that look up the key still find it.
        item["geometry"] = None
    return item


def write_stac_item(
    catalog: Any,
    sim_id: str,
    output_path: Path | str,
    *,
    context: FairExportContext | None = None,
) -> Path:
    """Render and write the STAC Item for *sim_id*."""
    ctx = context or build_context(catalog, sim_id)
    item = build_stac_item(ctx)
    out = Path(output_path)
    if out.is_dir() or out.suffix == "":
        out = out / f"{ctx.sim_id}.json"
    return to_json(item, out)


def validate_item(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate an Item dict with pystac when installed.

    Returns ``(True, [])`` when the payload parses correctly, otherwise a
    list of error strings. The function never raises so test suites can
    treat it as advisory.
    """
    try:
        import pystac  # type: ignore[import-not-found]
    except ImportError:
        return False, ["pystac not installed"]
    try:
        pystac.Item.from_dict(payload)
    except Exception as exc:  # noqa: BLE001 - pystac raises a wide hierarchy
        return False, [str(exc)]
    return True, []


def _union_bbox(items: list[dict[str, Any]]) -> list[float] | None:
    """Return the bounding box that encloses every item bbox, or ``None``."""
    boxes = [item.get("bbox") for item in items if item.get("bbox")]
    if not boxes:
        return None
    xmins, ymins, xmaxs, ymaxs = zip(*boxes, strict=False)
    return [float(min(xmins)), float(min(ymins)), float(max(xmaxs)), float(max(ymaxs))]


def _period_extent(items: list[dict[str, Any]]) -> list[list[str | None]]:
    """Return the STAC ``temporal.interval`` covering every item."""
    starts: list[str] = []
    ends: list[str] = []
    for item in items:
        props = item.get("properties", {})
        start = props.get("start_datetime") or props.get("datetime")
        end = props.get("end_datetime") or props.get("datetime")
        if start:
            starts.append(str(start))
        if end:
            ends.append(str(end))
    if not starts and not ends:
        return [[None, None]]
    return [[min(starts) if starts else None, max(ends) if ends else None]]


def build_stac_collection(
    items: list[dict[str, Any]],
    *,
    collection_id: str,
    title: str | None = None,
    description: str | None = None,
    license: str | None = None,
) -> dict[str, Any]:
    """Return a STAC ``Collection`` that groups ``items`` under ``collection_id``."""
    bbox = _union_bbox(items)
    spatial = [bbox] if bbox is not None else [[-180.0, -90.0, 180.0, 90.0]]
    payload: dict[str, Any] = {
        "type": "Collection",
        "stac_version": STAC_VERSION,
        "stac_extensions": list(STAC_EXTENSIONS),
        "id": collection_id,
        "title": title or collection_id,
        "description": description or f"HydroModPy project ``{collection_id}``",
        "license": license or "other",
        "extent": {
            "spatial": {"bbox": spatial},
            "temporal": {"interval": _period_extent(items)},
        },
        "links": [
            {
                "rel": "self",
                "href": "collection.json",
                "type": "application/json",
            },
            {"rel": "root", "href": "../catalog.json", "type": "application/json"},
            *(
                {
                    "rel": "item",
                    "href": f"items/{item['id']}.json",
                    "type": "application/geo+json",
                    "title": item.get("properties", {}).get("title"),
                }
                for item in items
            ),
        ],
        "summaries": {
            "hydromodpy:simCount": [len(items)],
        },
    }
    return payload


def build_stac_catalog(
    *,
    catalog_id: str,
    title: str | None,
    description: str | None,
    collection_ids: list[str],
) -> dict[str, Any]:
    """Return a STAC ``Catalog`` listing every project collection on disk."""
    return {
        "type": "Catalog",
        "stac_version": STAC_VERSION,
        "stac_extensions": list(STAC_EXTENSIONS),
        "id": catalog_id,
        "title": title or catalog_id,
        "description": description or "HydroModPy workspace",
        "links": [
            {
                "rel": "self",
                "href": "catalog.json",
                "type": "application/json",
            },
            *(
                {
                    "rel": "child",
                    "href": f"collections/{coll}/collection.json",
                    "type": "application/json",
                    "title": coll,
                }
                for coll in collection_ids
            ),
        ],
    }


def write_stac_collection(
    items: list[dict[str, Any]],
    output_path: Path | str,
    *,
    collection_id: str,
    title: str | None = None,
    description: str | None = None,
    license: str | None = None,
) -> Path:
    """Render and write a STAC Collection to ``output_path/collection.json``."""
    payload = build_stac_collection(
        items,
        collection_id=collection_id,
        title=title,
        description=description,
        license=license,
    )
    out = Path(output_path)
    if out.is_dir() or out.suffix == "":
        out = out / "collection.json"
    return to_json(payload, out)


def write_stac_catalog(
    output_path: Path | str,
    *,
    catalog_id: str,
    title: str | None = None,
    description: str | None = None,
    collection_ids: list[str] | None = None,
) -> Path:
    """Render and write a STAC Catalog to ``output_path/catalog.json``."""
    payload = build_stac_catalog(
        catalog_id=catalog_id,
        title=title,
        description=description,
        collection_ids=collection_ids or [],
    )
    out = Path(output_path)
    if out.is_dir() or out.suffix == "":
        out = out / "catalog.json"
    return to_json(payload, out)


__all__ = [
    "STAC_EXTENSIONS",
    "STAC_VERSION",
    "build_stac_catalog",
    "build_stac_collection",
    "build_stac_item",
    "validate_item",
    "write_stac_catalog",
    "write_stac_collection",
    "write_stac_item",
]
