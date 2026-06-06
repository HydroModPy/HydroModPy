"""Static figures for site-selection review reports."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.schema.site_selection_manifest import (
    load_selection_manifest,
    manifest_output_path,
)

REPORT_DIR_NAME = "review"
MAP_PNG_NAME = "site_selection_map.png"

AREA_COLOR_CLASSES: tuple[tuple[float, str, str], ...] = (
    (75.0, "<= 75 km2", "#2b83ba"),
    (100.0, "75-100 km2", "#1f9e89"),
    (150.0, "100-150 km2", "#66bd63"),
    (250.0, "150-250 km2", "#fdae61"),
    (500.0, "250-500 km2", "#d95f02"),
    (float("inf"), "> 500 km2", "#7b3294"),
)
UNKNOWN_AREA_COLOR = "#0f766e"
SNAP_LINK_MIN_DISTANCE_M = 250.0
SNAP_LINK_WARN_DISTANCE_M = 1000.0


def render_site_selection_map(
    manifest_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> Path:
    """Render a readable static spatial review map from manifest artifacts."""

    manifest_file = Path(manifest_path).expanduser().resolve()
    manifest = load_selection_manifest(manifest_file)
    output_root = Path(str(manifest.get("output_root") or manifest_file.parent)).resolve()
    destination = _map_output_path(
        manifest,
        manifest_path=manifest_file,
        output_root=output_root,
        output_path=output_path,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    selected_basins = _read_geojson(
        manifest_output_path(manifest, "selected_basins_geojson", manifest_path=manifest_file)
    )
    rejected_basins = _read_geojson(
        manifest_output_path(manifest, "rejected_basins_geojson", manifest_path=manifest_file)
    )
    selected_outlets = _read_geojson(
        manifest_output_path(manifest, "selected_outlets_geojson", manifest_path=manifest_file)
    )
    rejected_outlets = _read_geojson(
        manifest_output_path(manifest, "rejected_outlets_geojson", manifest_path=manifest_file)
    )
    observation_points = _read_geojson(
        manifest_output_path(manifest, "observation_points_geojson", manifest_path=manifest_file)
    )
    generated_network = _read_geojson(
        manifest_output_path(manifest, "generated_network_geojson", manifest_path=manifest_file)
    )
    context_layers = _read_context_layers(manifest, manifest_file=manifest_file)
    dem_path = _dem_path_from_manifest(manifest)
    prefer_dem_extent = _prefer_dem_extent_from_manifest(manifest)

    _write_map_png(
        destination,
        selection_id=str(manifest.get("selection_id") or "site_selection"),
        dem_path=dem_path,
        prefer_dem_extent=prefer_dem_extent,
        context_layers=context_layers,
        selected_basins=_features(selected_basins),
        rejected_basins=_features(rejected_basins),
        selected_outlets=_features(selected_outlets),
        rejected_outlets=_features(rejected_outlets),
        observation_points=_features(observation_points),
        generated_network=_features(generated_network),
    )
    return destination


def _map_output_path(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    output_root: Path,
    output_path: str | Path | None,
) -> Path:
    if output_path is not None:
        return Path(output_path).expanduser().resolve()
    manifest_path_value = manifest_output_path(
        manifest,
        "site_selection_map_png",
        manifest_path=manifest_path,
    )
    if manifest_path_value is not None:
        return manifest_path_value
    return output_root / REPORT_DIR_NAME / MAP_PNG_NAME


def _write_map_png(
    destination: Path,
    *,
    selection_id: str,
    dem_path: Path | None,
    prefer_dem_extent: bool = False,
    context_layers: list[dict[str, Any]],
    selected_basins: list[dict[str, Any]],
    rejected_basins: list[dict[str, Any]],
    selected_outlets: list[dict[str, Any]],
    rejected_outlets: list[dict[str, Any]],
    observation_points: list[dict[str, Any]],
    generated_network: list[dict[str, Any]],
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter

    fig, ax = plt.subplots(figsize=(12.8, 7.4), constrained_layout=True)
    ax.set_facecolor("#eef7fb")
    fig.patch.set_facecolor("white")

    dem_extent = _plot_dem_background(ax, dem_path)
    _plot_context_layers(ax, context_layers)
    _plot_generated_network(ax, generated_network)
    selected_outlet_symbols = _outlets_without_flow_station_marker(
        selected_outlets,
        observation_points,
    )
    _plot_polygons(
        ax,
        rejected_basins,
        facecolor="#fee2e2",
        edgecolor="#b91c1c",
        linewidth=0.4,
        alpha=0.14,
        hatch="",
        zorder=2,
    )
    _plot_area_colored_polygons(
        ax,
        selected_basins,
        linewidth=1.15,
        face_alpha=0.18,
        edge_alpha=0.98,
        zorder=3,
    )
    _plot_snap_links(ax, [*selected_outlet_symbols, *rejected_outlets], observation_points)
    _plot_observation_points(ax, observation_points)
    _plot_points(
        ax,
        rejected_outlets,
        marker="x",
        color="#b91c1c",
        edgecolor="#b91c1c",
        size=26,
        zorder=5,
    )
    _plot_points(
        ax,
        selected_outlet_symbols,
        marker="o",
        color="#ffffff",
        edgecolor="#0f766e",
        size=32,
        zorder=6,
    )

    artifact_bounds = _combined_bounds(
        [
            *generated_network,
            *selected_basins,
            *rejected_basins,
            *selected_outlets,
            *rejected_outlets,
        ]
    )
    bounds = _choose_display_bounds(
        dem_extent,
        artifact_bounds,
        prefer_dem_extent=prefer_dem_extent,
    )
    if bounds is None:
        ax.text(
            0.5,
            0.5,
            "Aucun artefact spatial disponible",
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="#64748b",
            fontsize=13,
        )
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, 1.0)
    else:
        xmin, ymin, xmax, ymax = bounds
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect("equal", adjustable="box")

    ax.set_title(selection_id, loc="left", fontsize=15, fontweight="semibold", pad=12)
    ax.set_xlabel("X Lambert-93 (km)")
    ax.set_ylabel("Y Lambert-93 (km)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.0f}"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.0f}"))
    ax.grid(color="#cbd5e1", linewidth=0.45, alpha=0.38)
    ax.tick_params(labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#94a3b8")
    ax.spines["bottom"].set_color("#94a3b8")
    legend_handles = _legend_handles(
        Patch=Patch,
        Line2D=Line2D,
        selected_basins=selected_basins,
        rejected_basins=rejected_basins,
        rejected_outlets=rejected_outlets,
        selected_outlet_symbols=selected_outlet_symbols,
        observation_points=observation_points,
        generated_network=generated_network,
    )
    if legend_handles:
        ax.legend(
            handles=legend_handles,
            loc="upper left",
            bbox_to_anchor=(1.01, 1.0),
            frameon=True,
            framealpha=0.95,
            fontsize=8,
        )
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_dem_background(
    ax: Any, dem_path: Path | None
) -> tuple[float, float, float, float] | None:
    if dem_path is None or not dem_path.is_file():
        return None
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.plot import plotting_extent
    except ImportError:
        return None

    try:
        with rasterio.open(dem_path) as src:
            max_pixels = 1_500_000
            scale = max((src.width * src.height / max_pixels) ** 0.5, 1.0)
            out_width = max(1, int(src.width / scale))
            out_height = max(1, int(src.height / scale))
            data = src.read(
                1,
                out_shape=(out_height, out_width),
                masked=False,
                resampling=Resampling.bilinear,
            )
            extent = plotting_extent(src)
            bounds = src.bounds
            nodata = src.nodata
    except Exception:
        return None

    if data.size == 0:
        return None
    data = np.asarray(data, dtype=float)
    mask = ~np.isfinite(data)
    if nodata is not None:
        mask |= np.isclose(data, float(nodata))
    mask |= data <= 0.0
    valid = np.ma.masked_array(data, mask=mask)
    if valid.count() == 0:
        return None
    values = valid.compressed()
    vmin, vmax = np.nanpercentile(values, [2, 98])
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
        vmin = float(np.nanmin(values))
        vmax = float(np.nanmax(values))
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    terrain = plt.get_cmap("terrain")
    cmap = ListedColormap(terrain(np.linspace(0.22, 1.0, 256)))
    cmap.set_bad(alpha=0.0)
    ax.imshow(
        valid,
        extent=extent,
        origin="upper",
        cmap=cmap,
        vmin=float(vmin),
        vmax=float(vmax),
        alpha=0.78,
        zorder=-10,
    )
    return float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)


def _plot_context_layers(ax: Any, layers: list[dict[str, Any]]) -> None:
    for layer in layers:
        role = str(layer.get("role") or "other")
        features = [
            feature for feature in layer.get("features", []) if isinstance(feature, Mapping)
        ]
        if role == "territory":
            _plot_polygons(
                ax,
                features,
                facecolor="none",
                edgecolor="#475569",
                linewidth=0.75,
                alpha=0.75,
                hatch="",
                zorder=0,
            )
            _plot_lines(
                ax,
                features,
                color="#475569",
                linewidth=0.75,
                alpha=0.7,
                linestyle="--",
                zorder=0,
            )
        elif role == "hydrography":
            _plot_lines(
                ax,
                features,
                color="#0284c7",
                linewidth=0.55,
                alpha=0.62,
                linestyle="-",
                zorder=1,
            )
        elif role == "geology":
            _plot_polygons(
                ax,
                features,
                facecolor="#fde68a",
                edgecolor="#92400e",
                linewidth=0.45,
                alpha=0.18,
                hatch="",
                zorder=0,
            )
        else:
            _plot_polygons(
                ax,
                features,
                facecolor="#e2e8f0",
                edgecolor="#64748b",
                linewidth=0.45,
                alpha=0.14,
                hatch="",
                zorder=0,
            )
            _plot_lines(
                ax,
                features,
                color="#64748b",
                linewidth=0.45,
                alpha=0.45,
                linestyle="-",
                zorder=0,
            )


def _plot_generated_network(ax: Any, features: list[dict[str, Any]]) -> None:
    if not features:
        return
    _plot_lines(
        ax,
        features,
        color="#0284c7",
        linewidth=0.38,
        alpha=0.46,
        linestyle="-",
        zorder=1,
    )
    point_features = [
        feature for feature in features if _mapping(feature.get("geometry")).get("type") == "Point"
    ]
    _plot_points(
        ax,
        point_features,
        marker=".",
        color="#0284c7",
        edgecolor="#0284c7",
        size=7,
        zorder=1,
    )


def _plot_polygons(
    ax: Any,
    features: Iterable[Mapping[str, Any]],
    *,
    facecolor: str,
    edgecolor: str,
    linewidth: float,
    alpha: float,
    hatch: str,
    zorder: int,
) -> None:
    from matplotlib.patches import Polygon as PolygonPatch

    for feature in features:
        for ring in _polygon_outer_rings(feature.get("geometry")):
            ax.add_patch(
                PolygonPatch(
                    ring,
                    closed=True,
                    facecolor=facecolor,
                    edgecolor=edgecolor,
                    linewidth=linewidth,
                    alpha=alpha,
                    hatch=hatch,
                    zorder=zorder,
                )
            )


def _plot_area_colored_polygons(
    ax: Any,
    features: Iterable[Mapping[str, Any]],
    *,
    linewidth: float,
    face_alpha: float,
    edge_alpha: float,
    zorder: int,
) -> None:
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Polygon as PolygonPatch

    for feature in features:
        _, color = _area_class_for_feature(feature)
        for ring in _polygon_outer_rings(feature.get("geometry")):
            ax.add_patch(
                PolygonPatch(
                    ring,
                    closed=True,
                    facecolor=to_rgba(color, face_alpha),
                    edgecolor=to_rgba(color, edge_alpha),
                    linewidth=linewidth,
                    zorder=zorder,
                )
            )


def _plot_lines(
    ax: Any,
    features: Iterable[Mapping[str, Any]],
    *,
    color: str,
    linewidth: float,
    alpha: float,
    linestyle: str,
    zorder: int,
) -> None:
    for feature in features:
        for line in _line_strings(feature.get("geometry")):
            if len(line) < 2:
                continue
            xs = [point[0] for point in line]
            ys = [point[1] for point in line]
            ax.plot(
                xs,
                ys,
                color=color,
                linewidth=linewidth,
                alpha=alpha,
                linestyle=linestyle,
                zorder=zorder,
            )


def _plot_points(
    ax: Any,
    features: Iterable[Mapping[str, Any]],
    *,
    marker: str,
    color: str,
    edgecolor: str,
    size: float,
    zorder: int,
) -> None:
    points = [_point_xy(feature.get("geometry")) for feature in features]
    clean = [point for point in points if point is not None]
    if not clean:
        return
    xs = [point[0] for point in clean]
    ys = [point[1] for point in clean]
    scatter_kwargs = {
        "marker": marker,
        "s": size,
        "c": color,
        "linewidths": 0.85,
        "zorder": zorder,
    }
    if marker != "x":
        scatter_kwargs["edgecolors"] = edgecolor
    ax.scatter(xs, ys, **scatter_kwargs)


def _plot_observation_points(ax: Any, features: list[dict[str, Any]]) -> None:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feature in features:
        props = _mapping(feature.get("properties"))
        by_type[str(props.get("observation_type") or "other")].append(feature)
    styles = {
        "flow_station": ("^", "#2563eb", "#1e3a8a", 24),
        "piezometer": ("s", "#7c3aed", "#4c1d95", 22),
        "other": ("D", "#64748b", "#334155", 22),
    }
    for observation_type, typed_features in sorted(by_type.items()):
        marker, color, edgecolor, size = styles.get(observation_type, styles["other"])
        _plot_points(
            ax,
            typed_features,
            marker=marker,
            color=color,
            edgecolor=edgecolor,
            size=size,
            zorder=4,
        )


def _plot_snap_links(
    ax: Any,
    outlet_features: list[dict[str, Any]],
    observation_points: list[dict[str, Any]],
) -> None:
    flow_stations_by_site: dict[str, tuple[float, float]] = {}
    for feature in observation_points:
        props = _mapping(feature.get("properties"))
        if str(props.get("observation_type") or "") != "flow_station":
            continue
        site_id = str(props.get("site_id") or "").strip()
        point = _point_xy(feature.get("geometry"))
        if site_id and point is not None:
            flow_stations_by_site[site_id] = point

    for outlet in outlet_features:
        props = _mapping(outlet.get("properties"))
        if str(props.get("outlet_geometry_source") or "") != "snapped":
            continue
        site_id = str(props.get("site_id") or outlet.get("id") or "").strip()
        station = flow_stations_by_site.get(site_id)
        outlet_point = _point_xy(outlet.get("geometry"))
        if station is None or outlet_point is None:
            continue
        distance_m = _float_or_none(props.get("outlet_snap_distance_m"))
        if distance_m is not None and distance_m < SNAP_LINK_MIN_DISTANCE_M:
            continue
        color = "#b45309" if (distance_m or 0.0) >= SNAP_LINK_WARN_DISTANCE_M else "#64748b"
        ax.plot(
            [station[0], outlet_point[0]],
            [station[1], outlet_point[1]],
            color=color,
            linewidth=0.55,
            alpha=0.62,
            linestyle=(0, (2.5, 2.5)),
            zorder=3,
        )


def _outlets_without_flow_station_marker(
    outlets: list[dict[str, Any]],
    observation_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only selected outlet points not already shown as hydrometric stations."""

    flow_site_ids: set[str] = set()
    flow_feature_ids: set[str] = set()
    flow_xy: set[tuple[float, float]] = set()
    for feature in observation_points:
        props = _mapping(feature.get("properties"))
        if str(props.get("observation_type") or "") != "flow_station":
            continue
        site_id = str(props.get("site_id") or "").strip()
        feature_id = str(props.get("feature_id") or "").strip()
        if site_id:
            flow_site_ids.add(site_id)
        if feature_id:
            flow_feature_ids.add(feature_id)
        point = _point_xy(feature.get("geometry"))
        if point is not None:
            flow_xy.add(_rounded_xy(point))

    filtered: list[dict[str, Any]] = []
    for outlet in outlets:
        props = _mapping(outlet.get("properties"))
        site_id = str(props.get("site_id") or outlet.get("id") or "").strip()
        source_feature_id = str(
            props.get("source_feature_id") or props.get("candidate_id") or ""
        ).strip()
        point = _point_xy(outlet.get("geometry"))
        if point is not None and _rounded_xy(point) in flow_xy:
            continue
        if str(props.get("outlet_geometry_source") or "") != "snapped":
            if site_id and site_id in flow_site_ids:
                continue
            if source_feature_id and source_feature_id in flow_feature_ids:
                continue
        filtered.append(outlet)
    return filtered


def _rounded_xy(point: tuple[float, float]) -> tuple[float, float]:
    return (round(float(point[0]), 3), round(float(point[1]), 3))


def _label_selected_sites(ax: Any, features: list[dict[str, Any]]) -> None:
    offsets = [(5, 5), (5, -10), (-38, 5), (-38, -10), (8, 14)]
    for index, feature in enumerate(features[:35]):
        point = _point_xy(feature.get("geometry"))
        if point is None:
            continue
        props = _mapping(feature.get("properties"))
        label = str(props.get("site_id") or feature.get("id") or "")
        if not label:
            continue
        ax.annotate(
            label,
            xy=point,
            xytext=offsets[index % len(offsets)],
            textcoords="offset points",
            fontsize=7.5,
            color="#134e4a",
            bbox={
                "boxstyle": "round,pad=0.18",
                "facecolor": "white",
                "edgecolor": "#99f6e4",
                "alpha": 0.9,
            },
            zorder=8,
        )


def _legend_handles(
    *,
    Patch: Any,
    Line2D: Any,
    selected_basins: list[dict[str, Any]],
    rejected_basins: list[dict[str, Any]],
    rejected_outlets: list[dict[str, Any]],
    selected_outlet_symbols: list[dict[str, Any]],
    observation_points: list[dict[str, Any]],
    generated_network: list[dict[str, Any]],
) -> list[Any]:
    handles: list[Any] = []
    observation_types = _observation_types(observation_points)
    if generated_network:
        handles.append(
            Line2D(
                [0],
                [0],
                color="#0284c7",
                linewidth=0.8,
                alpha=0.7,
                label="Reseau DEM genere",
            )
        )
    handles.extend(_area_legend_handles(Patch=Patch, selected_basins=selected_basins))
    if rejected_basins:
        handles.append(
            Patch(
                facecolor="#fee2e2",
                edgecolor="#b91c1c",
                alpha=0.14,
                label="Bassin rejete",
            )
        )
    if "flow_station" in observation_types:
        handles.append(
            Line2D(
                [0],
                [0],
                marker="^",
                color="none",
                markerfacecolor="#2563eb",
                markeredgecolor="#1e3a8a",
                markersize=5.5,
                label="Station hydro",
            )
        )
    if "piezometer" in observation_types:
        handles.append(
            Line2D(
                [0],
                [0],
                marker="s",
                color="none",
                markerfacecolor="#7c3aed",
                markeredgecolor="#4c1d95",
                markersize=5.5,
                label="Station piezo",
            )
        )
    if selected_outlet_symbols:
        handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor="white",
                markeredgecolor="#0f766e",
                markersize=5.5,
                label="Exutoire retenu",
            )
        )
    if _has_visible_snap_links([*selected_outlet_symbols, *rejected_outlets], observation_points):
        handles.append(
            Line2D(
                [0],
                [0],
                color="#b45309",
                linestyle=(0, (2.5, 2.5)),
                linewidth=0.8,
                label="Deplacement station -> exutoire",
            )
        )
    if rejected_outlets:
        handles.append(
            Line2D(
                [0],
                [0],
                marker="x",
                color="#b91c1c",
                linestyle="none",
                markersize=5.5,
                label="Exutoire rejete",
            )
        )
    return handles


def _has_visible_snap_links(
    outlet_features: list[dict[str, Any]],
    observation_points: list[dict[str, Any]],
) -> bool:
    flow_site_ids = {
        str(_mapping(feature.get("properties")).get("site_id") or "").strip()
        for feature in observation_points
        if str(_mapping(feature.get("properties")).get("observation_type") or "") == "flow_station"
    }
    for outlet in outlet_features:
        props = _mapping(outlet.get("properties"))
        if str(props.get("outlet_geometry_source") or "") != "snapped":
            continue
        site_id = str(props.get("site_id") or outlet.get("id") or "").strip()
        distance_m = _float_or_none(props.get("outlet_snap_distance_m"))
        if site_id in flow_site_ids and (
            distance_m is None or distance_m >= SNAP_LINK_MIN_DISTANCE_M
        ):
            return True
    return False


def _area_legend_handles(*, Patch: Any, selected_basins: list[dict[str, Any]]) -> list[Any]:
    classes_present: dict[str, str] = {}
    for feature in selected_basins:
        label, color = _area_class_for_feature(feature)
        classes_present[label] = color
    handles: list[Any] = []
    for _, label, color in AREA_COLOR_CLASSES:
        if label in classes_present:
            handles.append(
                Patch(facecolor=color, edgecolor=color, alpha=0.32, label=f"Bassin {label}")
            )
    if "surface non renseignee" in classes_present:
        handles.append(
            Patch(
                facecolor=classes_present["surface non renseignee"],
                edgecolor=classes_present["surface non renseignee"],
                alpha=0.32,
                label="Bassin surface non renseignee",
            )
        )
    return handles


def _area_class_for_feature(feature: Mapping[str, Any]) -> tuple[str, str]:
    area_km2 = _area_km2_from_feature(feature)
    if area_km2 is None:
        return "surface non renseignee", UNKNOWN_AREA_COLOR
    for max_area, label, color in AREA_COLOR_CLASSES:
        if area_km2 <= max_area:
            return label, color
    return "> 500 km2", AREA_COLOR_CLASSES[-1][2]


def _area_km2_from_feature(feature: Mapping[str, Any]) -> float | None:
    props = _mapping(feature.get("properties"))
    for key in ("area_km2", "computed_area_km2", "surface_bv_km2", "surface_km2"):
        value = props.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _observation_types(features: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for feature in features:
        props = _mapping(feature.get("properties"))
        observation_type = str(props.get("observation_type") or "").strip()
        if observation_type:
            values.add(observation_type)
    return values


def _map_note(
    *, dem_path: Path | None, dem_extent: tuple[float, float, float, float] | None
) -> str:
    if dem_path is not None and dem_extent is not None:
        return "Fond DEM regional; contours calcules depuis les exutoires"
    return "Contours calcules depuis les exutoires quand les produits DEM sont disponibles"


def _add_count_box(
    ax: Any,
    *,
    selected_basins: list[dict[str, Any]],
    rejected_basins: list[dict[str, Any]],
    selected_outlets: list[dict[str, Any]],
    rejected_outlets: list[dict[str, Any]],
) -> None:
    lines = [
        f"Bassins retenus: {len(selected_basins)}",
        f"Bassins rejetes: {len(rejected_basins)}",
        f"Exutoires retenus: {len(selected_outlets)}",
        f"Exutoires rejetes: {len(rejected_outlets)}",
    ]
    ax.text(
        0.01,
        0.99,
        "\n".join(lines),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
        color="#334155",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "white",
            "edgecolor": "#cbd5e1",
            "alpha": 0.95,
        },
        zorder=10,
    )


def _read_geojson(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_context_layers(
    manifest: Mapping[str, Any], *, manifest_file: Path
) -> list[dict[str, Any]]:
    context = _mapping(manifest.get("map_context"))
    raw_layers = context.get("layers")
    if not isinstance(raw_layers, list):
        return []
    output_root = Path(str(manifest.get("output_root") or manifest_file.parent)).expanduser()
    if output_root.is_absolute():
        output_root = output_root.resolve()
    else:
        output_root = (manifest_file.parent / output_root).resolve()

    layers: list[dict[str, Any]] = []
    for raw_layer in raw_layers:
        if not isinstance(raw_layer, Mapping):
            continue
        raw_path = raw_layer.get("path")
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = (output_root / path).resolve()
        if not path.is_file():
            continue
        try:
            collection = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        layers.append(
            {
                "name": str(raw_layer.get("name") or path.stem),
                "role": str(raw_layer.get("role") or "other"),
                "path": str(path),
                "features": _features(collection),
            }
        )
    return layers


def _dem_path_from_manifest(manifest: Mapping[str, Any]) -> Path | None:
    flow_products = _mapping(manifest.get("flow_products"))
    value = (
        flow_products.get("map_dem_path")
        or flow_products.get("dem_path")
        or flow_products.get("dem_corrected_path")
    )
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        output_root = Path(str(manifest.get("output_root") or ".")).expanduser().resolve()
        path = output_root / path
    return path.resolve()


def _prefer_dem_extent_from_manifest(manifest: Mapping[str, Any]) -> bool:
    review_map = _mapping(manifest.get("review_map"))
    flow_products = _mapping(manifest.get("flow_products"))
    has_dem_background = bool(
        flow_products.get("map_dem_path")
        or flow_products.get("dem_path")
        or flow_products.get("dem_corrected_path")
    )
    dem_background = str(review_map.get("dem_background") or "")
    return has_dem_background and dem_background == "territory_dem"


def _features(collection: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = collection.get("features")
    if not isinstance(values, list):
        return []
    return [dict(value) for value in values if isinstance(value, Mapping)]


def _polygon_outer_rings(geometry: object) -> list[list[tuple[float, float]]]:
    geom = _mapping(geometry)
    kind = geom.get("type")
    coordinates = geom.get("coordinates")
    if kind == "Polygon" and isinstance(coordinates, list):
        return [_ring_xy(coordinates[0])] if coordinates else []
    if kind == "MultiPolygon" and isinstance(coordinates, list):
        rings = []
        for polygon in coordinates:
            if isinstance(polygon, list) and polygon:
                rings.append(_ring_xy(polygon[0]))
        return rings
    return []


def _line_strings(geometry: object) -> list[list[tuple[float, float]]]:
    geom = _mapping(geometry)
    kind = geom.get("type")
    coordinates = geom.get("coordinates")
    if kind == "LineString" and isinstance(coordinates, list):
        return [_ring_xy(coordinates)]
    if kind == "MultiLineString" and isinstance(coordinates, list):
        return [_ring_xy(line) for line in coordinates if isinstance(line, list)]
    return []


def _ring_xy(values: object) -> list[tuple[float, float]]:
    if not isinstance(values, list):
        return []
    points: list[tuple[float, float]] = []
    for value in values:
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            points.append((float(value[0]), float(value[1])))
    return points


def _point_xy(geometry: object) -> tuple[float, float] | None:
    geom = _mapping(geometry)
    if geom.get("type") != "Point":
        return None
    coordinates = geom.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    return float(coordinates[0]), float(coordinates[1])


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _choose_display_bounds(
    dem_extent: tuple[float, float, float, float] | None,
    artifact_bounds: tuple[float, float, float, float] | None,
    *,
    prefer_dem_extent: bool = False,
) -> tuple[float, float, float, float] | None:
    if artifact_bounds is None:
        return dem_extent
    padded_artifacts = _pad_bounds(artifact_bounds, fraction=0.08)
    if dem_extent is None:
        return padded_artifacts
    if not _bounds_intersect(dem_extent, artifact_bounds):
        return padded_artifacts
    dem_area = _bounds_area(dem_extent)
    artifact_area = max(_bounds_area(artifact_bounds), 1.0)
    if prefer_dem_extent:
        return dem_extent
    if dem_area > artifact_area * 10.0:
        return padded_artifacts
    return _union_bounds(dem_extent, artifact_bounds)


def _pad_bounds(
    bounds: tuple[float, float, float, float],
    *,
    fraction: float,
) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = bounds
    width = max(xmax - xmin, 1.0)
    height = max(ymax - ymin, 1.0)
    pad_x = width * fraction
    pad_y = height * fraction
    return xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y


def _bounds_intersect(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1]
    )


def _bounds_area(bounds: tuple[float, float, float, float]) -> float:
    return max(bounds[2] - bounds[0], 0.0) * max(bounds[3] - bounds[1], 0.0)


def _union_bounds(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def _combined_bounds(features: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    points = []
    for feature in features:
        points.extend(_geometry_points(feature.get("geometry")))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _geometry_points(geometry: object) -> list[tuple[float, float]]:
    geom = _mapping(geometry)
    kind = geom.get("type")
    if kind == "Point":
        point = _point_xy(geom)
        return [] if point is None else [point]
    if kind == "Polygon":
        return [point for ring in _polygon_outer_rings(geom) for point in ring]
    if kind == "MultiPolygon":
        return [point for ring in _polygon_outer_rings(geom) for point in ring]
    if kind == "LineString":
        return [point for line in _line_strings(geom) for point in line]
    if kind == "MultiLineString":
        return [point for line in _line_strings(geom) for point in line]
    return []


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "MAP_PNG_NAME",
    "_choose_display_bounds",
    "_prefer_dem_extent_from_manifest",
    "render_site_selection_map",
]
