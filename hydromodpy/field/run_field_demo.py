"""
Launcher to visualize field geometry + heterogeneous field values on meshes.

Run from repository root:
    python hydromodpy/field/run_field_demo.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.field.field import Field
from hydromodpy.field.field_mesh import FieldMesh
from hydromodpy.field.field_param import FieldParam


DEFAULT_FIELD_PARAM_CONFIG_FILE = "example_field.toml"
DEFAULT_FIELD_PARAM_SECTION = "field_heterogeneous"
DEFAULT_MESH_CONFIG_FILE = "example_mesh.toml"
DEFAULT_MESH_SECTION = "mesh"
DEFAULT_FIELD_CONFIG_FILE = "example_field_square.toml"
DEFAULT_FIELD_SECTION = "field"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Visualize a heterogeneous field on unit square: "
            "zone map, field values, and mesh+values."
        )
    )
    parser.add_argument(
        "--field-param-config-file",
        default=DEFAULT_FIELD_PARAM_CONFIG_FILE,
        help="Field-parameter TOML path (default: example_field.toml).",
    )
    parser.add_argument(
        "--field-param-section",
        default=DEFAULT_FIELD_PARAM_SECTION,
        help=f"Field-parameter TOML section (default: {DEFAULT_FIELD_PARAM_SECTION}).",
    )
    parser.add_argument(
        "--mesh-config-file",
        default=DEFAULT_MESH_CONFIG_FILE,
        help="Mesh TOML path (default: example_mesh.toml).",
    )
    parser.add_argument(
        "--mesh-section",
        default=DEFAULT_MESH_SECTION,
        help=f"Mesh TOML section (default: {DEFAULT_MESH_SECTION}).",
    )
    parser.add_argument(
        "--field-config-file",
        default=DEFAULT_FIELD_CONFIG_FILE,
        help="Field-geometry TOML path (default: example_field_square.toml).",
    )
    parser.add_argument(
        "--field-section",
        default=DEFAULT_FIELD_SECTION,
        help=f"Field-geometry TOML section (default: {DEFAULT_FIELD_SECTION}).",
    )
    parser.add_argument(
        "--output-file",
        default="field_demo.png",
        help="Output figure filename (saved in current script folder if relative).",
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not display interactive figure window (default: show).",
    )
    return parser.parse_args(argv)


def _resolve_path(path_like):
    raw = Path(str(path_like))
    if raw.is_absolute():
        return raw
    return (Path(__file__).resolve().parent / raw).resolve()


def _plot_interface_line(ax, *, line_name):
    line_key = str(line_name).strip().lower()
    if line_key == "diag_main":
        ax.plot([0.0, 1.0], [0.0, 1.0], color="k", lw=1.1)
    elif line_key == "diag_anti":
        ax.plot([0.0, 1.0], [1.0, 0.0], color="k", lw=1.1)
    elif line_key == "axis_vertical":
        ax.plot([0.5, 0.5], [0.0, 1.0], color="k", lw=1.1)
    elif line_key == "axis_horizontal":
        ax.plot([0.0, 1.0], [0.5, 0.5], color="k", lw=1.1)


def _create_figure(*, field_param, field, mesh, values_mesh):
    """
    Create the 3-panel visualization figure.
    """
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.8), dpi=140)
    ax_left, ax_mid, ax_right = axes
    line_name = field.line
    zone1_color = "#6baed6"
    zone2_color = "#fdd0a2"

    # Left panel: field-only display on the continuous domain (no mesh usage).
    zones_img = field.zone_display()
    img_zone = ax_left.imshow(
        zones_img,
        origin="lower",
        extent=(0.0, 1.0, 0.0, 1.0),
        cmap=ListedColormap([zone1_color, zone2_color]),
        interpolation="nearest",
        vmin=1.0,
        vmax=2.0,
        aspect="equal",
    )
    _plot_interface_line(ax_left, line_name=line_name)

    _ = img_zone
    legend_handles = [
        Patch(facecolor=zone1_color, edgecolor="0.45", label=field.zone1_name),
        Patch(facecolor=zone2_color, edgecolor="0.45", label=field.zone2_name),
    ]
    ax_left.legend(
        handles=legend_handles,
        title="Zones",
        loc="upper right",
        frameon=True,
        framealpha=0.95,
    )
    ax_left.set_title("Field zones")
    ax_left.set_xlabel("x")
    ax_left.set_ylabel("y")

    ax_mid.axis("off")
    lines = [
        f'"{k}"  ->  {float(v):g}'
        for k, v in sorted(field_param.values_by_key.items(), key=lambda kv: str(kv[0]))
    ]
    values_dict_txt = "\n".join(lines)
    ax_mid.text(
        0.5,
        0.5,
        values_dict_txt,
        transform=ax_mid.transAxes,
        ha="center",
        va="center",
        fontsize=12,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.55", "fc": "#f7f7f7", "ec": "0.70"},
    )
    ax_mid.set_title("values by zone", y=0.74, pad=2)

    img = mesh.plot_cell_values(
        ax_right,
        values_mesh.cell_values,
        cmap="viridis",
        show_mesh=True,
    )

    cbar = fig.colorbar(img, ax=ax_right, shrink=0.78, aspect=26, pad=0.03)
    cbar.set_label("Field value")
    ax_right.set_title("Field values on Mesh")
    ax_right.set_xlabel("x")
    ax_right.set_ylabel("y")

    values_txt = ", ".join(
        f"{k}={v:g}" for k, v in sorted(field_param.values_by_key.items(), key=lambda kv: str(kv[0]))
    )
    fig.suptitle(
        (
            f"mesh={mesh.kind} | field_id={field.identifier} | line={line_name} "
            f"| zone1_side={field.zone1_side} | values: {values_txt}"
        ),
        fontsize=10,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


def main(argv=None):
    args = _parse_args(argv)

    field_param_config_path = _resolve_path(args.field_param_config_file)
    mesh_config_path = _resolve_path(args.mesh_config_file)
    field_config_path = _resolve_path(args.field_config_file)
    out_path = _resolve_path(args.output_file)

    field_param = FieldParam.from_toml(
        field_param_config_path,
        section=args.field_param_section,
    )
    if not field_param.is_heterogeneous:
        raise ValueError(
            f"Section '{args.field_param_section}' must describe a heterogeneous field "
            "(kind='heterogeneous')."
        )

    mesh = FieldMesh.from_toml(mesh_config_path, section=args.mesh_section)
    field = Field.from_toml(field_config_path, section=args.field_section)

    if field_param.field_id != field.identifier:
        raise ValueError(
            "Mismatch between field_param.field_id and field.id: "
            f"'{field_param.field_id}' != '{field.identifier}'"
        )

    field_discretization = field.on_mesh(mesh)
    values_mesh = field_param.to_mesh_field(field_discretization)

    fig = _create_figure(
        field_param=field_param,
        field=field,
        mesh=mesh,
        values_mesh=values_mesh,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    print(f"Saved figure: {out_path}")

    if not args.no_show_plot:
        plt.show()


if __name__ == "__main__":
    main()
