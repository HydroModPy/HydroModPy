"""Render map and HTML review artifacts for regional basin-site selections."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INVENTORY_DIR = (
    REPO_ROOT / "docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory"
)
DEFAULT_REGION_RASTER = REPO_ROOT / "examples/data/dem/DEM_armorican_massif.tif"
SITE_INVENTORY_CSV = "bouss_stationary_site_inventory.csv"
MESH_INVENTORY_CSV = "bouss_stationary_mesh_inventory.csv"
GEOJSON_NAME = "bouss_stationary_site_emprises.geojson"
HTML_NAME = "index.html"

SCALE_ORDER = {"10km2": 0, "100km2": 1, "1000km2": 2}
SCALE_COLORS = {
    "10km2": "#2563eb",
    "100km2": "#059669",
    "1000km2": "#dc2626",
}


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    inventory_dir = _resolve_path(args.inventory_dir)
    selection_id = _slug(args.selection_id)
    selection_dir = inventory_dir / "selections" / selection_id
    selection_dir.mkdir(parents=True, exist_ok=True)

    site_rows = _read_csv(inventory_dir / SITE_INVENTORY_CSV)
    mesh_rows = _read_csv(inventory_dir / MESH_INVENTORY_CSV)
    if not site_rows:
        raise FileNotFoundError(
            f"empty or missing site inventory: {inventory_dir / SITE_INVENTORY_CSV}"
        )
    if not mesh_rows:
        raise FileNotFoundError(
            f"empty or missing mesh inventory: {inventory_dir / MESH_INVENTORY_CSV}"
        )

    site_rows = _filter_site_rows(site_rows, args)
    mesh_rows = _filter_mesh_rows(mesh_rows, site_rows, args)
    features = _build_extent_features(mesh_rows, site_rows)
    if not features:
        raise RuntimeError("no mesh extent could be reconstructed for the requested site selection")
    features = _deduplicate_features_by_site(features)
    features = _select_spatially_balanced_features(features, args.max_sites, args.spatial_balance)
    _assign_map_numbers(features)
    selected_site_ids = {f["properties"]["site_id"] for f in features}
    site_rows = [row for row in site_rows if row.get("site_id", "") in selected_site_ids]

    region_bounds = _raster_bounds(_resolve_path(args.region_raster))

    geojson_path = selection_dir / GEOJSON_NAME
    _write_geojson(geojson_path, features)

    map_paths = _write_maps(
        selection_dir,
        features,
        args.map_title or args.selection_label or selection_id,
        _resolve_path(args.region_raster),
        region_bounds,
    )
    html_path = selection_dir / HTML_NAME
    _write_html(
        html_path,
        site_rows,
        mesh_rows,
        features,
        map_paths,
        geojson_path,
        args,
        region_bounds,
    )

    print(f"[written] {geojson_path}")
    for path in map_paths:
        print(f"[written] {path}")
    print(f"[written] {html_path}")
    return 0


def _build_extent_features(
    mesh_rows: list[dict[str, str]], site_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    sites_by_id = {row.get("site_id", ""): row for row in site_rows}
    features: list[dict[str, Any]] = []
    for row in mesh_rows:
        bundle_dir = _resolve_path(row.get("bundle_dir", ""))
        geometry, geometry_source, bounds = _bundle_geometry(bundle_dir)
        if geometry is None or bounds is None:
            continue
        xmin, ymin, xmax, ymax = bounds
        site_id = row.get("site_id", "")
        site = sites_by_id.get(site_id, {})
        feature = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "site_id": site_id,
                "site_label": site.get("site_label", ""),
                "mesh_variant_id": row.get("mesh_variant_id", ""),
                "inventory_source": row.get("inventory_source", ""),
                "cluster_scale": row.get("cluster_scale", ""),
                "cluster_family": row.get("cluster_family", ""),
                "outlet_id": row.get("outlet_id", ""),
                "target_area_km2": site.get("target_area_km2", ""),
                "bundle_cell_count": _coerce_int(row.get("bundle_cell_count")),
                "bundle_boussinesq_steady_ready": _coerce_bool(
                    row.get("bundle_boussinesq_steady_ready")
                ),
                "bundle_boussinesq_transient_ready": _coerce_bool(
                    row.get("bundle_boussinesq_transient_ready")
                ),
                "k_is_heterogeneous": _coerce_bool(row.get("k_is_heterogeneous")),
                "k_unique_count": _coerce_int(row.get("k_unique_count")),
                "cell_area_ratio_max_min": _coerce_float(row.get("cell_area_ratio_max_min")),
                "recommended_stationary_campaign": row.get("recommended_stationary_campaign", ""),
                "inventory_note": row.get("inventory_note", ""),
                "bundle_dir": str(bundle_dir),
                "geometry_source": geometry_source,
                "xmin": xmin,
                "ymin": ymin,
                "xmax": xmax,
                "ymax": ymax,
                "center_x": 0.5 * (xmin + xmax),
                "center_y": 0.5 * (ymin + ymax),
                "width_m": xmax - xmin,
                "height_m": ymax - ymin,
            },
        }
        features.append(feature)
    features.sort(key=_feature_sort_key)
    return features


def _deduplicate_features_by_site(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_site: dict[str, dict[str, Any]] = {}
    for feature in features:
        site_id = str(feature["properties"].get("site_id", ""))
        current = best_by_site.get(site_id)
        if current is None or _feature_priority(feature) < _feature_priority(current):
            best_by_site[site_id] = feature
    return sorted(best_by_site.values(), key=_feature_sort_key)


def _feature_priority(feature: Mapping[str, Any]) -> tuple[int, int, int, str]:
    props = feature["properties"]
    steady_penalty = 0 if props.get("bundle_boussinesq_steady_ready") is True else 1
    hetero_penalty = 0 if props.get("k_is_heterogeneous") is True else 1
    source_penalty = 0 if props.get("inventory_source") == "regional_lab_existing_child" else 1
    return (
        steady_penalty,
        hetero_penalty,
        source_penalty,
        str(props.get("mesh_variant_id", "")),
    )


def _select_spatially_balanced_features(
    features: list[dict[str, Any]], max_sites: int | None, enabled: bool
) -> list[dict[str, Any]]:
    if max_sites is None or max_sites <= 0 or len(features) <= max_sites:
        return features
    if not enabled:
        return features[:max_sites]

    selected = [_westernmost_feature(features)]
    remaining = [feature for feature in features if feature is not selected[0]]
    while remaining and len(selected) < max_sites:
        best = max(remaining, key=lambda feature: _distance_to_selection(feature, selected))
        selected.append(best)
        remaining = [feature for feature in remaining if feature is not best]
    return sorted(selected, key=_feature_sort_key)


def _westernmost_feature(features: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        features,
        key=lambda feature: (
            feature["properties"]["center_x"],
            feature["properties"]["center_y"],
            str(feature["properties"]["site_id"]),
        ),
    )


def _distance_to_selection(feature: Mapping[str, Any], selected: list[dict[str, Any]]) -> float:
    props = feature["properties"]
    x = float(props["center_x"])
    y = float(props["center_y"])
    return min(
        (x - float(other["properties"]["center_x"])) ** 2
        + (y - float(other["properties"]["center_y"])) ** 2
        for other in selected
    )


def _assign_map_numbers(features: list[dict[str, Any]]) -> None:
    for index, feature in enumerate(features, start=1):
        feature["properties"]["map_number"] = index


def _bundle_geometry(
    bundle_dir: Path,
) -> tuple[dict[str, Any] | None, str, tuple[float, float, float, float] | None]:
    boundary_geometry = _boundary_geometry_from_bundle(bundle_dir)
    if boundary_geometry is not None:
        return boundary_geometry, "bundle_boundary_edges", _geometry_bounds(boundary_geometry)

    bounds = _bundle_bounds(bundle_dir)
    if bounds is None:
        return None, "missing", None
    return _bbox_geometry(bounds), "bundle_xy_bounding_box", bounds


def _bundle_bounds(bundle_dir: Path) -> tuple[float, float, float, float] | None:
    nodes_path = bundle_dir / "nodes.csv"
    if nodes_path.is_file():
        bounds = _xy_bounds_from_csv(nodes_path, "x", "y")
        if bounds is not None:
            return bounds
    cells_path = bundle_dir / "cells.csv"
    if cells_path.is_file():
        return _xy_bounds_from_csv(cells_path, "centroid_x", "centroid_y")
    return None


def _boundary_geometry_from_bundle(bundle_dir: Path) -> dict[str, Any] | None:
    nodes = _node_coordinates(bundle_dir / "nodes.csv")
    if not nodes:
        return None
    edges = _boundary_edges(bundle_dir / "edges.csv")
    if not edges:
        return None
    rings = _boundary_rings(edges, nodes)
    if not rings:
        return None
    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": [rings[0]]}
    return {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}


def _node_coordinates(path: Path) -> dict[str, tuple[float, float]]:
    if not path.is_file():
        return {}
    coordinates: dict[str, tuple[float, float]] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            node_id = str(row.get("node_id", "")).strip()
            try:
                coordinates[node_id] = (float(row["x"]), float(row["y"]))
            except (KeyError, TypeError, ValueError):
                continue
    return coordinates


def _boundary_edges(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    edges: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            if str(row.get("edge_kind", "")).strip().lower() != "boundary":
                continue
            node_a = str(row.get("node_a", "")).strip()
            node_b = str(row.get("node_b", "")).strip()
            if node_a and node_b and node_a != node_b:
                edges.append((node_a, node_b))
    return edges


def _boundary_rings(
    edges: list[tuple[str, str]], nodes: Mapping[str, tuple[float, float]]
) -> list[list[list[float]]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    remaining: set[tuple[str, str]] = set()
    for node_a, node_b in edges:
        if node_a not in nodes or node_b not in nodes:
            continue
        key = _edge_key(node_a, node_b)
        remaining.add(key)
        adjacency[node_a].add(node_b)
        adjacency[node_b].add(node_a)

    rings: list[list[list[float]]] = []
    while remaining:
        start_a, start_b = next(iter(remaining))
        loop = [start_a, start_b]
        remaining.remove(_edge_key(start_a, start_b))
        previous = start_a
        current = start_b
        guard = 0
        while current != loop[0] and guard <= len(edges) + 1:
            guard += 1
            candidates = [
                node
                for node in adjacency[current]
                if _edge_key(current, node) in remaining and node != previous
            ]
            if not candidates:
                candidates = [
                    node for node in adjacency[current] if _edge_key(current, node) in remaining
                ]
            if not candidates:
                break
            next_node = sorted(candidates)[0]
            remaining.remove(_edge_key(current, next_node))
            loop.append(next_node)
            previous, current = current, next_node
        if loop[-1] != loop[0]:
            continue
        ring = [[nodes[node][0], nodes[node][1]] for node in loop if node in nodes]
        if len(ring) >= 4:
            rings.append(ring)
    rings.sort(key=_ring_area_abs, reverse=True)
    return rings


def _edge_key(node_a: str, node_b: str) -> tuple[str, str]:
    return tuple(sorted((node_a, node_b)))


def _ring_area_abs(ring: list[list[float]]) -> float:
    if len(ring) < 4:
        return 0.0
    area = 0.0
    for current, nxt in zip(ring, ring[1:], strict=False):
        area += current[0] * nxt[1] - nxt[0] * current[1]
    return abs(0.5 * area)


def _bbox_geometry(bounds: tuple[float, float, float, float]) -> dict[str, Any]:
    xmin, ymin, xmax, ymax = bounds
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


def _geometry_bounds(geometry: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    coords = list(_geometry_coordinates(geometry))
    if not coords:
        return None
    xs = [xy[0] for xy in coords]
    ys = [xy[1] for xy in coords]
    return min(xs), min(ys), max(xs), max(ys)


def _geometry_coordinates(geometry: Mapping[str, Any]) -> Iterable[list[float]]:
    if geometry.get("type") == "Polygon":
        for ring in geometry.get("coordinates", []):
            yield from ring
    elif geometry.get("type") == "MultiPolygon":
        for polygon in geometry.get("coordinates", []):
            for ring in polygon:
                yield from ring


def _xy_bounds_from_csv(
    path: Path, x_column: str, y_column: str
) -> tuple[float, float, float, float] | None:
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    found = False
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            try:
                x = float(row[x_column])
                y = float(row[y_column])
            except (KeyError, TypeError, ValueError):
                continue
            if x != x or y != y:
                continue
            xmin = min(xmin, x)
            ymin = min(ymin, y)
            xmax = max(xmax, x)
            ymax = max(ymax, y)
            found = True
    if not found:
        return None
    return xmin, ymin, xmax, ymax


def _write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    payload = {
        "type": "FeatureCollection",
        "name": "bouss_stationary_site_emprises",
        "crs": {
            "type": "name",
            "properties": {"name": "EPSG:2154"},
        },
        "features": features,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_maps(
    selection_dir: Path,
    features: list[dict[str, Any]],
    selection_id: str,
    region_raster: Path,
    region_bounds: tuple[float, float, float, float] | None,
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    _clear_previous_map_images(selection_dir)
    paths: list[Path] = []
    origin = _map_origin(features, region_bounds)
    fig, ax = plt.subplots(figsize=(12.5, 8.5), constrained_layout=True)
    _add_region_background(ax, region_raster, region_bounds, Rectangle, origin)
    _plot_feature_group(ax, features, origin)
    ax.set_title(_map_title(selection_id))
    _style_map_axes(ax, xlabel="x relatif (km)", ylabel="y relatif (km)", max_ticks=6)
    _style_large_map_text(ax)
    _set_map_limits(
        ax,
        features,
        region_bounds=region_bounds,
        include_region_bounds=True,
        origin=origin,
    )
    path = selection_dir / "map_selection.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    paths.append(path)
    return paths


def _add_region_background(
    ax: Any,
    region_raster: Path,
    region_bounds: tuple[float, float, float, float] | None,
    rectangle_cls: Any,
    origin: tuple[float, float],
) -> None:
    raster = _raster_preview(region_raster)
    has_raster = False
    if raster is not None:
        data, extent, vmin, vmax = raster
        has_raster = True
        rel_extent = _relative_extent(extent, origin)
        ax.imshow(
            data,
            extent=rel_extent,
            origin="upper",
            cmap="terrain",
            alpha=0.55,
            vmin=vmin,
            vmax=vmax,
            zorder=0,
        )
        _add_raster_valid_contour(ax, data, extent, origin)
    if region_bounds is None or has_raster:
        return
    xmin, ymin, xmax, ymax = region_bounds
    rel_xmin, rel_ymin = _relative_xy(xmin, ymin, origin)
    rel_xmax, rel_ymax = _relative_xy(xmax, ymax, origin)
    ax.add_patch(
        rectangle_cls(
            (rel_xmin, rel_ymin),
            rel_xmax - rel_xmin,
            rel_ymax - rel_ymin,
            facecolor="none",
            edgecolor="#111827",
            linewidth=2.0,
            linestyle="-",
            alpha=0.85,
            zorder=1,
        )
    )
    ax.text(
        rel_xmin,
        rel_ymax,
        "region",
        fontsize=17,
        color="#111827",
        ha="left",
        va="bottom",
        zorder=3,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 2.5},
    )


def _plot_feature_group(
    ax: Any, features: list[dict[str, Any]], origin: tuple[float, float]
) -> None:
    from matplotlib.patches import Polygon as PolygonPatch

    label_positions = _label_positions(features, origin)
    for feature in features:
        props = feature["properties"]
        scale = props["cluster_scale"]
        color = SCALE_COLORS.get(scale, "#374151")
        linestyle = "-" if props["bundle_boussinesq_steady_ready"] else "--"
        linewidth = 2.2 if props["k_is_heterogeneous"] else 1.5
        for ring in _geometry_outer_rings(feature["geometry"]):
            rel_ring = [_relative_xy(x, y, origin) for x, y in ring]
            patch = PolygonPatch(
                rel_ring,
                closed=True,
                facecolor=color,
                edgecolor=color,
                alpha=0.24,
                linewidth=linewidth,
                linestyle=linestyle,
                zorder=3,
            )
            ax.add_patch(patch)
        rel_center = _relative_xy(props["center_x"], props["center_y"], origin)
        label_pos = label_positions[int(props.get("map_number", 0))]
        if label_pos != rel_center:
            ax.plot(
                [rel_center[0], label_pos[0]],
                [rel_center[1], label_pos[1]],
                color="#111827",
                linewidth=0.8,
                alpha=0.8,
                zorder=5,
            )
        ax.text(
            label_pos[0],
            label_pos[1],
            str(props.get("map_number", "")),
            fontsize=12,
            fontweight="bold",
            color="#111827",
            ha="center",
            va="center",
            zorder=6,
            bbox={
                "boxstyle": "circle,pad=0.2",
                "facecolor": "white",
                "edgecolor": "#111827",
                "linewidth": 0.75,
                "alpha": 0.9,
            },
        )


def _geometry_outer_rings(geometry: Mapping[str, Any]) -> Iterable[list[list[float]]]:
    if geometry.get("type") == "Polygon":
        coordinates = geometry.get("coordinates", [])
        if coordinates:
            yield coordinates[0]
    elif geometry.get("type") == "MultiPolygon":
        for polygon in geometry.get("coordinates", []):
            if polygon:
                yield polygon[0]


def _label_positions(
    features: list[dict[str, Any]], origin: tuple[float, float], *, threshold_km: float = 13.0
) -> dict[int, tuple[float, float]]:
    centers = {
        int(feature["properties"].get("map_number", 0)): _relative_xy(
            feature["properties"]["center_x"],
            feature["properties"]["center_y"],
            origin,
        )
        for feature in features
    }
    remaining = set(centers)
    positions = dict(centers)
    while remaining:
        seed = min(remaining)
        cluster = {seed}
        changed = True
        while changed:
            changed = False
            for candidate in list(remaining - cluster):
                if any(
                    _distance_km(centers[candidate], centers[member]) <= threshold_km
                    for member in cluster
                ):
                    cluster.add(candidate)
                    changed = True
        remaining -= cluster
        if len(cluster) <= 1:
            continue
        ordered = sorted(cluster)
        cx = sum(centers[item][0] for item in ordered) / len(ordered)
        cy = sum(centers[item][1] for item in ordered) / len(ordered)
        radius = max(8.0, 2.8 * len(ordered))
        for index, item in enumerate(ordered):
            angle = 2.0 * math.pi * index / len(ordered) + 0.35
            positions[item] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
    return positions


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _clear_previous_map_images(selection_dir: Path) -> None:
    for path in selection_dir.glob("map_*.png"):
        path.unlink()


def _map_origin(
    features: list[dict[str, Any]], region_bounds: tuple[float, float, float, float] | None
) -> tuple[float, float]:
    if region_bounds is not None:
        return float(region_bounds[0]), float(region_bounds[1])
    return (
        min(float(feature["properties"]["xmin"]) for feature in features),
        min(float(feature["properties"]["ymin"]) for feature in features),
    )


def _relative_xy(x: float, y: float, origin: tuple[float, float]) -> tuple[float, float]:
    return (float(x) - origin[0]) / 1000.0, (float(y) - origin[1]) / 1000.0


def _relative_extent(
    extent: tuple[float, float, float, float], origin: tuple[float, float]
) -> tuple[float, float, float, float]:
    left, right, bottom, top = extent
    rel_left, rel_bottom = _relative_xy(left, bottom, origin)
    rel_right, rel_top = _relative_xy(right, top, origin)
    return rel_left, rel_right, rel_bottom, rel_top


def _raster_preview(
    path: Path, *, max_pixels_per_axis: int = 900
) -> tuple[Any, tuple[float, float, float, float], float, float] | None:
    if not path.is_file():
        return None
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
    except Exception:
        return None
    try:
        with rasterio.open(path) as dataset:
            scale = max(
                dataset.width / max_pixels_per_axis,
                dataset.height / max_pixels_per_axis,
                1.0,
            )
            width = max(1, int(dataset.width / scale))
            height = max(1, int(dataset.height / scale))
            data = dataset.read(
                1,
                out_shape=(height, width),
                masked=True,
                resampling=Resampling.bilinear,
            )
            if np.ma.is_masked(data) and data.count() <= 0:
                return None
            values = data.compressed() if np.ma.is_masked(data) else data.ravel()
            if values.size <= 0:
                return None
            vmin, vmax = np.nanpercentile(values, [2.0, 98.0])
            bounds = dataset.bounds
            return data, (bounds.left, bounds.right, bounds.bottom, bounds.top), vmin, vmax
    except Exception:
        return None


def _add_raster_valid_contour(
    ax: Any, data: Any, extent: tuple[float, float, float, float], origin: tuple[float, float]
) -> None:
    try:
        import numpy as np

        left, right, bottom, top = extent
        valid = ~np.ma.getmaskarray(data)
        valid &= np.isfinite(np.ma.filled(data, np.nan))
        if valid.sum() <= 0:
            return
        rel_left, rel_bottom = _relative_xy(left, bottom, origin)
        rel_right, rel_top = _relative_xy(right, top, origin)
        x = np.linspace(rel_left, rel_right, valid.shape[1])
        y = np.linspace(rel_top, rel_bottom, valid.shape[0])
        ax.contour(
            x,
            y,
            valid.astype(float),
            levels=[0.5],
            colors="#111827",
            linewidths=2.2,
            alpha=0.9,
            zorder=2,
        )
        ax.text(
            rel_left,
            rel_top,
            "region",
            fontsize=17,
            color="#111827",
            ha="left",
            va="bottom",
            zorder=4,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 2.5},
        )
    except Exception:
        return


def _style_large_map_text(ax: Any) -> None:
    ax.title.set_fontsize(22)
    ax.xaxis.label.set_size(17)
    ax.yaxis.label.set_size(17)
    ax.tick_params(axis="both", which="major", labelsize=15)


def _style_map_axes(
    ax: Any,
    *,
    xlabel: str = "x (m)",
    ylabel: str = "y (m)",
    max_ticks: int = 4,
) -> None:
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_aspect("equal", adjustable="datalim")
    ax.ticklabel_format(useOffset=False, style="plain", axis="both")
    locator_kw = {"nbins": max_ticks, "integer": False, "prune": "both", "steps": [1, 2, 5, 10]}
    ax.xaxis.set_major_locator(MaxNLocator(**locator_kw))
    ax.yaxis.set_major_locator(MaxNLocator(**locator_kw))
    formatter = FuncFormatter(lambda value, _pos: f"{int(value):,}" if abs(value) >= 1 else f"{value:g}")
    ax.xaxis.set_major_formatter(formatter)
    ax.yaxis.set_major_formatter(formatter)
    ax.tick_params(axis="both", which="major", labelsize=9)


def _set_map_limits(
    ax: Any,
    features: list[dict[str, Any]],
    *,
    region_bounds: tuple[float, float, float, float] | None,
    include_region_bounds: bool,
    origin: tuple[float, float],
) -> None:
    xmin = min(f["properties"]["xmin"] for f in features)
    ymin = min(f["properties"]["ymin"] for f in features)
    xmax = max(f["properties"]["xmax"] for f in features)
    ymax = max(f["properties"]["ymax"] for f in features)
    if include_region_bounds and region_bounds is not None:
        rxmin, rymin, rxmax, rymax = region_bounds
        xmin = min(xmin, rxmin)
        ymin = min(ymin, rymin)
        xmax = max(xmax, rxmax)
        ymax = max(ymax, rymax)
    width = xmax - xmin
    height = ymax - ymin
    margin = max(width, height, 1.0) * 0.06
    rel_xmin, rel_ymin = _relative_xy(xmin - margin, ymin - margin, origin)
    rel_xmax, rel_ymax = _relative_xy(xmax + margin, ymax + margin, origin)
    ax.set_xlim(rel_xmin, rel_xmax)
    ax.set_ylim(rel_ymin, rel_ymax)


def _write_html(
    path: Path,
    site_rows: list[dict[str, str]],
    mesh_rows: list[dict[str, str]],
    features: list[dict[str, Any]],
    map_paths: list[Path],
    geojson_path: Path,
    args: argparse.Namespace,
    region_bounds: tuple[float, float, float, float] | None,
) -> None:
    scale_counts = Counter(row.get("cluster_scale", "") for row in site_rows)
    selected_counts = Counter(f["properties"]["cluster_scale"] for f in features)
    map_blocks = "\n".join(
        f"""
        <figure>
          <a href="{html.escape(map_path.name)}">
            <img src="{html.escape(map_path.name)}" alt="Carte des emprises {html.escape(map_path.stem)}">
          </a>
          <figcaption>{html.escape(map_path.name)}</figcaption>
        </figure>
        """
        for map_path in map_paths
    )
    scale_summary = "\n".join(
        "<tr>"
        f"<td>{html.escape(scale)}</td>"
        f"<td>{scale_counts[scale]}</td>"
        f"<td>{selected_counts[scale]}</td>"
        "</tr>"
        for scale in sorted(scale_counts, key=_scale_key)
    )
    selected_table = "\n".join(_feature_row_html(feature) for feature in features)
    selection_summary = _selection_summary_html(args, region_bounds)
    title = args.selection_label or args.selection_id
    payload = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>{_h(title)}</title>
  <style>
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #111827;
      background: #f8fafc;
      font-size: 17px;
    }}
    main {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px 24px 48px;
    }}
    h1, h2 {{
      margin: 0 0 12px;
      letter-spacing: 0;
    }}
    h1 {{ font-size: 36px; }}
    h2 {{ font-size: 26px; margin-top: 32px; }}
    p {{ max-width: 920px; line-height: 1.5; }}
    a {{ color: #1d4ed8; }}
    .maps {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap: 18px;
    }}
    figure {{
      margin: 0;
      background: white;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      padding: 12px;
    }}
    img {{ width: 100%; height: auto; display: block; }}
    figcaption {{ font-size: 16px; color: #4b5563; margin-top: 10px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      border: 1px solid #d1d5db;
      font-size: 16px;
    }}
    th, td {{
      padding: 7px 8px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef2ff;
      font-weight: 650;
    }}
    .table-wrap {{
      max-height: 620px;
      overflow: auto;
      border-radius: 6px;
    }}
    .ok {{ color: #047857; font-weight: 650; }}
    .warn {{ color: #b45309; font-weight: 650; }}
    .muted {{ color: #6b7280; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
  </style>
</head>
<body>
<main>
  <h1>{_h(title)}</h1>
  <p>
    Rapport de choix de bassins versants dans une region. La carte utilise des coordonnees
    relatives en kilometres, un fond topographique regional et des numeros simples pour
    identifier les sites selectionnes.
  </p>
  <p>
    GeoJSON des contours: <a href="{html.escape(geojson_path.name)}"><code>{html.escape(geojson_path.name)}</code></a>.
  </p>

  <h2>Selection</h2>
  {selection_summary}

  <h2>Cartes</h2>
  <section class="maps">
    {map_blocks}
  </section>

  <h2>Couverture par echelle</h2>
  <table>
    <thead><tr><th>Echelle</th><th>Sites filtres</th><th>Sites affiches</th></tr></thead>
    <tbody>{scale_summary}</tbody>
  </table>

  <h2>Bassins selectionnes</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>No.</th><th>Site</th><th>Echelle</th><th>Famille</th><th>Aire cible</th>
          <th>Cellules</th><th>Emprise</th><th>Source contour</th>
        </tr>
      </thead>
      <tbody>{selected_table}</tbody>
    </table>
  </div>
</main>
</body>
</html>
"""
    path.write_text(payload, encoding="utf-8")


def _feature_row_html(feature: Mapping[str, Any]) -> str:
    props = feature["properties"]
    width_km = float(props["width_m"]) / 1000.0
    height_km = float(props["height_m"]) / 1000.0
    extent = f"{width_km:.1f} x {height_km:.1f} km"
    return (
        "<tr>"
        f"<td>{_h(props.get('map_number'))}</td>"
        f"<td><code>{_h(props.get('site_id'))}</code></td>"
        f"<td>{_h(props.get('cluster_scale'))}</td>"
        f"<td>{_h(props.get('cluster_family'))}</td>"
        f"<td>{_h(props.get('target_area_km2'))}</td>"
        f"<td>{_h(props.get('bundle_cell_count'))}</td>"
        f"<td>{_h(extent)}</td>"
        f"<td>{_h(props.get('geometry_source'))}</td>"
        "</tr>"
    )


def _site_row_html(row: Mapping[str, str]) -> str:
    return (
        "<tr>"
        f"<td>{_h(row.get('cluster_scale'))}</td>"
        f"<td><code>{_h(row.get('site_id'))}</code></td>"
        f"<td>{_h(row.get('inventory_source'))}</td>"
        f"<td>{_h(row.get('cluster_family'))}</td>"
        f"<td>{_h(row.get('target_area_km2'))}</td>"
        f"<td>{_h(row.get('preflight_mesh_variant_count'))}</td>"
        f"<td>{_h(row.get('preflight_ready_variant_count'))}</td>"
        f"<td>{_h(row.get('preflight_heterogeneous_ready_variant_count'))}</td>"
        f'<td class="muted">{_h(row.get("inventory_note"))}</td>'
        "</tr>"
    )


def _mesh_row_html(row: Mapping[str, str], extent: Mapping[str, Any]) -> str:
    ready = _coerce_bool(row.get("bundle_boussinesq_steady_ready"))
    hetero = _coerce_bool(row.get("k_is_heterogeneous"))
    extent_text = "missing"
    if extent:
        extent_text = (
            f"{extent['xmin']:.0f}, {extent['ymin']:.0f} - "
            f"{extent['xmax']:.0f}, {extent['ymax']:.0f}"
        )
    return (
        "<tr>"
        f"<td>{_h(row.get('cluster_scale'))}</td>"
        f"<td><code>{_h(row.get('site_id'))}</code></td>"
        f"<td><code>{_h(row.get('mesh_variant_id'))}</code></td>"
        f"<td>{_h(row.get('inventory_source'))}</td>"
        f"<td>{_h(row.get('bundle_cell_count'))}</td>"
        f"<td>{_bool_html(hetero)}</td>"
        f"<td>{_bool_html(ready)}</td>"
        f"<td>{_h(row.get('cell_area_ratio_max_min'))}</td>"
        f'<td><code>{_h(extent_text)}</code><br><span class="muted">{_h(extent.get("geometry_source", "missing"))}</span></td>'
        f'<td class="muted">{_h(row.get("inventory_note"))}</td>'
        "</tr>"
    )


def _bool_html(value: bool | None) -> str:
    if value is True:
        return '<span class="ok">true</span>'
    if value is False:
        return '<span class="warn">false</span>'
    return '<span class="muted">missing</span>'


def _selection_summary_html(
    args: argparse.Namespace, region_bounds: tuple[float, float, float, float] | None
) -> str:
    filters = [
        ("selection_id", args.selection_id),
        ("map_title", args.map_title or args.selection_label or args.selection_id),
        ("scale", ", ".join(args.scale) if args.scale else "all"),
        ("campaign", args.campaign or "all"),
        ("source_selection_id", args.source_selection_id or "all"),
        ("site_group", args.site_group or "all"),
        ("cluster_id", args.cluster_id or "all"),
        ("cluster_family", args.cluster_family or "all"),
        ("tag", args.tag or "all"),
        ("only_steady_ready", str(bool(args.only_steady_ready)).lower()),
        ("only_heterogeneous_ready", str(bool(args.only_heterogeneous_ready)).lower()),
        ("max_sites", "none" if args.max_sites is None else str(args.max_sites)),
        ("spatial_balance", str(bool(args.spatial_balance)).lower()),
        (
            "region_raster",
            str(_resolve_path(args.region_raster)),
        ),
        (
            "region_bounds",
            "missing"
            if region_bounds is None
            else (
                f"{region_bounds[0]:.0f}, {region_bounds[1]:.0f} - "
                f"{region_bounds[2]:.0f}, {region_bounds[3]:.0f}"
            ),
        ),
    ]
    rows = "\n".join(
        f"<tr><td><code>{_h(key)}</code></td><td>{_h(value)}</td></tr>" for key, value in filters
    )
    return f"<table><tbody>{rows}</tbody></table>"


def _filter_site_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    scales = set(args.scale or [])
    for row in rows:
        if scales and row.get("cluster_scale", "") not in scales:
            continue
        if args.campaign and row.get("recommended_stationary_campaign", "") != args.campaign:
            continue
        if (
            args.source_selection_id
            and row.get("source_selection_id", "") != args.source_selection_id
        ):
            continue
        if args.site_group and row.get("site_group", "") != args.site_group:
            continue
        if args.cluster_id and row.get("cluster_id", "") != args.cluster_id:
            continue
        if args.cluster_family and row.get("cluster_family", "") != args.cluster_family:
            continue
        if args.tag and args.tag not in _tag_set(row.get("tags", "")):
            continue
        filtered.append(row)
    return filtered


def _filter_mesh_rows(
    rows: list[dict[str, str]], site_rows: list[dict[str, str]], args: argparse.Namespace
) -> list[dict[str, str]]:
    site_ids = {row.get("site_id", "") for row in site_rows}
    scales = set(args.scale or [])
    filtered: list[dict[str, str]] = []
    for row in rows:
        if row.get("site_id", "") not in site_ids:
            continue
        if scales and row.get("cluster_scale", "") not in scales:
            continue
        if args.campaign and row.get("recommended_stationary_campaign", "") != args.campaign:
            continue
        if args.cluster_family and row.get("cluster_family", "") != args.cluster_family:
            continue
        if (
            args.only_steady_ready
            and _coerce_bool(row.get("bundle_boussinesq_steady_ready")) is not True
        ):
            continue
        if (
            args.only_heterogeneous_ready
            and _coerce_bool(row.get("k_is_heterogeneous")) is not True
        ):
            continue
        filtered.append(row)
    return filtered


def _tag_set(raw: str) -> set[str]:
    return {part.strip() for part in str(raw or "").split(";") if part.strip()}


def _raster_bounds(path: Path) -> tuple[float, float, float, float] | None:
    if not path.is_file():
        return None
    try:
        import rasterio
    except Exception:
        return None
    try:
        with rasterio.open(path) as dataset:
            bounds = dataset.bounds
            return bounds.left, bounds.bottom, bounds.right, bounds.top
    except Exception:
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _resolve_path(path: str | Path) -> Path:
    text = str(path).strip()
    if not text:
        return Path()
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def _feature_sort_key(feature: Mapping[str, Any]) -> tuple[int, str, str]:
    props = feature["properties"]
    return (
        _scale_key(str(props.get("cluster_scale", ""))),
        str(props.get("site_id", "")),
        str(props.get("mesh_variant_id", "")),
    )


def _scale_key(scale: str) -> int:
    return SCALE_ORDER.get(scale, 99)


def _map_title(selection_id: str) -> str:
    return selection_id.replace("_", " ")


def _slug(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "selection"


def _coerce_bool(value: object) -> bool | None:
    text = str(value or "").strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _coerce_int(value: object) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _h(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory-dir",
        default=str(DEFAULT_INVENTORY_DIR),
        help="Directory containing the site and mesh inventory CSV files.",
    )
    parser.add_argument(
        "--selection-id",
        default="strict_stationary_boussinesq_selection",
        help="Stable identifier for this one site-selection HTML report.",
    )
    parser.add_argument(
        "--selection-label",
        default="",
        help="Human-readable title for the site-selection HTML report.",
    )
    parser.add_argument(
        "--map-title",
        default="",
        help="Short title used on the map figure.",
    )
    parser.add_argument(
        "--scale",
        action="append",
        choices=sorted(SCALE_ORDER, key=_scale_key),
        help="Restrict the report to one scale. Repeat to include several scales.",
    )
    parser.add_argument(
        "--campaign",
        default="",
        help="Restrict rows to one recommended_stationary_campaign value.",
    )
    parser.add_argument(
        "--source-selection-id",
        default="",
        help="Restrict site rows to one source_selection_id.",
    )
    parser.add_argument(
        "--site-group",
        default="",
        help="Restrict site rows to one site_group.",
    )
    parser.add_argument(
        "--cluster-id",
        default="",
        help="Restrict site rows to one cluster_id.",
    )
    parser.add_argument(
        "--cluster-family",
        default="",
        help="Restrict rows to one cluster_family, for example headwater.",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="Restrict site rows to rows carrying this semicolon-separated tag.",
    )
    parser.add_argument(
        "--max-sites",
        type=int,
        default=None,
        help="Keep at most this many basin candidates after filtering.",
    )
    parser.add_argument(
        "--spatial-balance",
        action="store_true",
        help="When --max-sites is set, choose a spatially spread subset by farthest-point sampling.",
    )
    parser.add_argument(
        "--only-steady-ready",
        action="store_true",
        help="Keep only mesh variants that are Boussinesq steady-ready.",
    )
    parser.add_argument(
        "--only-heterogeneous-ready",
        action="store_true",
        help="Keep only mesh variants whose bundle K is heterogeneous.",
    )
    parser.add_argument(
        "--region-raster",
        default=str(DEFAULT_REGION_RASTER),
        help="Raster whose bounds are drawn as the regional background contour.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


if __name__ == "__main__":
    raise SystemExit(main())
