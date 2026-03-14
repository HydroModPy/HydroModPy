"""CLI demo for 3D FieldParam extrusion visualization on SGrid."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib
import matplotlib.colors as mcolors
from matplotlib.ticker import ScalarFormatter
import numpy as np


def _configure_matplotlib_backend_from_argv(argv: list[str]) -> None:
    """Pick one GUI backend early when interactive display is expected."""
    if "--no-show-plot" in argv:
        return
    backend = str(matplotlib.get_backend()).strip().lower()
    if ("inline" not in backend) and ("agg" not in backend):
        return
    for candidate in ("TkAgg", "QtAgg"):
        try:
            matplotlib.use(candidate, force=True)
            return
        except Exception:
            continue


_configure_matplotlib_backend_from_argv(sys.argv[1:])

import matplotlib.pyplot as plt

# Ensure repository root is importable when script is launched directly.
def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    return current.parents[0]


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.case_runner import (
    run_discretization_case,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.run_demo_config import (
    SGridFieldParamDiscretizationConfig,
)
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_config import SGridConfig
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_from_config import (
    build_sgrid_from_config,
)


DEFAULT_CONFIG_FILE = "run_demo_3d_config.toml"
DEFAULT_SECTION = "case"
DEFAULT_OUTPUT_FIGURE = "outputs/sgrid_fieldparam_discretization_3d_demo.png"
DEFAULT_OUTPUT_FIELD_FIGURE = "outputs/sgrid_discretized_field_on_sgrid_demo.png"

TITLE_FONTSIZE = 9
LABEL_FONTSIZE = 7
TICK_FONTSIZE = 6


def _set_square_axes(ax) -> None:
    """Force a square plotting box when Matplotlib supports it."""
    try:
        ax.set_box_aspect(1.0)
    except Exception:
        pass


def _disable_axis_offset(ax) -> None:
    """Disable scientific offset to avoid collisions with titles."""
    fmt = ScalarFormatter(useMathText=False)
    fmt.set_scientific(False)
    fmt.set_useOffset(False)
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run a dedicated 3D discretization demo with exponential vertical "
            "decay and produce: (1) final-values figure (orthogonal sections + "
            "profiles) and (2) discretized-field figure on SGrid."
        )
    )
    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
        help=(
            "Path to 3D demo TOML config. "
            f"Default: {DEFAULT_CONFIG_FILE} (cwd first, then script directory)."
        ),
    )
    parser.add_argument(
        "--section",
        default=DEFAULT_SECTION,
        help=f"TOML section to load (default: {DEFAULT_SECTION}).",
    )
    parser.add_argument(
        "--output-figure",
        default=DEFAULT_OUTPUT_FIGURE,
        help=(
            "Output PNG path for the sections/profiles demo figure. "
            f"Default: {DEFAULT_OUTPUT_FIGURE} (relative to config directory)."
        ),
    )
    parser.add_argument(
        "--output-field-figure",
        default=DEFAULT_OUTPUT_FIELD_FIGURE,
        help=(
            "Output PNG path for the SGrid projected-field figure "
            "(same layout as final-values figure, before vertical correction). "
            f"Default: {DEFAULT_OUTPUT_FIELD_FIGURE} (relative to config directory)."
        ),
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not open interactive figure window.",
    )
    return parser.parse_args(argv)


def _resolve_config_path(raw_config: str) -> Path:
    candidate = Path(raw_config).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()

    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    script_candidate = (Path(__file__).resolve().parent / candidate).resolve()
    if script_candidate.exists():
        return script_candidate

    raise FileNotFoundError(
        f"Config TOML not found: '{raw_config}'. "
        f"Tried '{cwd_candidate}' and '{script_candidate}'."
    )


def _resolve_output_path(raw_output: str, *, config_path: Path) -> Path:
    output = Path(raw_output).expanduser()
    if not output.is_absolute():
        output = (config_path.parent / output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _ensure_gui_backend_for_blocking_show() -> None:
    """Switch away from inline/non-GUI backends before blocking `show()`."""
    backend = str(plt.get_backend()).strip().lower()
    if ("inline" not in backend) and ("agg" not in backend):
        return

    for candidate in ("TkAgg", "QtAgg"):
        try:
            plt.switch_backend(candidate)
            return
        except Exception:
            continue


def _compute_layer_center_depths(sgrid) -> np.ndarray:
    top = np.asarray(getattr(sgrid, "top"), dtype=float)
    botm = np.asarray(getattr(sgrid, "botm"), dtype=float)
    if botm.ndim != 3:
        raise ValueError("sgrid.botm must be 3D")
    ztop = np.empty_like(botm, dtype=float)
    ztop[0, :, :] = top
    if botm.shape[0] > 1:
        ztop[1:, :, :] = botm[:-1, :, :]
    zmid = 0.5 * (ztop + botm)
    return np.maximum(0.0, top[None, :, :] - zmid)


def _extract_xy_from_sgrid(sgrid) -> tuple[np.ndarray, np.ndarray]:
    """Return 2D center coordinates for SGrid cells."""
    nrow = int(getattr(sgrid, "nrow"))
    ncol = int(getattr(sgrid, "ncol"))

    if hasattr(sgrid, "xcellcenters") and hasattr(sgrid, "ycellcenters"):
        x = np.asarray(getattr(sgrid, "xcellcenters"), dtype=float)
        y = np.asarray(getattr(sgrid, "ycellcenters"), dtype=float)
        if x.ndim == 2 and y.ndim == 2 and x.shape == (nrow, ncol) and y.shape == (nrow, ncol):
            return x, y
        if x.ndim == 1 and y.ndim == 1 and x.size == ncol and y.size == nrow:
            return np.meshgrid(x, y, indexing="xy")

    x_idx, y_idx = np.meshgrid(
        np.arange(ncol, dtype=float),
        np.arange(nrow, dtype=float),
        indexing="xy",
    )
    return x_idx, y_idx


def _centers_to_edges_1d(centers: np.ndarray) -> np.ndarray:
    """Build edge coordinates from center coordinates."""
    c = np.asarray(centers, dtype=float).reshape(-1)
    if c.size == 0:
        raise ValueError("Cannot build edges from empty center array")
    if c.size == 1:
        return np.array([float(c[0]) - 0.5, float(c[0]) + 0.5], dtype=float)

    e = np.empty(c.size + 1, dtype=float)
    e[1:-1] = 0.5 * (c[:-1] + c[1:])
    e[0] = c[0] - (e[1] - c[0])
    e[-1] = c[-1] + (c[-1] - e[-2])
    return e


def _layer_interfaces_elevation_for_row(sgrid, *, row_idx: int) -> np.ndarray:
    """Return layer-interface elevations at one row as (nlay+1, ncol)."""
    top = np.asarray(getattr(sgrid, "top"), dtype=float)
    botm = np.asarray(getattr(sgrid, "botm"), dtype=float)
    nlay = int(botm.shape[0])
    ncol = int(top.shape[1])

    interfaces = np.empty((nlay + 1, ncol), dtype=float)
    interfaces[0, :] = top[row_idx, :]
    for ilay in range(nlay):
        interfaces[ilay + 1, :] = botm[ilay, row_idx, :]
    return interfaces


def _compute_layer_center_elevations(sgrid) -> np.ndarray:
    top = np.asarray(getattr(sgrid, "top"), dtype=float)
    botm = np.asarray(getattr(sgrid, "botm"), dtype=float)
    if botm.ndim != 3:
        raise ValueError("sgrid.botm must be 3D")
    ztop = np.empty_like(botm, dtype=float)
    ztop[0, :, :] = top
    if botm.shape[0] > 1:
        ztop[1:, :, :] = botm[:-1, :, :]
    return 0.5 * (ztop + botm)


def _build_color_norm(values_3d: np.ndarray) -> tuple[mcolors.Normalize, bool]:
    """Choose linear or log normalization depending on value spread.

    Log normalization is activated only when:
    - all considered values are strictly positive,
    - max/min ratio is strictly greater than 10 (more than one order).
    """
    arr = np.asarray(values_3d, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError("No finite values available for color normalization")

    positive = finite[finite > 0.0]
    use_log = False
    if positive.size > 0 and positive.size == finite.size:
        vmin_pos = float(np.nanmin(positive))
        vmax_pos = float(np.nanmax(positive))
        if vmin_pos > 0.0 and (vmax_pos / vmin_pos) > 10.0:
            use_log = True

    if use_log:
        vmin = float(np.nanmin(positive))
        vmax = float(np.nanmax(positive))
        if np.isclose(vmin, vmax):
            vmax = vmin * 10.0
        return mcolors.LogNorm(vmin=vmin, vmax=vmax), True

    vmin = float(np.nanmin(finite))
    vmax = float(np.nanmax(finite))
    if np.isclose(vmin, vmax):
        vmax = vmin + max(1.0e-12, abs(vmin) * 1.0e-6)
    return mcolors.Normalize(vmin=vmin, vmax=vmax), False


def _plot_vertical_section(ax, *, values_3d: np.ndarray, sgrid, cmap, norm) -> None:
    nlay, _, ncol = values_3d.shape
    row_idx = int(values_3d.shape[1] // 2)
    section = np.asarray(values_3d[:, row_idx, :], dtype=float)
    if isinstance(norm, mcolors.LogNorm):
        section = np.ma.masked_less_equal(section, 0.0)
    x2d, _ = _extract_xy_from_sgrid(sgrid)
    x_centers = np.asarray(x2d[row_idx, :], dtype=float)
    x_edges = _centers_to_edges_1d(x_centers)

    interfaces_center = _layer_interfaces_elevation_for_row(sgrid, row_idx=row_idx)
    z_edges = np.empty((nlay + 1, ncol + 1), dtype=float)
    for ilay in range(nlay + 1):
        z_edges[ilay, :] = _centers_to_edges_1d(interfaces_center[ilay, :])
    x_edges_2d = np.tile(x_edges[None, :], (nlay + 1, 1))

    img = ax.pcolormesh(
        x_edges_2d,
        z_edges,
        section,
        shading="flat",
        cmap=cmap,
        norm=norm,
    )
    _ = img
    top_row = np.asarray(interfaces_center[0, :], dtype=float)
    bottom_row = np.asarray(interfaces_center[-1, :], dtype=float)
    ax.plot(x_centers, top_row, color="black", lw=1.1, alpha=0.95)
    ax.plot(x_centers, bottom_row, color="black", lw=0.9, alpha=0.55)

    ax.set_ylim(float(np.nanmin(bottom_row)), float(np.nanmax(top_row)))
    ax.set_title("Vertical section on SGrid layers (center row)", fontsize=TITLE_FONTSIZE)
    ax.set_xlabel("x", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("elevation [m]", fontsize=LABEL_FONTSIZE)
    ax.tick_params(labelsize=TICK_FONTSIZE)
    _disable_axis_offset(ax)
    ax.grid(False)
    _set_square_axes(ax)

def _plot_horizontal_center_section(ax, *, values_3d: np.ndarray, sgrid, cmap, norm) -> None:
    """Plot one horizontal slice at the center layer."""
    nlay, nrow, ncol = values_3d.shape
    layer_idx = int(nlay // 2)
    section = np.asarray(values_3d[layer_idx, :, :], dtype=float)
    if isinstance(norm, mcolors.LogNorm):
        section = np.ma.masked_less_equal(section, 0.0)

    x2d, y2d = _extract_xy_from_sgrid(sgrid)
    x_centers = np.asarray(x2d[0, :], dtype=float)
    y_centers = np.asarray(y2d[:, 0], dtype=float)
    x_edges = _centers_to_edges_1d(x_centers)
    y_edges = _centers_to_edges_1d(y_centers)
    x_edges_2d, y_edges_2d = np.meshgrid(x_edges, y_edges, indexing="xy")

    ax.pcolormesh(
        x_edges_2d,
        y_edges_2d,
        section,
        shading="flat",
        cmap=cmap,
        norm=norm,
    )
    ax.axhline(float(y_centers[nrow // 2]), color="black", lw=0.8, alpha=0.35)
    ax.axvline(float(x_centers[ncol // 2]), color="black", lw=0.8, alpha=0.35)

    zmid = np.asarray(_compute_layer_center_elevations(sgrid)[layer_idx, :, :], dtype=float)
    zmid_mean = float(np.nanmean(zmid))
    ax.set_title(
        f"Horizontal center section (layer {layer_idx}, z~{zmid_mean:.1f} m)",
        fontsize=TITLE_FONTSIZE,
    )
    ax.set_xlabel("x", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("y", fontsize=LABEL_FONTSIZE)
    ax.tick_params(labelsize=TICK_FONTSIZE)
    _disable_axis_offset(ax)
    ax.grid(False)
    _set_square_axes(ax)


def _plot_additional_profile(ax, *, values_3d: np.ndarray, sgrid, norm, value_label: str) -> None:
    """Plot one additional 1D vertical profile at the center cell."""
    nlay, nrow, ncol = values_3d.shape
    row_idx = int(nrow // 2)
    col_idx = int(ncol // 2)
    depth_3d = _compute_layer_center_depths(sgrid)
    depth_vals = np.asarray(depth_3d[:, row_idx, col_idx], dtype=float)
    profile = np.asarray(values_3d[:, row_idx, col_idx], dtype=float)

    if isinstance(norm, mcolors.LogNorm):
        valid = np.isfinite(profile) & (profile > 0.0) & np.isfinite(depth_vals)
    else:
        valid = np.isfinite(profile) & np.isfinite(depth_vals)

    if np.any(valid):
        ax.plot(profile[valid], depth_vals[valid], color="black", lw=1.3)
        if isinstance(norm, mcolors.LogNorm):
            ax.set_xscale("log")
        ax.invert_yaxis()
    else:
        ax.text(
            0.5,
            0.5,
            "no valid values",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=8,
        )

    ax.set_title("Additional profile: center cell vs depth", fontsize=TITLE_FONTSIZE)
    if isinstance(norm, mcolors.LogNorm):
        ax.set_xlabel(f"{value_label} (log)", fontsize=LABEL_FONTSIZE)
    else:
        ax.set_xlabel(value_label, fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("depth [m]", fontsize=LABEL_FONTSIZE)
    finite_depth = np.isfinite(depth_vals)
    if np.any(finite_depth):
        ax.set_ylim(
            float(np.nanmax(depth_vals[finite_depth])),
            float(np.nanmin(depth_vals[finite_depth])),
        )
    ax.tick_params(labelsize=TICK_FONTSIZE)
    ax.grid(False)
    _set_square_axes(ax)
    ax.text(
        0.03,
        0.97,
        f"row={row_idx}, col={col_idx}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=6,
    )


def _plot_3d_demo_figure(
    *,
    values_3d: np.ndarray,
    sgrid,
    field_param: FieldParam,
    title: str,
    subtitle: str | None,
    output_path: Path,
    show_plot: bool,
    norm: mcolors.Normalize | None = None,
    use_log: bool | None = None,
):
    arr3d = np.asarray(values_3d, dtype=float)
    if norm is None:
        norm, use_log_auto = _build_color_norm(arr3d)
        if use_log is None:
            use_log = bool(use_log_auto)
    if use_log is None:
        use_log = isinstance(norm, mcolors.LogNorm)
    cmap = plt.get_cmap("hsv")

    fig = plt.figure(figsize=(16.8, 6.8), dpi=150)
    grid = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.0, 1.0], wspace=0.34)
    ax_left = fig.add_subplot(grid[0, 0])
    ax_mid = fig.add_subplot(grid[0, 1])
    ax_right = fig.add_subplot(grid[0, 2])

    _plot_horizontal_center_section(
        ax_left,
        values_3d=arr3d,
        sgrid=sgrid,
        cmap=cmap,
        norm=norm,
    )
    _plot_vertical_section(
        ax_mid,
        values_3d=arr3d,
        sgrid=sgrid,
        cmap=cmap,
        norm=norm,
    )
    _plot_additional_profile(
        ax_right,
        values_3d=arr3d,
        sgrid=sgrid,
        norm=norm,
        value_label=str(field_param.identifier),
    )

    mappable = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    mappable.set_array([])

    title_text = str(title).strip()
    subtitle_text = str(subtitle).strip() if subtitle is not None else ""
    if subtitle_text:
        fig.suptitle(f"{title_text}\n{subtitle_text}", fontsize=10, y=0.985)
    else:
        fig.suptitle(title_text, fontsize=10, y=0.985)
    fig.subplots_adjust(left=0.05, right=0.96, bottom=0.10, top=0.88, wspace=0.32)

    # Compact colorbar placed immediately to the right of the center panel.
    pos_mid = ax_mid.get_position()
    pos_right = ax_right.get_position()
    gap = 0.006
    cax_x = pos_mid.x1 + gap
    free_width = max(0.004, pos_right.x0 - cax_x - gap)
    cax_w = min(0.009, free_width)
    cax_h = pos_mid.height * 0.58
    cax_y = pos_mid.y0 + 0.5 * (pos_mid.height - cax_h)
    cax = fig.add_axes([cax_x, cax_y, cax_w, cax_h])
    cbar = fig.colorbar(mappable, cax=cax)
    if use_log:
        cbar.set_label(
            f"{field_param.identifier} value (log scale)",
            fontsize=max(6, LABEL_FONTSIZE - 1),
        )
    else:
        cbar.set_label(f"{field_param.identifier} value", fontsize=max(6, LABEL_FONTSIZE - 1))
    cbar.ax.tick_params(labelsize=max(5, TICK_FONTSIZE - 1))
    fig.savefig(output_path)
    print(f"saved_figure={output_path}")

    if not show_plot:
        plt.close(fig)
        return None
    return fig


def _show_figures_blocking(*figures) -> None:
    visible = [fig for fig in figures if fig is not None]
    if not visible:
        return
    print(f"matplotlib_backend={plt.get_backend()}")
    print("showing_figure=interactive_blocking")
    # Force blocking behavior even when an interactive backend is active.
    plt.ioff()
    for fig in visible:
        try:
            manager = getattr(fig.canvas, "manager", None)
            if manager is not None and hasattr(manager, "show"):
                manager.show()
            fig.show()
        except Exception:
            continue
    plt.pause(0.05)
    plt.show(block=True)
    for fig in visible:
        plt.close(fig)


def _reshape_to_sgrid_2d(arr, *, nrow: int, ncol: int) -> np.ndarray:
    values = np.asarray(arr, dtype=float)
    if values.ndim == 2 and values.shape == (nrow, ncol):
        return values
    return values.reshape((nrow, ncol))


def _build_projected_field_on_sgrid_3d(
    *,
    field_discretization,
    field_param: FieldParam,
    sgrid,
) -> np.ndarray:
    """Build the projected field on SGrid before vertical correction.

    Strategy:
    1) evaluate `FieldParam` at depth=0 on the planar SGrid support,
    2) extrude this planar map uniformly across all layers.
    """
    nrow = int(getattr(sgrid, "nrow"))
    ncol = int(getattr(sgrid, "ncol"))
    nlay = int(getattr(sgrid, "nlay"))
    projected_surface = field_param.to_mesh_field(field_discretization, depth=0.0)
    surface_2d = _reshape_to_sgrid_2d(projected_surface.cell_values, nrow=nrow, ncol=ncol)
    return np.repeat(surface_2d[None, :, :], nlay, axis=0)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not bool(args.no_show_plot):
        _ensure_gui_backend_for_blocking_show()
    config_path = _resolve_config_path(args.config_file)
    cfg = SGridFieldParamDiscretizationConfig.from_toml(config_path, section=args.section)

    print(f"config={config_path}")
    print("step=run_discretization_case")
    result = run_discretization_case(cfg)
    field_param = FieldParam.from_dict(cfg.field_param)
    sgrid = build_sgrid_from_config(SGridConfig.from_mapping(cfg.sgrid))
    values_3d = np.asarray(result.values_3d, dtype=float)
    projected_field_3d = _build_projected_field_on_sgrid_3d(
        field_discretization=result.field_discretization,
        field_param=field_param,
        sgrid=sgrid,
    )
    output_path = _resolve_output_path(args.output_figure, config_path=config_path)
    output_field_path = _resolve_output_path(args.output_field_figure, config_path=config_path)

    combined = np.concatenate(
        [
            np.asarray(values_3d, dtype=float).reshape(-1),
            np.asarray(projected_field_3d, dtype=float).reshape(-1),
        ]
    )
    shared_norm, shared_use_log = _build_color_norm(combined)

    print(f"shape_3d={values_3d.shape}")
    print(f"min_3d={float(np.nanmin(values_3d)):.6g}")
    print(f"max_3d={float(np.nanmax(values_3d)):.6g}")
    print(f"projected_shape_3d={projected_field_3d.shape}")
    print(f"projected_min_3d={float(np.nanmin(projected_field_3d)):.6g}")
    print(f"projected_max_3d={float(np.nanmax(projected_field_3d)):.6g}")

    mode = str(field_param.vertical_profile.get("mode", "none"))
    char_depth = field_param.vertical_profile.get("characteristic_depth")
    if mode == "exponential" and char_depth is not None:
        final_subtitle = f"vertical profile: exponential (characteristic_depth={float(char_depth):.3g} m)"
    else:
        final_subtitle = f"vertical profile: {mode}"

    fig_final = _plot_3d_demo_figure(
        values_3d=values_3d,
        sgrid=sgrid,
        field_param=field_param,
        title="Final 3D values array: permeability extrusion and depth evolution",
        subtitle=final_subtitle,
        output_path=output_path,
        show_plot=(not bool(args.no_show_plot)),
        norm=shared_norm,
        use_log=shared_use_log,
    )
    fig_projected = _plot_3d_demo_figure(
        values_3d=projected_field_3d,
        sgrid=sgrid,
        field_param=field_param,
        title="Projected FieldParam array (depth=0 extruded over layers)",
        subtitle=(
            "same plotting layout and color scale as final-values figure; "
            "no vertical decay by construction"
        ),
        output_path=output_field_path,
        show_plot=(not bool(args.no_show_plot)),
        norm=shared_norm,
        use_log=shared_use_log,
    )
    if not bool(args.no_show_plot):
        _show_figures_blocking(fig_final, fig_projected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
