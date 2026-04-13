"""Geology-to-property transfer demo using the generic field pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
from rasterio.features import rasterize
from rasterio.transform import from_bounds

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.data.variables.geology.cases.common import (
    clip_square_window,
    format_axes_ticks_km,
    resolve_case_path,
    resolve_output_path,
    save_figure,
)
from hydromodpy.data.variables.geology.config_cases import load_geology_toml
from hydromodpy.data.variables.geology.io import load_vector_geology_dataframe
from hydromodpy.data.variables.geology.processing import (
    uniformize_sea_zone_on_dataframe,
)
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.geology.geology_field import GeologyField
from hydromodpy.spatial.field.geology.geology_mesh import GeologyStructuredMesh
from hydromodpy.core.units import parse_length_to_m

DEFAULT_GEOLOGY_CONFIG_FILE = "run_geology_case.toml"
DEFAULT_GEOLOGY_SECTION = "geology"
DEFAULT_FIELD_PARAM_CONFIG_FILE = "run_geology_property_case.toml"
DEFAULT_FIELD_PARAM_SECTION = "field"
DEFAULT_OUTPUT_FILE = "geology_property_demo.png"
DEFAULT_SEA_FIELD = "TERRE_MER"
DEFAULT_SEA_VALUE = "M"
DEFAULT_SEA_ZONE_KEY = "SEA"
DEFAULT_BRETAGNE_CENTER_X = 355000.0
DEFAULT_BRETAGNE_CENTER_Y = 6715000.0
DEFAULT_TARGET_N_CELLS = 400
DEFAULT_CELL_SAMPLES_PER_AXIS = 10


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Map one physical property from FieldParam onto a geology-driven mesh "
            "using the generic field pipeline."
        )
    )
    parser.add_argument("--geology-config-file", default=DEFAULT_GEOLOGY_CONFIG_FILE)
    parser.add_argument("--geology-section", default=DEFAULT_GEOLOGY_SECTION)
    parser.add_argument("--field-param-config-file", default=DEFAULT_FIELD_PARAM_CONFIG_FILE)
    parser.add_argument("--field-param-section", default=DEFAULT_FIELD_PARAM_SECTION)
    parser.add_argument("--output-file", default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--sea-field", default=DEFAULT_SEA_FIELD)
    parser.add_argument("--sea-value", default=DEFAULT_SEA_VALUE)
    parser.add_argument("--sea-zone-key", default=DEFAULT_SEA_ZONE_KEY)
    parser.add_argument("--no-uniform-sea", action="store_true")
    parser.add_argument("--global-map", action="store_true")
    parser.add_argument("--center-x", type=float, default=DEFAULT_BRETAGNE_CENTER_X)
    parser.add_argument("--center-y", type=float, default=DEFAULT_BRETAGNE_CENTER_Y)
    parser.add_argument("--window-km", type=float, default=10.0)
    parser.add_argument("--target-n-cells", type=int, default=DEFAULT_TARGET_N_CELLS)
    parser.add_argument(
        "--cell-samples-per-axis",
        type=int,
        default=DEFAULT_CELL_SAMPLES_PER_AXIS,
    )
    parser.add_argument("--no-show-plot", action="store_true")
    return parser.parse_args(argv)


def _plot_zone_map(ax, gdf):
    zone_keys = gdf["zone_key"].astype(str)
    unique_keys = sorted(np.unique(zone_keys.to_numpy()).tolist())
    zone_to_class = {key: i for i, key in enumerate(unique_keys)}
    class_values = zone_keys.map(zone_to_class).astype(float)

    gdf_zone = gdf.copy()
    gdf_zone["zone_class"] = class_values
    cmap = plt.get_cmap("tab20", max(1, len(unique_keys)))
    gdf_zone.plot(
        column="zone_class",
        ax=ax,
        cmap=cmap,
        linewidth=0.15,
        edgecolor="0.35",
        legend=False,
        vmin=-0.5,
        vmax=float(len(unique_keys)) - 0.5,
    )
    ax.set_title(f"Geology zones ({len(unique_keys)} classes)")
    ax.set_aspect("equal")
    format_axes_ticks_km(ax)


def _plot_mesh_property_map(ax, mesh, mesh_values, *, property_label: str):
    img = mesh.plot_cell_values(
        ax,
        mesh_values.cell_values,
        cmap="viridis",
        show_mesh=True,
    )
    ax.set_title(f"Field values on Mesh ({property_label})")
    format_axes_ticks_km(ax)
    return img


def _build_zone_name_by_key(
    gdf,
    *,
    zone_key_column: str = "zone_key",
    name_column: str = "LITHOLOGIE",
):
    out: dict[str, str] = {}
    key_col = str(zone_key_column)
    name_col = str(name_column)
    for key in sorted(np.unique(gdf[key_col].astype(str).to_numpy()).tolist()):
        if name_col not in gdf.columns:
            out[key] = key
            continue
        names = gdf.loc[gdf[key_col].astype(str) == key, name_col].astype(str).str.strip()
        names = names[(names != "") & (names.str.lower() != "none") & (names.str.lower() != "nan")]
        out[key] = str(names.value_counts().index[0]) if not names.empty else key
    return out


def _values_panel_text(gdf, field_param: FieldParam, *, max_lines: int = 26):
    counts = gdf["zone_key"].astype(str).value_counts()
    zone_name_by_key = _build_zone_name_by_key(gdf)
    lines = [f'"id" -> "{field_param.identifier}"', "values_by_zone:"]

    shown = 0
    for key in counts.index.tolist():
        if shown >= int(max_lines):
            break
        if key not in field_param.values_by_key:
            continue
        name = str(zone_name_by_key.get(key, key))
        value = float(field_param.values_by_key[key])
        lines.append(f'  "{key}" ({name}) -> {value:g}')
        shown += 1

    remaining = max(0, int(len(counts)) - shown)
    if remaining > 0:
        lines.append(f"  ... +{remaining} zones")
    return "\n".join(lines)


def _load_display_geology(args, geology_config_path):
    geology_cfg = load_geology_toml(geology_config_path, section=args.geology_section)
    loaded = load_vector_geology_dataframe(
        geology_cfg,
        config_path=geology_config_path,
        zone_key_column="zone_key",
    )
    gdf = loaded["gdf"].copy()
    window_polygon = None

    if not bool(args.global_map):
        window_m = float(parse_length_to_m(args.window_km, default_unit="km", label="window_km"))
        gdf, window_polygon = clip_square_window(
            gdf,
            center_x=float(args.center_x),
            center_y=float(args.center_y),
            window_m=window_m,
        )

    gdf, sea_info = uniformize_sea_zone_on_dataframe(
        gdf,
        enabled=(not bool(args.no_uniform_sea)),
        zone_key_column="zone_key",
        sea_field=str(args.sea_field),
        sea_value=str(args.sea_value),
        sea_zone_key=str(args.sea_zone_key),
    )
    return loaded, gdf, window_polygon, sea_info


def _load_and_validate_field_param(args, field_param_path, *, expected_field_id: str):
    field_param = FieldParam.from_toml(field_param_path, section=args.field_param_section)
    if field_param.is_homogeneous:
        raise ValueError("This demo expects a heterogeneous FieldParam (kind='heterogeneous').")
    if str(field_param.field_spatial_id) != str(expected_field_id):
        raise ValueError(
            "FieldParam.field_spatial_id does not match geology id: "
            f"'{field_param.field_spatial_id}' != '{expected_field_id}'"
        )
    return field_param


def _build_local_geology_field(
    gdf,
    *,
    identifier: str,
    target_n_cells: int,
):
    if len(gdf) == 0:
        raise ValueError("Cannot build a local geology field from an empty GeoDataFrame")

    zone_series = gdf["zone_key"].astype(str).str.strip()
    zone_series = zone_series[zone_series != ""]
    unique_zone_keys = sorted(np.unique(zone_series.to_numpy()).tolist())
    if len(unique_zone_keys) == 0:
        raise ValueError("No usable zone_key found in display geology polygons")

    zone_to_encoded = {key: (i + 1) for i, key in enumerate(unique_zone_keys)}
    encoded_to_zone = {int(v): str(k) for k, v in zone_to_encoded.items()}

    xmin, ymin, xmax, ymax = [float(v) for v in gdf.total_bounds]
    width_m = xmax - xmin
    height_m = ymax - ymin
    if width_m <= 0.0 or height_m <= 0.0:
        raise ValueError("Invalid geology bounds for local field rasterization")

    approx = max(1, int(target_n_cells))
    ratio = width_m / height_m
    nx_cells = max(8, int(np.round(np.sqrt(float(approx) * ratio))))
    ny_cells = max(8, int(np.round(np.sqrt(float(approx) / ratio))))

    raster_width = max(32, int(4 * nx_cells))
    raster_height = max(32, int(4 * ny_cells))
    transform = from_bounds(xmin, ymin, xmax, ymax, raster_width, raster_height)

    shapes = []
    for geom, key in zip(gdf.geometry, gdf["zone_key"], strict=False):
        zone_key = str(key).strip()
        if zone_key == "" or zone_key not in zone_to_encoded:
            continue
        shapes.append((geom, int(zone_to_encoded[zone_key])))
    if not shapes:
        raise ValueError("No usable geometry found to build local geology field")

    encoded = rasterize(
        shapes=shapes,
        out_shape=(int(raster_height), int(raster_width)),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="int32",
    )
    return GeologyField(
        identifier=str(identifier),
        encoded_codes=encoded,
        encoded_to_zone=encoded_to_zone,
        transform=transform,
        crs=getattr(gdf, "crs", None),
        source_kind="vector_local",
        default_cell_samples_per_axis=DEFAULT_CELL_SAMPLES_PER_AXIS,
    )


def main(argv=None):
    args = _parse_args(argv)
    geology_config_path = resolve_case_path(args.geology_config_file)
    field_param_path = resolve_case_path(args.field_param_config_file)
    output_path = resolve_output_path(args.output_file, default_file=DEFAULT_OUTPUT_FILE)

    loaded, gdf, _window_polygon, sea_info = _load_display_geology(args, geology_config_path)
    field_param = _load_and_validate_field_param(
        args,
        field_param_path,
        expected_field_id=str(loaded["field_id"]),
    )
    geology_field = _build_local_geology_field(
        gdf,
        identifier=str(loaded["field_id"]),
        target_n_cells=int(args.target_n_cells),
    )
    mesh = GeologyStructuredMesh.from_bounds(
        gdf.total_bounds,
        target_n_cells=int(args.target_n_cells),
    )
    field_discretization = geology_field.on_mesh(
        mesh,
        cell_samples_per_axis=max(2, int(args.cell_samples_per_axis)),
    )
    values_mesh = field_param.to_mesh_field(field_discretization)
    values_flat = np.asarray(values_mesh.cell_values, dtype=float).reshape(-1)

    print(f"Geology source: {loaded['source_path']}")
    print(f"FieldParam id: {field_param.identifier}")
    print(f"n_polygons: {len(gdf)}")
    print(f"n_mesh_cells: {mesh.n_cells}")
    print(f"sea_uniformization: {sea_info}")
    print(
        "property_range_on_mesh: "
        f"[{float(np.nanmin(values_flat)):.6g}, {float(np.nanmax(values_flat)):.6g}]"
    )

    fig, axes = plt.subplots(1, 3, figsize=(18.0, 6.3), dpi=140)
    ax_left, ax_mid, ax_right = axes
    _plot_zone_map(ax_left, gdf)
    ax_mid.axis("off")
    ax_mid.text(
        0.5,
        0.5,
        _values_panel_text(gdf, field_param),
        transform=ax_mid.transAxes,
        ha="center",
        va="center",
        fontsize=9.5,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.55", "fc": "#f7f7f7", "ec": "0.70"},
    )
    img = _plot_mesh_property_map(
        ax_right,
        mesh,
        values_mesh,
        property_label=str(field_param.identifier),
    )
    fig.colorbar(img, ax=ax_right, shrink=0.72, aspect=28, pad=0.03)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    saved_path = save_figure(fig, output_path)
    print(f"Saved figure: {saved_path}")

    if not args.no_show_plot:
        plt.show()


if __name__ == "__main__":
    main()
