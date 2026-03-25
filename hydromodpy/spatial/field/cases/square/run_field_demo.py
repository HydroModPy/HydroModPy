"""
Visual launcher for the pedagogical square-domain field examples.

This module has two roles:
- provide a direct script entrypoint for one square-field demonstration;
- expose a reusable `run_field_demo_case(...)` helper so the root
  `field/cases/review_cases.py` launcher can chain several examples in
  blocking mode for manual review.

Run from repository root:
    python -m hydromodpy.spatial.field.cases.square.run_field_demo
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import numpy as np

try:
    matplotlib.use("Agg", force=True)
except Exception:
    pass

from matplotlib import pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.spatial.field.cases.square.field_spatial_square import FieldSquare
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.solver.utils.mesh.plot_window_utils import maximize_figure_windows

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
            "hydromodpy/spatial/field/cases/square/ (default: outputs/field_demo.png)."
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


def _ensure_interactive_backend_for_show() -> None:
    """Switch from inline/Agg to one GUI backend before figures are created."""
    backend = str(matplotlib.get_backend()).strip().lower()
    if ("inline" not in backend) and ("agg" not in backend):
        return
    for candidate in ("TkAgg", "QtAgg"):
        try:
            plt.switch_backend(candidate)
            return
        except Exception:
            continue


def _show_figures_blocking(*figures) -> None:
    """Display one or many figures in blocking mode and maximize them."""
    visible = [fig for fig in figures if fig is not None]
    if not visible:
        return
    plt.ioff()
    for fig in visible:
        manager = getattr(getattr(fig, "canvas", None), "manager", None)
        if manager is not None:
            show = getattr(manager, "show", None)
            if callable(show):
                try:
                    show()
                except Exception:
                    pass
        try:
            fig.show()
        except Exception:
            pass
    maximize_figure_windows(*visible)
    plt.pause(0.05)
    plt.show(block=True)
    for fig in visible:
        plt.close(fig)


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
    fig, axes = plt.subplots(
        1,
        3,
        figsize=(18.0, 6.8),
        dpi=140,
        gridspec_kw={"width_ratios": (1.1, 0.9, 1.45)},
    )
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
            for k, v in sorted(
                field_param.values_by_key.items(), key=lambda kv: str(kv[0])
            )
        ]
        values_dict_txt = f'"id"  ->  "{field_param.identifier}"\n' + "\n".join(lines)
        values_txt = ", ".join(
            f"{k}={v:g}"
            for k, v in sorted(
                field_param.values_by_key.items(), key=lambda kv: str(kv[0])
            )
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
        legend_handles = [
            Patch(facecolor=domain_color, edgecolor="0.45", label="domain")
        ]
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
    fig.tight_layout(rect=[0.01, 0.01, 0.99, 0.95])
    return fig


def load_field_demo_inputs_from_toml(
    *,
    field_param_config_file: str | Path = DEFAULT_FIELD_PARAM_CONFIG_FILE,
    mesh_config_file: str | Path = DEFAULT_MESH_CONFIG_FILE,
    mesh_section: str = DEFAULT_MESH_SECTION,
    field_config_file: str | Path = DEFAULT_FIELD_CONFIG_FILE,
    field_section: str = DEFAULT_FIELD_SECTION,
) -> dict[str, object]:
    """Load one square-field demonstration case from TOML files."""
    field_param_config_path = _resolve_path(field_param_config_file)
    mesh_config_path = _resolve_path(mesh_config_file)

    field_param = FieldParam.from_toml(field_param_config_path)
    mesh = FieldMeshSquare.from_toml(mesh_config_path, section=mesh_section)
    field = None
    if field_param.is_heterogeneous:
        field_config_path = _resolve_path(field_config_file)
        field = FieldSquare.from_toml(field_config_path, section=field_section)

    return {
        "field_param": field_param,
        "mesh": mesh,
        "field": field,
    }


def _resolve_mesh_values(*, field_param, mesh, field=None):
    """Map one field parameter onto the provided square-case mesh."""
    if field_param.is_heterogeneous:
        if field is None:
            raise ValueError(
                "field must be provided for heterogeneous field parameters"
            )

        if field_param.field_spatial_id != field.identifier:
            raise ValueError(
                "Mismatch between field_param.field_spatial_id and field.id: "
                f"'{field_param.field_spatial_id}' != '{field.identifier}'"
            )

        field_discretization = field.on_mesh(mesh)
        values_mesh = field_param.to_mesh_field(field_discretization)
        return field_discretization, values_mesh

    values_mesh = field_param.to_mesh_field(mesh=mesh)
    return None, values_mesh


def run_field_demo_case(
    *,
    field_param,
    mesh,
    field=None,
    output_file: str | Path | None = DEFAULT_OUTPUT_FILE,
    show_plot: bool = False,
) -> dict[str, object]:
    """Render one square-field example, optionally showing it in blocking mode."""
    if show_plot:
        _ensure_interactive_backend_for_show()

    field_discretization, values_mesh = _resolve_mesh_values(
        field_param=field_param,
        mesh=mesh,
        field=field,
    )

    fig = _create_figure(
        field_param=field_param,
        mesh=mesh,
        values_mesh=values_mesh,
        field=field,
    )

    out_path = None
    if output_file is not None:
        out_path = _resolve_path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight")
        print(f"Saved figure: {out_path}")

    if show_plot:
        _show_figures_blocking(fig)
    else:
        plt.close(fig)

    return {
        "field_param_id": str(field_param.identifier),
        "field_id": None if field is None else str(field.identifier),
        "mesh_kind": str(mesh.kind),
        "n_cells": int(mesh.n_cells),
        "is_heterogeneous": bool(field_param.is_heterogeneous),
        "output_file": None if out_path is None else str(out_path),
        "field_discretization": field_discretization,
        "values_mesh": values_mesh,
    }


def run_field_demo_from_toml(
    *,
    field_param_config_file: str | Path = DEFAULT_FIELD_PARAM_CONFIG_FILE,
    mesh_config_file: str | Path = DEFAULT_MESH_CONFIG_FILE,
    mesh_section: str = DEFAULT_MESH_SECTION,
    field_config_file: str | Path = DEFAULT_FIELD_CONFIG_FILE,
    field_section: str = DEFAULT_FIELD_SECTION,
    output_file: str | Path | None = DEFAULT_OUTPUT_FILE,
    show_plot: bool = False,
) -> dict[str, object]:
    """Load the standard square-case configs and run the demonstration."""
    payload = load_field_demo_inputs_from_toml(
        field_param_config_file=field_param_config_file,
        mesh_config_file=mesh_config_file,
        mesh_section=mesh_section,
        field_config_file=field_config_file,
        field_section=field_section,
    )
    return run_field_demo_case(
        field_param=payload["field_param"],
        mesh=payload["mesh"],
        field=payload["field"],
        output_file=output_file,
        show_plot=show_plot,
    )


def main(argv=None):
    args = _parse_args(argv)
    run_field_demo_from_toml(
        field_param_config_file=args.field_param_config_file,
        mesh_config_file=args.mesh_config_file,
        mesh_section=args.mesh_section,
        field_config_file=args.field_config_file,
        field_section=args.field_section,
        output_file=args.output_file,
        show_plot=(not bool(args.no_show_plot)),
    )


if __name__ == "__main__":
    main()
