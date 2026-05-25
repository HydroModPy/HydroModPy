"""Reference-network helpers for site-selection outlet snapping."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.candidate_outlets import CandidateOutlet

ReferenceNetworkFetcher = Callable[..., Any]


@dataclass(frozen=True)
class ReferenceNetworkBundle:
    """Loaded hydrographic reference network and audit metadata."""

    source: str
    path: Path | None
    crs: str
    feature_count: int
    bbox_wgs84: tuple[float, float, float, float] | None = None

    def to_manifest_record(self) -> dict[str, Any]:
        """Return a JSON-friendly summary."""

        return {
            "source": self.source,
            "path": "" if self.path is None else str(self.path),
            "crs": self.crs,
            "feature_count": self.feature_count,
            "bbox_wgs84": self.bbox_wgs84,
        }


def load_reference_network_for_outlets(
    *,
    source: str,
    outlets: Iterable[CandidateOutlet],
    target_crs: str,
    output_dir: str | Path,
    path: str | Path | None = None,
    fetch_margin_m: float = 500.0,
    page_size: int = 2000,
    force_refresh: bool = False,
    fetcher: ReferenceNetworkFetcher | None = None,
) -> tuple[Any, ReferenceNetworkBundle]:
    """Load the reference network used before DEM outlet snapping.

    ``bdtopage`` downloads or reuses a run-local GeoPackage. ``custom`` reads
    a local vector file. The returned GeoDataFrame is projected to ``target_crs``.
    """

    if source == "custom":
        if path is None:
            raise ValueError("reference_network_path is required for custom reference networks.")
        return _load_custom_reference_network(path, target_crs=target_crs)

    if source != "bdtopage":
        raise ValueError(f"Unsupported reference network source: {source!r}.")

    return _load_bdtopage_reference_network(
        outlets=list(outlets),
        target_crs=target_crs,
        output_dir=output_dir,
        fetch_margin_m=fetch_margin_m,
        page_size=page_size,
        force_refresh=force_refresh,
        fetcher=fetcher,
    )


def snap_outlet_to_reference_network(
    outlet: CandidateOutlet,
    reference_network: Any,
    *,
    max_distance_m: float,
    source: str,
) -> CandidateOutlet:
    """Project one outlet to the nearest line of a reference network."""

    from shapely.geometry import Point
    from shapely.ops import nearest_points, unary_union

    if max_distance_m <= 0:
        raise ValueError("max_distance_m must be > 0.")

    network = _line_network_in_crs(reference_network, outlet.crs)
    if network.empty:
        raise ValueError(f"Reference network {source!r} contains no line geometry.")

    target = Point(float(outlet.x), float(outlet.y))
    network_union = unary_union(list(network.geometry))
    projected = nearest_points(target, network_union)[1]
    distance_m = float(target.distance(projected))
    if distance_m > float(max_distance_m):
        raise ValueError(
            f"Outlet {outlet.candidate_id!r} is {distance_m:.1f} m from reference "
            f"network {source!r}, above the configured limit {max_distance_m:.1f} m."
        )

    attributes = dict(outlet.attributes)
    attributes.setdefault("station_x", float(outlet.x))
    attributes.setdefault("station_y", float(outlet.y))
    attributes.setdefault("station_crs", outlet.crs)
    attributes.update(
        {
            "reference_network_source": source,
            "reference_network_snap_status": "snapped",
            "reference_network_snap_distance_m": distance_m,
            "reference_network_original_x": float(outlet.x),
            "reference_network_original_y": float(outlet.y),
            "reference_network_x": float(projected.x),
            "reference_network_y": float(projected.y),
        }
    )
    return CandidateOutlet(
        candidate_id=outlet.candidate_id,
        x=float(projected.x),
        y=float(projected.y),
        crs=outlet.crs,
        source=outlet.source,
        source_feature_id=outlet.source_feature_id,
        source_label=outlet.source_label,
        priority=outlet.priority,
        attributes=attributes,
    )


def score_outlets_against_reference_network(
    outlets: Iterable[CandidateOutlet],
    reference_network: Any,
    *,
    max_distance_m: float,
    source: str,
) -> list[CandidateOutlet]:
    """Annotate outlets with distance and normalized score to a reference network."""

    if max_distance_m <= 0:
        raise ValueError("max_distance_m must be > 0.")

    cached_networks: dict[str, Any] = {}
    scored: list[CandidateOutlet] = []
    for outlet in outlets:
        network = cached_networks.get(outlet.crs)
        if network is None:
            network = _line_network_in_crs(reference_network, outlet.crs)
            cached_networks[outlet.crs] = network
        scored.append(
            _score_outlet_against_projected_network(
                outlet,
                network,
                max_distance_m=float(max_distance_m),
                source=source,
            )
        )
    return scored


def _load_custom_reference_network(
    path: str | Path,
    *,
    target_crs: str,
) -> tuple[Any, ReferenceNetworkBundle]:
    import geopandas as gpd

    source_path = Path(path).expanduser().resolve()
    network = gpd.read_file(source_path)
    network = _line_network_in_crs(network, target_crs)
    return network, ReferenceNetworkBundle(
        source="custom",
        path=source_path,
        crs=target_crs,
        feature_count=int(len(network)),
    )


def _load_bdtopage_reference_network(
    *,
    outlets: list[CandidateOutlet],
    target_crs: str,
    output_dir: str | Path,
    fetch_margin_m: float,
    page_size: int,
    force_refresh: bool,
    fetcher: ReferenceNetworkFetcher | None,
) -> tuple[Any, ReferenceNetworkBundle]:
    import geopandas as gpd

    from hydromodpy.data.variables.hydrography.apis.bdtopage import fetch as fetch_bdtopage
    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

    if not outlets:
        raise ValueError("Cannot fetch BD Topage reference network without outlets.")

    destination = Path(output_dir).expanduser().resolve() / "bdtopage_reference_network.gpkg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    bbox_wgs84 = _outlets_bbox_wgs84(
        outlets,
        source_crs=target_crs,
        margin_m=float(fetch_margin_m),
    )

    if destination.is_file() and not force_refresh:
        network = gpd.read_file(destination)
    else:
        cfg = HydrographySourceConfig(source="bdtopage", page_size=int(page_size))
        fetch = fetcher or fetch_bdtopage
        network = fetch(cfg, bbox_wgs84)
        if network.empty:
            raise ValueError("BD Topage returned no feature for the outlet extent.")
        network.to_file(destination, driver="GPKG")

    network = _line_network_in_crs(network, target_crs)
    return network, ReferenceNetworkBundle(
        source="bdtopage",
        path=destination,
        crs=target_crs,
        feature_count=int(len(network)),
        bbox_wgs84=bbox_wgs84,
    )


def _line_network_in_crs(network: Any, target_crs: str):
    if network is None:
        raise ValueError("Reference network is missing.")
    if getattr(network, "empty", False):
        return network
    if getattr(network, "crs", None) is None:
        network = network.set_crs(target_crs, allow_override=True)
    elif str(network.crs) != str(target_crs):
        network = network.to_crs(target_crs)
    return network[network.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()


def _score_outlet_against_projected_network(
    outlet: CandidateOutlet,
    network: Any,
    *,
    max_distance_m: float,
    source: str,
) -> CandidateOutlet:
    from shapely.geometry import Point
    from shapely.ops import nearest_points, unary_union

    attributes = dict(outlet.attributes)
    attributes["reference_network_source"] = source
    if network.empty:
        attributes.update(
            {
                "reference_network_status": "empty_reference_network",
                "reference_network_distance_m": None,
                "reference_network_score": 0.0,
            }
        )
        return _outlet_with_attributes(outlet, attributes)

    point = Point(float(outlet.x), float(outlet.y))
    network_union = unary_union(list(network.geometry))
    projected = nearest_points(point, network_union)[1]
    distance_m = float(point.distance(projected))
    score = max(0.0, 1.0 - min(distance_m / max_distance_m, 1.0))
    status = (
        "within_reference_network_tolerance"
        if distance_m <= max_distance_m
        else "far_from_reference_network"
    )
    attributes.update(
        {
            "reference_network_status": status,
            "reference_network_distance_m": distance_m,
            "reference_network_score": score,
            "reference_network_x": float(projected.x),
            "reference_network_y": float(projected.y),
        }
    )
    return _outlet_with_attributes(outlet, attributes)


def _outlet_with_attributes(
    outlet: CandidateOutlet,
    attributes: dict[str, Any],
) -> CandidateOutlet:
    return CandidateOutlet(
        candidate_id=outlet.candidate_id,
        x=outlet.x,
        y=outlet.y,
        crs=outlet.crs,
        source=outlet.source,
        source_feature_id=outlet.source_feature_id,
        source_label=outlet.source_label,
        priority=outlet.priority,
        attributes=attributes,
    )


def _outlets_bbox_wgs84(
    outlets: Iterable[CandidateOutlet],
    *,
    source_crs: str,
    margin_m: float,
) -> tuple[float, float, float, float]:
    from pyproj import Transformer

    xs = [float(outlet.x) for outlet in outlets]
    ys = [float(outlet.y) for outlet in outlets]
    xmin = min(xs) - margin_m
    xmax = max(xs) + margin_m
    ymin = min(ys) - margin_m
    ymax = max(ys) + margin_m
    transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    corners = [
        transformer.transform(xmin, ymin),
        transformer.transform(xmin, ymax),
        transformer.transform(xmax, ymin),
        transformer.transform(xmax, ymax),
    ]
    lon = [float(x) for x, _y in corners]
    lat = [float(y) for _x, y in corners]
    return (min(lon), min(lat), max(lon), max(lat))


__all__ = [
    "ReferenceNetworkBundle",
    "ReferenceNetworkFetcher",
    "load_reference_network_for_outlets",
    "score_outlets_against_reference_network",
    "snap_outlet_to_reference_network",
]
