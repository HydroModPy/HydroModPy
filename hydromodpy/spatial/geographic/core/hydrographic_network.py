"""Canonical hydrographic-network contract shared across geographic workflows.

Purpose
-------
Expose one common object for hydrographic networks regardless of how they were
obtained:

- loaded from a reference dataset (`data.hydrography`),
- generated from the DEM (`geographic.river_network`),
- projected later into narrower downstream views such as `RiverMeshTrace`.

This module intentionally keeps the contract lightweight and file-oriented so it
can bridge existing managers and preprocessors without forcing an immediate
storage or runtime refactor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import numpy as np

from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from geopandas import GeoDataFrame

    from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts


HydrographicNetworkRole = Literal["reference", "generated", "mesh_constraint", "simulated_active"]
ScalarMetric = float | int | bool | str | None
HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME = "hydrographic_network_reference"
HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME = "hydrographic_network_generated"
HYDROGRAPHIC_NETWORK_SIMULATED_ACTIVE_FEATURE_NAME = "hydrographic_network_simulated_active"
HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME = "river_network"
HYDROGRAPHIC_NETWORK_REFERENCE_VECTOR_FILENAME = "streams.shp"
HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FILENAME = "streams.tif"
HYDROGRAPHIC_NETWORK_GENERATED_VECTOR_FILENAME = "river_network.shp"
HYDROGRAPHIC_NETWORK_GENERATED_SUMMARY_FILENAME = "river_network_summary.json"
HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME = "hydrography_streams"

_ROLE_TO_FEATURE_NAME: dict[str, str] = {
    "reference": HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
    "generated": HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    "simulated_active": HYDROGRAPHIC_NETWORK_SIMULATED_ACTIVE_FEATURE_NAME,
}

_ROLE_TO_LEGACY_FEATURE_NAME: dict[str, str] = {
    "generated": HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME,
}

_ROLE_TO_VECTOR_FILENAME: dict[str, str] = {
    "reference": HYDROGRAPHIC_NETWORK_REFERENCE_VECTOR_FILENAME,
    "generated": HYDROGRAPHIC_NETWORK_GENERATED_VECTOR_FILENAME,
}


def _freeze_mapping(
    mapping: Mapping[str, object] | None,
) -> Mapping[str, object]:
    return MappingProxyType(dict(mapping or {}))


def _string_path(path: str | Path | None) -> str | None:
    if path in (None, ""):
        return None
    return str(path)


def _count_positive_pixels(arr: np.ndarray | None) -> int | None:
    if arr is None:
        return None
    values = np.asarray(arr)
    if values.size == 0:
        return 0
    valid = np.isfinite(values)
    return int(np.count_nonzero((values > 0) & valid))


def _hydrography_field(load_result: object) -> object:
    fields = getattr(load_result, "fields", None) or ()
    for record in fields:
        if getattr(record, "variable", None) == HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME:
            return record
    raise ValueError(
        "Hydrography LoadResult must contain a "
        f"{HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME!r} field."
    )


def _record_metadata(record: object) -> dict[str, object]:
    metadata = getattr(record, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    return {}


def _record_array(record: object) -> np.ndarray | None:
    data = getattr(record, "data", None)
    metadata = _record_metadata(record)
    if hasattr(data, "data_vars"):
        var_name = str(metadata.get("array_name") or getattr(record, "variable", ""))
        if var_name in data.data_vars:
            return np.asarray(data[var_name].values)
        if data.data_vars:
            first_name = next(iter(data.data_vars))
            return np.asarray(data[first_name].values)
        return None
    if hasattr(data, "values"):
        return np.asarray(data.values)
    return None


def _pick_first_column(columns: Iterable[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {str(name).lower(): str(name) for name in columns}
    for candidate in candidates:
        match = lowered.get(candidate.lower())
        if match is not None:
            return match
    return None


def _coerce_crs(crs_like) -> object | None:
    if crs_like in (None, ""):
        return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(crs_like)
    except Exception:
        return None


def _bounds_look_geographic(gdf) -> bool:
    if gdf is None or gdf.empty:
        return True
    minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
    return (
        np.isfinite([minx, miny, maxx, maxy]).all()
        and minx >= -180.0
        and maxx <= 180.0
        and miny >= -90.0
        and maxy <= 90.0
    )


def project_gdf_for_metric_operations(
    gdf,
    *,
    fallback_crs: str | object | None = None,
):
    """Return *gdf* in one projected CRS suitable for metric operations."""
    if gdf is None or gdf.empty:
        return gdf

    out = gdf.copy()
    source_crs = _coerce_crs(out.crs)
    fallback = _coerce_crs(fallback_crs)

    if source_crs is None and fallback is not None:
        out = out.set_crs(fallback, allow_override=True)
        source_crs = fallback
    elif (
        source_crs is not None
        and getattr(source_crs, "is_geographic", False)
        and not _bounds_look_geographic(out)
        and fallback is not None
    ):
        out = out.set_crs(fallback, allow_override=True)
        source_crs = fallback

    if source_crs is None or getattr(source_crs, "is_projected", False):
        return out

    target = None
    try:
        target = out.estimate_utm_crs()
    except Exception:
        target = None
    if target is None and fallback is not None and getattr(fallback, "is_projected", False):
        target = fallback
    if target is None:
        return out
    return out.to_crs(target)


def measure_linework_length_m(
    gdf,
    *,
    fallback_crs: str | object | None = None,
) -> float:
    """Return total line length in metres after coercing to one metric CRS."""
    if gdf is None or gdf.empty:
        return 0.0
    metric_gdf = project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs)
    return float(np.sum(np.asarray(metric_gdf.length, dtype=float)))


def measure_polygon_area_m2(
    gdf,
    *,
    fallback_crs: str | object | None = None,
) -> float:
    """Return total polygon area in m² after coercing to one metric CRS."""
    if gdf is None or gdf.empty:
        return 0.0
    metric_gdf = project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs)
    return float(np.sum(np.asarray(metric_gdf.area, dtype=float)))


def _compute_vector_metrics(
    vector_path: str | Path,
    *,
    watershed_shp: str | Path | None = None,
) -> dict[str, ScalarMetric]:
    import geopandas as gpd

    gdf = gpd.read_file(str(vector_path))
    if gdf.empty:
        metrics: dict[str, ScalarMetric] = {
            "segment_count": 0,
            "network_total_length_m": 0.0,
        }
    else:
        geom = gdf.geometry
        gdf = gdf[(~geom.is_empty) & (~geom.isna())].copy()
        metrics = {
            "segment_count": int(len(gdf)),
            "network_total_length_m": measure_linework_length_m(gdf),
        }
        strahler_field = _pick_first_column(
            gdf.columns,
            ("STRAHLER", "strahler", "strahler_order", "order"),
        )
        if strahler_field is not None:
            values = np.asarray(gdf[strahler_field], dtype=float)
            finite = values[np.isfinite(values)]
            if finite.size > 0:
                metrics["max_strahler_order"] = float(np.max(finite))

    if watershed_shp is None:
        return metrics

    watershed_path = Path(str(watershed_shp))
    if not watershed_path.exists():
        return metrics

    import geopandas as gpd

    watershed = gpd.read_file(str(watershed_path))
    if watershed.empty:
        return metrics

    catchment_area_m2 = measure_polygon_area_m2(watershed, fallback_crs=gdf.crs)
    catchment_area_km2 = float(catchment_area_m2 / 1_000_000.0)
    metrics["catchment_area_km2"] = catchment_area_km2
    length_m = float(metrics.get("network_total_length_m", 0.0) or 0.0)
    if catchment_area_km2 > 0.0:
        metrics["drainage_density_km_per_km2"] = float((length_m / 1000.0) / catchment_area_km2)
    return metrics


def canonical_feature_name_for_role(role: HydrographicNetworkRole | str) -> str | None:
    """Return the canonical store feature name for one hydrographic-network role."""
    return _ROLE_TO_FEATURE_NAME.get(str(role).strip())


def legacy_feature_name_for_role(role: HydrographicNetworkRole | str) -> str | None:
    """Return the historical persisted feature alias for one role, if any."""
    return _ROLE_TO_LEGACY_FEATURE_NAME.get(str(role).strip())


def default_vector_filename_for_role(role: HydrographicNetworkRole | str) -> str | None:
    """Return the historical on-disk vector filename for one role."""
    return _ROLE_TO_VECTOR_FILENAME.get(str(role).strip())


def hydrographic_network_naming_contract(
    role: HydrographicNetworkRole | str,
) -> dict[str, str | None]:
    """Return canonical and legacy naming hints for one hydrographic-network role."""
    role_token = str(role).strip()
    return {
        "role": role_token,
        "canonical_feature_name": canonical_feature_name_for_role(role_token),
        "legacy_feature_name": legacy_feature_name_for_role(role_token),
        "default_vector_filename": default_vector_filename_for_role(role_token),
        "reference_raster_forcing_name": (
            HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME
            if role_token == "reference"
            else None
        ),
    }


@dataclass(frozen=True)
class HydrographicNetwork:
    """Common hydrographic-network contract for reference and generated networks."""

    role: HydrographicNetworkRole
    source_kind: str
    vector_path: str | None = None
    raster_path: str | None = None
    crs: str | None = None
    watershed_shp: str | None = None
    river_mesh_trace: RiverMeshTrace | None = None
    metrics: Mapping[str, ScalarMetric] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid_roles = {"reference", "generated", "mesh_constraint", "simulated_active"}
        if str(self.role) not in valid_roles:
            raise ValueError(
                "role must be one of: reference, generated, mesh_constraint, simulated_active."
            )
        if str(self.source_kind).strip() == "":
            raise ValueError("source_kind cannot be empty")

        object.__setattr__(self, "vector_path", _string_path(self.vector_path))
        object.__setattr__(self, "raster_path", _string_path(self.raster_path))
        object.__setattr__(self, "crs", _string_path(self.crs))
        object.__setattr__(self, "watershed_shp", _string_path(self.watershed_shp))
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    @property
    def has_vector(self) -> bool:
        return self.vector_path is not None and Path(self.vector_path).exists()

    @property
    def has_raster(self) -> bool:
        return self.raster_path is not None and Path(self.raster_path).exists()

    @property
    def canonical_feature_name(self) -> str | None:
        """Canonical geographic-feature key used when this network is persisted."""
        return canonical_feature_name_for_role(self.role)

    def read_vector(self) -> GeoDataFrame | None:
        """Load the vector representation when available."""
        if not self.has_vector:
            return None
        import geopandas as gpd

        return gpd.read_file(str(self.vector_path))

    @classmethod
    def from_hydrography_load_result(
        cls,
        hydrography_load_result,
        *,
        watershed_shp: str | Path | None = None,
        source_kind: str = "hydrography_loaded",
    ) -> HydrographicNetwork:
        """Lift a hydrography LoadResult into the network contract."""
        record = _hydrography_field(hydrography_load_result)
        metadata = _record_metadata(record)
        vector_path = _string_path(metadata.get("vector_path"))
        raster_path = _string_path(metadata.get("raster_path"))
        arr = _record_array(record)

        metrics: dict[str, ScalarMetric] = {}
        crs = str(getattr(record, "crs", "") or "") or None
        if vector_path is not None and Path(vector_path).exists():
            metrics.update(_compute_vector_metrics(vector_path, watershed_shp=watershed_shp))
            try:
                vector = cls(
                    role="reference",
                    source_kind=source_kind,
                    vector_path=vector_path,
                ).read_vector()
                if vector is not None and vector.crs is not None:
                    crs = str(vector.crs)
            except Exception:
                crs = None

        stream_pixel_count = _count_positive_pixels(arr)
        if stream_pixel_count is not None:
            metrics.setdefault("stream_pixel_count", stream_pixel_count)

        return cls(
            role="reference",
            source_kind=source_kind,
            vector_path=vector_path,
            raster_path=raster_path,
            crs=crs,
            watershed_shp=watershed_shp,
            metrics=metrics,
            metadata={"result_type": type(hydrography_load_result).__name__},
        )

    @classmethod
    def from_river_network_products(
        cls,
        river_network_products: RiverNetworkProducts,
        *,
        watershed_shp: str | Path | None = None,
        source_kind: str = "geographic_generated",
    ) -> HydrographicNetwork | None:
        """Lift DEM-derived river-network products into the canonical contract."""
        if not bool(getattr(river_network_products, "enabled", False)):
            return None

        vector_path = _string_path(
            getattr(river_network_products, "hydrographic_network_generated_shp", None)
            or getattr(river_network_products, "network_shp", None)
        )
        raster_path = _string_path(
            getattr(river_network_products, "active_streams_tif", None)
            or getattr(river_network_products, "streams_tif", None)
        )
        crs = _string_path(getattr(river_network_products, "network_crs", None))
        river_mesh_trace = getattr(river_network_products, "river_mesh_trace", None)

        metrics: dict[str, ScalarMetric] = {}
        summary_json = _string_path(
            getattr(river_network_products, "hydrographic_network_generated_summary_json", None)
            or getattr(river_network_products, "summary_json", None)
        )
        if summary_json is not None and Path(summary_json).exists():
            with Path(summary_json).open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            metrics.update(
                {
                    str(key): value
                    for key, value in payload.items()
                    if isinstance(value, (float, int, bool, str)) or value is None
                }
            )
        elif vector_path is not None and Path(vector_path).exists():
            metrics.update(_compute_vector_metrics(vector_path, watershed_shp=watershed_shp))

        return cls(
            role="generated",
            source_kind=source_kind,
            vector_path=vector_path,
            raster_path=raster_path,
            crs=crs,
            watershed_shp=watershed_shp,
            river_mesh_trace=river_mesh_trace,
            metrics=metrics,
            metadata={
                "threshold_cells": getattr(river_network_products, "threshold_cells", None),
                "summary_json": summary_json,
                "stream_order_strahler_tif": _string_path(
                    getattr(river_network_products, "stream_order_strahler_tif", None)
                ),
                "stream_link_id_tif": _string_path(
                    getattr(river_network_products, "stream_link_id_tif", None)
                ),
            },
        )


@dataclass(frozen=True)
class HydrographicNetworks:
    """Optional bundle of canonical hydrographic networks attached to one run/site."""

    reference: HydrographicNetwork | None = None
    generated: HydrographicNetwork | None = None
    simulated_active: HydrographicNetwork | None = None

    def iter_available(self):
        """Yield the available networks in a stable order."""
        for network in (self.reference, self.generated, self.simulated_active):
            if network is not None:
                yield network


__all__ = [
    "HydrographicNetwork",
    "HydrographicNetworks",
    "HydrographicNetworkRole",
    "HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME",
    "HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME",
    "HYDROGRAPHIC_NETWORK_GENERATED_SUMMARY_FILENAME",
    "HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME",
    "HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME",
    "HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FILENAME",
    "HYDROGRAPHIC_NETWORK_REFERENCE_VECTOR_FILENAME",
    "HYDROGRAPHIC_NETWORK_GENERATED_VECTOR_FILENAME",
    "HYDROGRAPHIC_NETWORK_SIMULATED_ACTIVE_FEATURE_NAME",
    "canonical_feature_name_for_role",
    "default_vector_filename_for_role",
    "hydrographic_network_naming_contract",
    "legacy_feature_name_for_role",
    "measure_linework_length_m",
    "measure_polygon_area_m2",
    "project_gdf_for_metric_operations",
]
