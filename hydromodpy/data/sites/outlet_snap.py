"""Move an outlet onto the nearest line of a river network."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

NetworkFetcher = Callable[..., Any]
"""Downloads BD Topage as ``fetcher(bbox_wgs84, page_size=...)``, a frame in EPSG:4326."""

Point2D = tuple[float, float]


def load_network(
    *,
    source: str,
    outlets: Iterable[Point2D],
    target_crs: str,
    output_dir: str | Path,
    fetcher: NetworkFetcher,
    path: str | Path | None = None,
    fetch_margin_m: float = 500.0,
    page_size: int = 2000,
) -> Any:
    """Load the river network in ``target_crs``, as a frame of lines.

    ``bdtopage`` downloads through *fetcher* around the outlets, or reuses the
    GeoPackage of ``output_dir``. ``custom`` reads a local vector file.
    """
    if source in ("file", "custom"):
        if path is None:
            raise ValueError("A file river network needs a path.")
        return _read_file_source(path, target_crs=target_crs)
    if source != "bdtopage":
        raise ValueError(f"Unsupported river network source: {source!r}.")
    return _read_bdtopage(
        outlets=list(outlets),
        target_crs=target_crs,
        output_dir=output_dir,
        fetch_margin_m=fetch_margin_m,
        page_size=page_size,
        fetcher=fetcher,
    )


def snap_outlet(
    site: str,
    outlet: Point2D,
    network: Any,
    *,
    crs: str,
    max_distance_m: float,
    source: str,
) -> Point2D:
    """Project one outlet on the nearest line, or refuse it beyond ``max_distance_m``."""
    from shapely.geometry import Point
    from shapely.ops import nearest_points, unary_union

    if max_distance_m <= 0:
        raise ValueError("max_distance_m must be > 0.")
    lines = _lines_in_crs(network, crs)
    if lines.empty:
        raise ValueError(f"River network {source!r} contains no line geometry.")
    target = Point(float(outlet[0]), float(outlet[1]))
    projected = nearest_points(target, unary_union(list(lines.geometry)))[1]
    distance_m = float(target.distance(projected))
    if distance_m > float(max_distance_m):
        raise ValueError(
            f"Outlet {site!r} is {distance_m:.1f} m from river network {source!r}, "
            f"above the configured limit {max_distance_m:.1f} m."
        )
    return float(projected.x), float(projected.y)


def _read_file_source(path: str | Path, *, target_crs: str) -> Any:
    import geopandas as gpd

    return _lines_in_crs(gpd.read_file(Path(path).expanduser().resolve()), target_crs)


def _read_bdtopage(
    *,
    outlets: list[Point2D],
    target_crs: str,
    output_dir: str | Path,
    fetch_margin_m: float,
    page_size: int,
    fetcher: NetworkFetcher,
) -> Any:
    import geopandas as gpd

    if not outlets:
        raise ValueError("Cannot fetch BD Topage without outlets.")
    destination = Path(output_dir).expanduser().resolve() / "bdtopage_reference_network.gpkg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        network = gpd.read_file(destination)
    else:
        bbox = _outlets_bbox_wgs84(outlets, source_crs=target_crs, margin_m=float(fetch_margin_m))
        network = fetcher(bbox, page_size=int(page_size))
        if network.empty:
            raise ValueError("BD Topage returned no feature for the outlet extent.")
        network.to_file(destination, driver="GPKG")
    return _lines_in_crs(network, target_crs)


def _lines_in_crs(network: Any, target_crs: str) -> Any:
    if network is None:
        raise ValueError("River network is missing.")
    if getattr(network, "empty", False):
        return network
    if getattr(network, "crs", None) is None:
        network = network.set_crs(target_crs, allow_override=True)
    elif str(network.crs) != str(target_crs):
        network = network.to_crs(target_crs)
    return network[network.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()


def _outlets_bbox_wgs84(
    outlets: list[Point2D],
    *,
    source_crs: str,
    margin_m: float,
) -> tuple[float, float, float, float]:
    from pyproj import Transformer

    xs = [float(x) for x, _y in outlets]
    ys = [float(y) for _x, y in outlets]
    xmin, xmax = min(xs) - margin_m, max(xs) + margin_m
    ymin, ymax = min(ys) - margin_m, max(ys) + margin_m
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


__all__ = ["NetworkFetcher", "load_network", "snap_outlet"]
