"""Loaders for support domains used by zone-conformal meshing."""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from hydromodpy.data_managers.variables.geology.io import resolve_data_path
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._domain_contracts import (
    ZoneMeshingDomainConfig,
    ZoneMeshingDomainPayload,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._domain_geometry import (
    geometry_to_summary_payload,
    normalize_polygonal_domain_geometry,
)


def load_zone_meshing_domain_payload_impl(
    config: ZoneMeshingDomainConfig,
    *,
    config_path: str | Path | None = None,
    domain_geographic: object | None = None,
    target_crs=None,
) -> ZoneMeshingDomainPayload:
    """Load one domain geometry and return one typed payload."""
    import geopandas as gpd

    kind = str(config.kind)

    if kind == "bbox":
        if config.bbox is None:  # pragma: no cover - validated upstream
            raise ValueError("bbox domain requires bbox coordinates")
        geometry = box(*config.bbox)
        domain_gdf = gpd.GeoDataFrame(
            {"domain_id": ["bbox_domain"]}, geometry=[geometry], crs=target_crs
        )
        return ZoneMeshingDomainPayload(
            geometry=geometry,
            gdf=domain_gdf,
            summary=geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={"domain_bbox": [round(float(v), 6) for v in config.bbox]},
            ),
        )

    if kind == "geographic_box_buffer":
        return _load_geographic_domain_from_attr(
            attr_name="box_buff_shp",
            domain_id="geographic_box_buffer",
            label="Geographic box-buffer",
            kind=kind,
            domain_geographic=domain_geographic,
            target_crs=target_crs,
        )

    if kind == "geographic_watershed":
        return _load_geographic_domain_from_attr(
            attr_name="watershed_shp",
            domain_id="geographic_watershed",
            label="Geographic watershed",
            kind=kind,
            domain_geographic=domain_geographic,
            target_crs=target_crs,
        )

    if kind == "geographic_watershed_box":
        return _load_geographic_domain_from_attr(
            attr_name="watershed_box_shp",
            domain_id="geographic_watershed_box",
            label="Geographic watershed-box",
            kind=kind,
            domain_geographic=domain_geographic,
            target_crs=target_crs,
        )

    if kind == "polygon":
        if config.coordinates is None:  # pragma: no cover - validated upstream
            raise ValueError("polygon domain requires coordinates")
        geometry = normalize_polygonal_domain_geometry(
            geometry=Polygon(config.coordinates),
            empty_error="polygon domain produced no usable polygon",
        )
        domain_gdf = gpd.GeoDataFrame(
            {"domain_id": ["inline_polygon_domain"]},
            geometry=[geometry],
            crs=target_crs,
        )
        return ZoneMeshingDomainPayload(
            geometry=geometry,
            gdf=domain_gdf,
            summary=geometry_to_summary_payload(
                geometry=geometry,
                kind=kind,
                extras={"domain_vertex_count": int(len(config.coordinates))},
            ),
        )

    return _load_vector_domain(
        config=config,
        kind=kind,
        config_path=config_path,
        target_crs=target_crs,
    )


def _load_geographic_domain_from_attr(
    *,
    attr_name: str,
    domain_id: str,
    label: str,
    kind: str,
    domain_geographic: object | None,
    target_crs,
) -> ZoneMeshingDomainPayload:
    import geopandas as gpd

    if domain_geographic is None:
        raise ValueError(f"domain.kind='{kind}' requires one domain_geographic context.")
    raw_path = getattr(domain_geographic, attr_name, None)
    if raw_path is None:
        raise ValueError(f"domain.kind='{kind}' requires domain_geographic.{attr_name}.")
    source_path = Path(str(raw_path)).expanduser().resolve()
    gdf = gpd.read_file(source_path)
    if gdf.empty:
        raise ValueError(f"{label} domain source has no geometry: {source_path}")
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    if gdf.empty:
        raise ValueError(f"{label} domain source has only empty geometries: {source_path}")
    source_crs = gdf.crs
    if target_crs is not None and source_crs is not None and source_crs != target_crs:
        gdf = gdf.to_crs(target_crs)

    geometry = normalize_polygonal_domain_geometry(
        geometry=unary_union(list(gdf.geometry)),
        empty_error=(
            f"{label} domain produced no usable polygon after cleaning: {source_path}"
        ),
    )
    domain_gdf = gpd.GeoDataFrame(
        {"domain_id": [domain_id]},
        geometry=[geometry],
        crs=gdf.crs,
    )
    return ZoneMeshingDomainPayload(
        geometry=geometry,
        gdf=domain_gdf,
        summary=geometry_to_summary_payload(
            geometry=geometry,
            kind=kind,
            extras={
                "domain_source_path": str(source_path),
                "domain_source_feature_count": int(len(gdf)),
                "domain_crs": None if gdf.crs is None else str(gdf.crs),
            },
        ),
    )


def _load_vector_domain(
    *,
    config: ZoneMeshingDomainConfig,
    kind: str,
    config_path: str | Path | None,
    target_crs,
) -> ZoneMeshingDomainPayload:
    import geopandas as gpd

    if config.path is None:  # pragma: no cover - validated upstream
        raise ValueError("vector domain requires path")
    source_path = Path(resolve_data_path(config.path, config_path=config_path)).resolve()
    gdf = gpd.read_file(source_path)
    if gdf.empty:
        raise ValueError(f"Domain vector source has no geometry: {source_path}")
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    if gdf.empty:
        raise ValueError(f"Domain vector source has only empty geometries: {source_path}")

    n_source_features = int(len(gdf))
    id_field = config.id_field
    selected_id = config.selected_id
    if id_field is not None:
        if id_field not in gdf.columns:
            raise KeyError(f"Missing domain id field '{id_field}' in {source_path}")
        if selected_id is not None:
            gdf = gdf.loc[gdf[id_field].astype(str) == str(selected_id)].copy()
            if gdf.empty:
                raise ValueError(
                    f"Domain vector source contains no feature with "
                    f"{id_field}={selected_id!r}: {source_path}"
                )

    source_crs = gdf.crs
    if target_crs is not None and source_crs is not None and source_crs != target_crs:
        gdf = gdf.to_crs(target_crs)

    geometry = normalize_polygonal_domain_geometry(
        geometry=unary_union(list(gdf.geometry)),
        empty_error=(
            f"Domain vector source produced no usable polygon after cleaning: {source_path}"
        ),
    )
    domain_gdf = gpd.GeoDataFrame(
        {"domain_id": ["domain_source"]},
        geometry=[geometry],
        crs=gdf.crs,
    )
    return ZoneMeshingDomainPayload(
        geometry=geometry,
        gdf=domain_gdf,
        summary=geometry_to_summary_payload(
            geometry=geometry,
            kind=kind,
            extras={
                "domain_source_path": str(source_path),
                "domain_id_field": None if id_field is None else str(id_field),
                "domain_selected_id": None if selected_id is None else str(selected_id),
                "domain_source_feature_count": int(n_source_features),
                "domain_selected_feature_count": int(len(gdf)),
                "domain_crs": None if gdf.crs is None else str(gdf.crs),
            },
        ),
    )
