"""Geographic-side binders for data-to-structure updates.

These functions bridge geographic outputs (catchment polygons, zone codes) into
domain-level objects (``CatchmentZonesField``, ``Domain.zones``).  They live in
``geographic/`` because they depend on geographic core functions and produce
objects consumed by the domain layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.spatial.catchment_zones_field import CatchmentZonesField
from hydromodpy.spatial.geographic.core.catchment_zones import (
    CatchmentZoneCode,
    build_catchment_zone_codes,
    build_uniform_zone_codes,
)

if TYPE_CHECKING:
    from hydromodpy.spatial.domain import Domain
    from hydromodpy.spatial.field.geology.geology_field import GeologyField


def apply_geology_to_domain(
    *,
    domain: Domain,
    geology: GeologyField | None,
    zone_id: str = "geology",
) -> None:
    """Attach one loaded geology field to the domain zone registry."""
    if geology is None:
        return
    domain.set_zone(zone_id, geology)


def build_catchment_zone_field_from_geographic(
    *,
    geographic: object | None,
) -> tuple[CatchmentZonesField | None, str | None, str | None]:
    """Build one catchment-zone field from legacy or V2 geographic payloads.

    Supported inputs include:
    - legacy ``CatchmentDelineation`` objects exposing ``watershed_shp`` / ``box_buff``,
    - ``DomainGeographicContext`` exposing ``watershed_shp`` / ``box_buff_shp``.

    Returns
    -------
    tuple
        ``(zone_field, zone_codes_tif, note)`` where ``note`` explains why the
        zone field could not be built when the first item is ``None``.
    """
    if geographic is None:
        return None, None, "geographic payload is missing"

    watershed_shp = getattr(geographic, "watershed_shp", None)
    reference_raster = getattr(geographic, "watershed_box_buff_dem", None)
    zone_kind = str(getattr(geographic, "zone_kind", "catchment")).strip().lower()
    if watershed_shp is None:
        return None, None, "watershed shapefile path is missing"
    if reference_raster is None:
        return None, None, "reference raster path is missing"

    catchment_shp = Path(str(watershed_shp))
    reference_raster_path = Path(str(reference_raster))
    geographic_dir = catchment_shp.parent
    zone_codes_tif_path = geographic_dir / "catchment_zone_codes.tif"

    if not reference_raster_path.exists():
        return None, None, f"reference raster not found: {reference_raster_path}"

    if zone_kind == "uniform":
        products = build_uniform_zone_codes(
            reference_raster_path=reference_raster_path,
            zone_codes_tif_path=zone_codes_tif_path,
        )
        zone_field = CatchmentZonesField(
            identifier="catchment_zones",
            encoded_codes=np.asarray(products.zone_codes, dtype=np.uint8),
            encoded_to_zone={
                int(CatchmentZoneCode.UNIFORM): "uniform",
            },
            nodata_code=0,
            source_meta={
                "reference_raster_path": str(reference_raster_path),
                "zone_codes_tif_path": str(zone_codes_tif_path),
                "zone_kind": zone_kind,
            },
        )
        return zone_field, products.zone_codes_tif, None

    box_buff_shp = getattr(geographic, "box_buff_shp", None)
    if box_buff_shp is None:
        box_buff_shp = getattr(geographic, "box_buff", None)
    if box_buff_shp is None:
        return None, None, "buffered domain shapefile path is missing"

    watershed_buff_shp = geographic_dir / "watershed_buff.shp"
    watershed_box_buff_shp = Path(str(box_buff_shp))
    if not catchment_shp.exists():
        return None, None, f"catchment shapefile not found: {catchment_shp}"
    if not watershed_buff_shp.exists():
        return None, None, f"buffered catchment shapefile not found: {watershed_buff_shp}"
    if not watershed_box_buff_shp.exists():
        return None, None, f"buffered domain shapefile not found: {watershed_box_buff_shp}"

    products = build_catchment_zone_codes(
        catchment_shp=catchment_shp,
        watershed_buff_shp=watershed_buff_shp,
        watershed_box_buff_shp=watershed_box_buff_shp,
        reference_raster_path=reference_raster_path,
        zone_codes_tif_path=zone_codes_tif_path,
    )
    zone_field = CatchmentZonesField(
        identifier="catchment_zones",
        encoded_codes=np.asarray(products.zone_codes, dtype=np.uint8),
        encoded_to_zone={
            int(CatchmentZoneCode.DOMAIN_OUTSIDE_BUFFER): "domain",
            int(CatchmentZoneCode.BUFFER_RING): "buffer",
            int(CatchmentZoneCode.CATCHMENT_CORE): "core",
        },
        nodata_code=0,
        source_meta={
            "catchment_shp": str(catchment_shp),
            "watershed_buff_shp": str(watershed_buff_shp),
            "watershed_box_buff_shp": str(watershed_box_buff_shp),
            "reference_raster_path": str(reference_raster_path),
            "zone_codes_tif_path": str(zone_codes_tif_path),
            "zone_kind": zone_kind,
        },
    )
    return zone_field, products.zone_codes_tif, None


def apply_catchment_zones_to_domain(
    *,
    domain: Domain,
    geographic: object | None,
    zone_id: str = "catchment",
) -> None:
    """Attach zone codes built from geographic outputs.

    The binder is intentionally tolerant: when required geographic artifacts are
    missing, it silently skips zone attachment.
    """
    if not hasattr(domain, "set_zone"):
        return

    catchment_zone_field, _, _ = build_catchment_zone_field_from_geographic(
        geographic=geographic,
    )
    if catchment_zone_field is None:
        return
    domain.set_zone(zone_id, catchment_zone_field)
