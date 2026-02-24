"""
Launcher to visualize field values on meshes for square-case geometry.

Run from repository root:
    python hydromodpy/field/cases/square/run_field_demo.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.field.cases.square.field_spatial_square import FieldSquare
from hydromodpy.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.field.core.field_param import FieldParam


DEFAULT_FIELD_PARAM_CONFIG_FILE = "field_param_config.toml"
DEFAULT_MESH_CONFIG_FILE = "mesh_config.toml"
DEFAULT_MESH_SECTION = "mesh"
DEFAULT_FIELD_CONFIG_FILE = "field_spatial_config.toml"
DEFAULT_FIELD_SECTION = "field"
DEFAULT_OUTPUT_FILE = "outputs/field_demo.png"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Visualize field values on the unit square: "
            "zone map, configuration values, and mesh values."
        )
    )
    parser.add_argument(
        "--field-param-config-file",
        default=DEFAULT_FIELD_PARAM_CONFIG_FILE,
        help="Field-parameter TOML path (default: field_param_config.toml).",
    )
    parser.add_argument(
        "--mesh-config-file",
        default=DEFAULT_MESH_CONFIG_FILE,
        help="Mesh TOML path (default: mesh_config.toml).",
    )
    parser.add_argument(
        "--mesh-section",
        default=DEFAULT_MESH_SECTION,
        help=f"Mesh TOML section (default: {DEFAULT_MESH_SECTION}).",
    )
    parser.add_argument(
        "--field-config-file",
        default=DEFAULT_FIELD_CONFIG_FILE,
        help="Field-geometry TOML path (default: field_spatial_config.toml).",
    )
    parser.add_argument(
        "--field-section",
        default=DEFAULT_FIELD_SECTION,
        help=f"Field-geometry TOML section (default: {DEFAULT_FIELD_SECTION}).",
    )
    parser.add_argument(
        "--output-file",
        default=DEFAULT_OUTPUT_FILE,
        help=(
            "Output figure path. Relative paths are resolved from "
            "hydromodpy/field/cases/square/ (default: outputs/field_demo.png)."
        ),
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


def _create_figure(*, field_param, mesh, values_mesh, field=None):
    """
    Create the 3-panel visualization figure.
    """
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.8), dpi=140)
    ax_left, ax_mid, ax_right = axes
    ax_mid.axis("off")

    if field_param.is_heterogeneous:
        if field is None:
            raise ValueError("field must be provided for heterogeneous visualization")
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

        lines = [
            f'"{k}"  ->  {float(v):g}'
            for k, v in sorted(field_param.values_by_key.items(), key=lambda kv: str(kv[0]))
        ]
        values_dict_txt = f'"id"  ->  "{field_param.identifier}"\n' + "\n".join(lines)
        values_txt = ", ".join(
            f"{k}={v:g}" for k, v in sorted(field_param.values_by_key.items(), key=lambda kv: str(kv[0]))
        )
        suptitle = (
            f"mesh={mesh.kind} | param_id={field_param.identifier} | "
            f"field_spatial_id={field.identifier} | line={line_name} "
            f"| zone1_side={field.zone1_side} | values: {values_txt}"
        )
    else:
        # Homogeneous case: no field_spatial object is required.
        domain_color = "#9ecae1"
        domain_img = np.ones((80, 80), dtype=float)
        ax_left.imshow(
            domain_img,
            origin="lower",
            extent=(0.0, 1.0, 0.0, 1.0),
            cmap=ListedColormap([domain_color]),
            interpolation="nearest",
            aspect="equal",
        )
        legend_handles = [Patch(facecolor=domain_color, edgecolor="0.45", label="domain")]
        ax_left.legend(
            handles=legend_handles,
            title="Zones",
            loc="upper right",
            frameon=True,
            framealpha=0.95,
        )
        ax_left.set_title("Homogeneous domain")
        values_dict_txt = (
            f'"id"  ->  "{field_param.identifier}"\n'
            f'"value"  ->  {float(field_param.value):g}'
        )
        suptitle = (
            f"mesh={mesh.kind} | param_id={field_param.identifier} "
            f"| homogeneous value={float(field_param.value):g}"
        )

    ax_left.set_xlabel("x")
    ax_left.set_ylabel("y")

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

    fig.suptitle(suptitle, fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


def main(argv=None):
    args = _parse_args(argv)

    field_param_config_path = _resolve_path(args.field_param_config_file)
    mesh_config_path = _resolve_path(args.mesh_config_file)
    out_path = _resolve_path(args.output_file)

    field_param = FieldParam.from_toml(field_param_config_path)
    mesh = FieldMeshSquare.from_toml(mesh_config_path, section=args.mesh_section)
    field = None
    if field_param.is_heterogeneous:
        field_config_path = _resolve_path(args.field_config_file)
        field = FieldSquare.from_toml(field_config_path, section=args.field_section)

        if field_param.field_spatial_id != field.identifier:
            raise ValueError(
                "Mismatch between field_param.field_spatial_id and field.id: "
                f"'{field_param.field_spatial_id}' != '{field.identifier}'"
            )

        field_discretization = field.on_mesh(mesh)
        values_mesh = field_param.to_mesh_field(field_discretization)
    else:
        values_mesh = field_param.to_mesh_field(mesh=mesh)

    fig = _create_figure(
        field_param=field_param,
        mesh=mesh,
        values_mesh=values_mesh,
        field=field,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    print(f"Saved figure: {out_path}")

    if not args.no_show_plot:
        plt.show()


if __name__ == "__main__":
    main()
