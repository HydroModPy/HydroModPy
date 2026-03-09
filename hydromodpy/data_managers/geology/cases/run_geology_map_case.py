"""
Standalone geology visual check for France-style geology vectors.

Goal
----
Display one geology map and verify that the loaded source contains multiple
classes (not a uniform map).

By default, sea polygons are reassigned to one uniform class for readability.

Run from repository root:
    python hydromodpy/data_managers/geology/cases/run_geology_map_case.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.data_managers.geology.cases.common import (
    clip_square_window,
    format_axes_ticks_km,
    resolve_case_path,
    resolve_output_path,
    save_figure,
)
from hydromodpy.data_managers.geology.geology_config import load_geology_toml
from hydromodpy.data_managers.geology.geology_io import load_vector_geology_dataframe
from hydromodpy.data_managers.geology.geology_processing import (
    build_zone_class_index_on_dataframe,
    uniformize_sea_zone_on_dataframe,
)
from hydromodpy.units import parse_length_to_m


DEFAULT_CONFIG_FILE = "run_geology_case.toml"
DEFAULT_SECTION = "geology"
DEFAULT_OUTPUT_FILE = "geology_france_global.png"
DEFAULT_SEA_FIELD = "TERRE_MER"
DEFAULT_SEA_VALUE = "M"
DEFAULT_SEA_ZONE_KEY = "SEA"
# Inland Brittany preset (10 km square, no sea expected).
DEFAULT_BRETAGNE_CENTER_X = 355000.0
DEFAULT_BRETAGNE_CENTER_Y = 6715000.0
DEFAULT_MAX_LEGEND_CLASSES = 30
DEFAULT_LEGEND_NAME_FIELD = "LITHOLOGIE"
DEFAULT_SEA_LABEL = "Mer"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Show one geology map and verify that several classes are present."
        )
    )
    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
        help="Geology TOML configuration path (default: run_geology_case.toml).",
    )
    parser.add_argument(
        "--section",
        default=DEFAULT_SECTION,
        help=f"TOML section name (default: {DEFAULT_SECTION}).",
    )
    parser.add_argument(
        "--output-file",
        default=DEFAULT_OUTPUT_FILE,
        help=(
            "Output figure path. Bare filenames are saved in outputs/. "
            "Relative paths are resolved from hydromodpy/data_managers/geology/cases/ "
            f"(default: {DEFAULT_OUTPUT_FILE})."
        ),
    )
    parser.add_argument(
        "--sea-field",
        default=DEFAULT_SEA_FIELD,
        help=(
            "Vector attribute used to identify sea polygons "
            f"(default: {DEFAULT_SEA_FIELD})."
        ),
    )
    parser.add_argument(
        "--sea-value",
        default=DEFAULT_SEA_VALUE,
        help=(
            "Value in --sea-field considered as sea "
            f"(default: {DEFAULT_SEA_VALUE})."
        ),
    )
    parser.add_argument(
        "--sea-zone-key",
        default=DEFAULT_SEA_ZONE_KEY,
        help=(
            "Uniform class label assigned to sea polygons when enabled "
            f"(default: {DEFAULT_SEA_ZONE_KEY})."
        ),
    )
    parser.add_argument(
        "--no-uniform-sea",
        action="store_true",
        help="Disable sea-uniformization step.",
    )
    parser.add_argument(
        "--center-x",
        type=float,
        default=None,
        help=(
            "Center X coordinate (meters in source CRS) for local square window. "
            "Use together with --center-y."
        ),
    )
    parser.add_argument(
        "--center-y",
        type=float,
        default=None,
        help=(
            "Center Y coordinate (meters in source CRS) for local square window. "
            "Use together with --center-x."
        ),
    )
    parser.add_argument(
        "--window-km",
        type=float,
        default=10.0,
        help="Local square side length in km (default: 10).",
    )
    parser.add_argument(
        "--bretagne-10km",
        action="store_true",
        help=(
            "Use a predefined inland 10-km square in Brittany (no sea expected) "
            f"(center x={DEFAULT_BRETAGNE_CENTER_X}, y={DEFAULT_BRETAGNE_CENTER_Y}, "
            "EPSG:2154)."
        ),
    )
    parser.add_argument(
        "--max-legend-classes",
        type=int,
        default=DEFAULT_MAX_LEGEND_CLASSES,
        help=(
            "Maximum number of classes displayed in the color legend "
            f"(default: {DEFAULT_MAX_LEGEND_CLASSES})."
        ),
    )
    parser.add_argument(
        "--legend-name-field",
        default=DEFAULT_LEGEND_NAME_FIELD,
        help=(
            "Attribute used for legend labels (geology names). "
            f"Default: {DEFAULT_LEGEND_NAME_FIELD}."
        ),
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not open the interactive matplotlib window.",
    )
    return parser.parse_args(argv)


def _build_zone_labels(
    gdf,
    counts,
    *,
    zone_key_column: str,
    legend_name_field: str,
    sea_zone_key: str,
    sea_label: str,
):
    """
    Build display labels for each zone key from one geology-name attribute.
    """
    key_col = str(zone_key_column).strip()
    name_field = str(legend_name_field).strip()
    sea_key = str(sea_zone_key).strip()
    sea_name = str(sea_label).strip() or "Mer"

    label_by_key: dict[str, str] = {}
    for key in counts.index.tolist():
        key_str = str(key)
        if key_str == sea_key:
            label_by_key[key_str] = sea_name
            continue
        if name_field == "" or (name_field not in gdf.columns):
            label_by_key[key_str] = key_str
            continue
        sub = gdf.loc[gdf[key_col].astype(str) == key_str, name_field]
        names = sub.astype(str).str.strip()
        names = names[
            (names != "")
            & (names.str.lower() != "none")
            & (names.str.lower() != "nan")
        ]
        if names.empty:
            label_by_key[key_str] = key_str
            continue
        label_by_key[key_str] = str(names.value_counts().index[0])
    return label_by_key


def _build_color_legend(gdf, counts, *, cmap_name: str, max_classes: int, label_by_key: dict[str, str]):
    """
    Build legend handles mapping class colors to zone keys.
    """
    class_rows = (
        gdf[["zone_key", "class_idx"]]
        .drop_duplicates()
        .sort_values("class_idx")
    )
    n_classes = int(len(class_rows))
    cmap = plt.get_cmap(cmap_name, max(1, n_classes))

    # Keep all classes for small windows; truncate on very large maps.
    max_n = max(1, int(max_classes))
    zone_rank = {str(k): i for i, k in enumerate(counts.index.tolist())}
    class_rows["rank"] = class_rows["zone_key"].astype(str).map(zone_rank).fillna(10**9)
    if n_classes > max_n:
        class_rows = class_rows.sort_values("rank").head(max_n).sort_values("class_idx")
        truncated = n_classes - max_n
    else:
        truncated = 0

    handles = []
    for row in class_rows.itertuples(index=False):
        idx = int(getattr(row, "class_idx"))
        key = str(getattr(row, "zone_key"))
        label = str(label_by_key.get(key, key))
        handles.append(
            Patch(
                facecolor=cmap(idx),
                edgecolor="0.25",
                linewidth=0.5,
                label=label,
            )
        )
    return cmap, n_classes, handles, truncated


def _plot_global_geology(
    ax,
    gdf,
    counts,
    *,
    max_legend_classes: int,
    label_by_key: dict[str, str],
    legend_outside: bool,
):
    cmap, n_classes, legend_handles, truncated = _build_color_legend(
        gdf,
        counts,
        cmap_name="nipy_spectral",
        max_classes=max_legend_classes,
        label_by_key=label_by_key,
    )

    gdf.plot(
        column="class_idx",
        ax=ax,
        cmap=cmap,
        linewidth=0.0,
        legend=False,
        vmin=-0.5,
        vmax=float(n_classes) - 0.5,
    )
    ax.set_title(f"Carte geologique ({counts.size} classes)", fontsize=12)
    ax.set_aspect("equal")
    format_axes_ticks_km(ax)
    legend_title = "Couleurs -> noms de geologie"
    if truncated > 0:
        legend_title += f"\n(top {len(legend_handles)} / {n_classes})"
    if legend_outside:
        ax.legend(
            handles=legend_handles,
            title=legend_title,
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=True,
            framealpha=0.95,
            borderaxespad=0.0,
            fontsize=8,
            title_fontsize=9,
            ncol=1,
        )
    else:
        ax.legend(
            handles=legend_handles,
            title=legend_title,
            loc="upper right",
            frameon=True,
            framealpha=0.95,
            fontsize=7.5,
            title_fontsize=8.5,
            ncol=1,
        )


def _plot_zone_location(ax, base_gdf, window_polygon, *, source_path: str):
    """
    Plot the study-window position over a Brittany-scale map.
    """
    base_gdf.plot(
        ax=ax,
        color="#efefef",
        edgecolor="#9a9a9a",
        linewidth=0.2,
    )
    zone_gdf = base_gdf.__class__(geometry=[window_polygon], crs=base_gdf.crs)
    zone_gdf.boundary.plot(
        ax=ax,
        color="#d7301f",
        linewidth=2.0,
    )
    zone_gdf.plot(
        ax=ax,
        color="#d7301f",
        alpha=0.12,
        edgecolor="none",
    )
    ax.set_title("Position de la zone etudiee (Bretagne)")
    ax.set_aspect("equal")
    format_axes_ticks_km(ax)
    ax.text(
        0.02,
        0.02,
        f"Source: {Path(source_path).name}",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=8,
        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "0.7", "alpha": 0.9},
    )


def _load_geology(config_path, section: str):
    """
    Load geology vectors once and return both full and working copies.
    """
    cfg = load_geology_toml(config_path, section=section)
    loaded = load_vector_geology_dataframe(
        cfg,
        config_path=config_path,
        zone_key_column="zone_key",
    )
    base_gdf = loaded["gdf"].copy()
    gdf = loaded["gdf"].copy()
    return loaded, base_gdf, gdf


def _select_local_window(args, gdf):
    """
    Optionally clip geology to one local square window.
    """
    local_window_polygon = None
    if bool(args.bretagne_10km):
        center_x = DEFAULT_BRETAGNE_CENTER_X
        center_y = DEFAULT_BRETAGNE_CENTER_Y
        window_m = float(parse_length_to_m(10.0, default_unit="km", label="window"))
        gdf, local_window_polygon = clip_square_window(
            gdf,
            center_x=center_x,
            center_y=center_y,
            window_m=window_m,
        )
        print(
            "local_window: preset_bretagne_10km "
            f"(center=({center_x:.1f}, {center_y:.1f}), side={window_m / 1000.0:.1f} km)"
        )
    elif (args.center_x is not None) or (args.center_y is not None):
        if (args.center_x is None) or (args.center_y is None):
            raise ValueError("Use --center-x and --center-y together.")
        window_m = float(parse_length_to_m(args.window_km, default_unit="km", label="window_km"))
        gdf, local_window_polygon = clip_square_window(
            gdf,
            center_x=float(args.center_x),
            center_y=float(args.center_y),
            window_m=window_m,
        )
        print(
            "local_window: custom "
            f"(center=({float(args.center_x):.1f}, {float(args.center_y):.1f}), "
            f"side={window_m / 1000.0:.1f} km)"
        )
    return gdf, local_window_polygon


def _prepare_plot_data(args, gdf):
    """
    Apply sea handling, derive class indices, and build display labels.
    """
    gdf, sea_info = uniformize_sea_zone_on_dataframe(
        gdf,
        enabled=(not bool(args.no_uniform_sea)),
        zone_key_column="zone_key",
        sea_field=str(args.sea_field),
        sea_value=str(args.sea_value),
        sea_zone_key=str(args.sea_zone_key),
    )

    gdf, counts = build_zone_class_index_on_dataframe(
        gdf,
        zone_key_column="zone_key",
        class_index_column="class_idx",
        min_unique=2,
    )
    label_by_key = _build_zone_labels(
        gdf,
        counts,
        zone_key_column="zone_key",
        legend_name_field=str(args.legend_name_field),
        sea_zone_key=str(args.sea_zone_key),
        sea_label=DEFAULT_SEA_LABEL,
    )
    return gdf, counts, label_by_key, sea_info


def _create_figure(
    *,
    gdf,
    counts,
    label_by_key,
    base_gdf,
    local_window_polygon,
    source_path: str,
    max_legend_classes: int,
):
    """
    Build either:
    - one global map, or
    - one local map + one location panel.
    """
    if local_window_polygon is not None:
        fig, axes = plt.subplots(1, 2, figsize=(15.0, 6.6), dpi=140)
        ax_map, ax_loc = axes
        _plot_global_geology(
            ax_map,
            gdf,
            counts,
            max_legend_classes=max_legend_classes,
            label_by_key=label_by_key,
            legend_outside=False,
        )
        _plot_zone_location(
            ax_loc,
            base_gdf,
            local_window_polygon,
            source_path=source_path,
        )
        fig.suptitle("Geologie locale et position de la zone", fontsize=11)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        return fig

    fig, ax = plt.subplots(1, 1, figsize=(9.0, 7.8), dpi=140)
    _plot_global_geology(
        ax,
        gdf,
        counts,
        max_legend_classes=max_legend_classes,
        label_by_key=label_by_key,
        legend_outside=True,
    )
    fig.tight_layout()
    return fig


def main(argv=None):
    # 1) Parse and resolve run configuration.
    args = _parse_args(argv)
    config_path = resolve_case_path(args.config_file)
    output_path = resolve_output_path(
        args.output_file,
        default_file=DEFAULT_OUTPUT_FILE,
    )

    # 2) Load data and optional local subset.
    loaded, base_gdf, gdf = _load_geology(config_path, section=args.section)
    gdf, local_window_polygon = _select_local_window(args, gdf)

    # 3) Prepare classes and labels used by plotting.
    gdf, counts, label_by_key, sea_info = _prepare_plot_data(args, gdf)

    print(f"Geology source: {loaded['source_path']}")
    print(f"code_field: {loaded['code_field']}")
    print(f"n_unique_classes: {counts.size}")
    print(f"top_10_classes: {counts.head(10).to_dict()}")
    print(f"sea_uniformization: {sea_info}")

    # 4) Build figure then save/show.
    fig = _create_figure(
        gdf=gdf,
        counts=counts,
        label_by_key=label_by_key,
        base_gdf=base_gdf,
        local_window_polygon=local_window_polygon,
        source_path=str(loaded["source_path"]),
        max_legend_classes=int(args.max_legend_classes),
    )
    saved_path = save_figure(fig, output_path)
    print(f"Saved figure: {saved_path}")

    if not args.no_show_plot:
        plt.show()


if __name__ == "__main__":
    main()
