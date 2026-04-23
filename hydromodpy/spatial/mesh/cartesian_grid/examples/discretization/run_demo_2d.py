"""CLI demo for standalone FieldParam discretization on SGrid (2D views)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.ticker as mticker
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Rectangle
from shapely.geometry import box


def _configure_matplotlib_backend_from_argv(argv: list[str]) -> None:
    """Use a non-interactive backend by default; switch later only for show()."""
    try:
        matplotlib.use("Agg", force=True)
    except Exception:
        pass


_configure_matplotlib_backend_from_argv(sys.argv[1:])

import matplotlib.pyplot as plt

plt.switch_backend("Agg")


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

from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.geology.geology_field import GeologyField
from hydromodpy.spatial.mesh.cartesian_grid.examples.discretization.case_runner import (
    run_discretization_case,
)
from hydromodpy.spatial.mesh.cartesian_grid.examples.discretization.run_demo_config import (
    SGridFieldParamDiscretizationConfig,
)
from hydromodpy.spatial.mesh.plot_window_utils import maximize_figure_windows

DEFAULT_CONFIG_FILE = "run_demo_config_2d.toml"
DEFAULT_SECTION = "case"
DEFAULT_OUTPUT_FIGURE = "outputs/sgrid_fieldparam_discretization_2d_demo.png"

TITLE_FONTSIZE = 9
LABEL_FONTSIZE = 7
TICK_FONTSIZE = 6


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Discretize one FieldParam on one SGrid through one geology field, "
            "without running full Modflow workflow."
        )
    )
    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
        help=(
            "Path to discretization case TOML. "
            f"Default: {DEFAULT_CONFIG_FILE} (resolved from current directory, "
            "then fallback to this script directory)."
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
            "Output PNG path for the 3-panel visual check. "
            f"Default: {DEFAULT_OUTPUT_FIGURE} (relative to config file directory)."
        ),
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not open interactive figure window.",
    )
    return parser.parse_args(argv)


def _resolve_config_path(raw_config: str) -> Path:
    """Resolve config path robustly for direct-script and module execution."""
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
        f"Config TOML not found: '{raw_config}'. Tried '{cwd_candidate}' and '{script_candidate}'."
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


def _disable_axis_offset(ax) -> None:
    """Disable scientific offset text like '+6.7e6' on axis ticks."""
    ax.ticklabel_format(style="plain", axis="both", useOffset=False)
    ax.xaxis.get_major_formatter().set_useOffset(False)
    ax.yaxis.get_major_formatter().set_useOffset(False)
    ax.xaxis.get_offset_text().set_visible(False)
    ax.yaxis.get_offset_text().set_visible(False)


def _maybe_scientific_colorbar(cbar, values) -> None:
    """Switch colorbar ticks to scientific notation when values are very small/large."""
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return
    absmax = float(np.nanmax(np.abs(finite)))
    use_scientific = (absmax > 0.0 and absmax < 1e-2) or absmax >= 1e4
    if use_scientific:
        cbar.formatter = mticker.FormatStrFormatter("%.2e")
    else:
        cbar.formatter = mticker.ScalarFormatter(useMathText=False)
    cbar.update_ticks()


def _select_name_field(gdf, *, code_field: str) -> str | None:
    for candidate in ("LITHOLOGIE", "NOM_LEG", "LIBELLE", "name", "NAME"):
        if candidate in gdf.columns and candidate != code_field:
            return candidate
    return None


def _build_zone_name_by_key(gdf, *, code_field: str, name_field: str | None) -> dict[str, str]:
    keys = gdf[code_field].map(_normalize_zone_key)
    unique_keys = sorted(np.unique(keys.to_numpy()).tolist())
    if name_field is None:
        return {key: key for key in unique_keys}

    out: dict[str, str] = {}
    for key in unique_keys:
        names = gdf.loc[keys == key, name_field].astype(str).str.strip()
        names = names[(names != "") & (names.str.lower() != "nan") & (names.str.lower() != "none")]
        out[key] = str(names.value_counts().index[0]) if not names.empty else key
    return out


def _normalize_zone_key(raw: object) -> str:
    if isinstance(raw, (int, np.integer)):
        return str(int(raw))
    if isinstance(raw, (float, np.floating)):
        value = float(raw)
        if np.isfinite(value) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(raw).strip()


def _add_zone_cartouches(ax, entries: list[tuple[tuple[float, float, float, float], str]]) -> int:
    """Draw geology legend lines below left panel and return number of rows used."""
    if not entries:
        return 0
    max_entries = 10
    shown = entries[:max_entries]
    n_per_row = 2
    n_rows = int(np.ceil(len(shown) / float(n_per_row)))
    row_step = 0.072
    y0 = -0.13

    for i, (rgba, label) in enumerate(shown):
        row = i // n_per_row
        col = i % n_per_row
        # Per-column anchor and line baseline (in axes coordinates).
        x = 0.02 + col * 0.49
        y = y0 - row * row_step
        short = label if len(label) <= 42 else (label[:39] + "...")

        # Color swatch rectangle.
        rect = Rectangle(
            (x, y - 0.028),
            0.026,
            0.026,
            transform=ax.transAxes,
            facecolor=rgba,
            edgecolor="0.30",
            linewidth=0.50,
            clip_on=False,
        )
        ax.add_patch(rect)

        # Label text (cartouche style, neutral background).
        ax.text(
            x + 0.034,
            y - 0.002,
            short,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=6,
            color="0.10",
            bbox={
                "boxstyle": "round,pad=0.14",
                "fc": "white",
                "ec": "0.82",
                "lw": 0.35,
                "alpha": 0.98,
            },
            clip_on=False,
        )
    if len(entries) > len(shown):
        ax.text(
            0.02,
            y0 - n_rows * row_step,
            f"... +{len(entries) - len(shown)} more",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=6,
            color="0.20",
            clip_on=False,
        )
        n_rows += 1
    return n_rows


def _plot_left_raw_geology(
    ax,
    *,
    cfg: SGridFieldParamDiscretizationConfig,
    geology_field: GeologyField,
    mesh,
) -> tuple[
    list[tuple[tuple[float, float, float, float], str]],
    dict[str, tuple[float, float, float, float]],
]:
    """Left panel: raw geology polygons in real coordinates."""
    source_cfg = dict(cfg.geology.get("source", {}))
    source_kind = str(source_cfg.get("kind", "auto")).strip().lower()
    source_path = Path(str(source_cfg.get("path", "")))
    code_field = str(source_cfg.get("code_field", "CODE_LEG")).strip()

    xmin = float(np.nanmin(mesh.x_plot))
    xmax = float(np.nanmax(mesh.x_plot))
    ymin = float(np.nanmin(mesh.y_plot))
    ymax = float(np.nanmax(mesh.y_plot))
    mesh_bbox = box(xmin, ymin, xmax, ymax)

    plotted = False
    cartouches: list[tuple[tuple[float, float, float, float], str]] = []
    zone_color_by_key: dict[str, tuple[float, float, float, float]] = {}
    if source_kind in {"vector", "auto"} and source_path.exists():
        gdf = gpd.read_file(source_path)
        if not gdf.empty and code_field in gdf.columns:
            gdf_sel = gdf[gdf.intersects(mesh_bbox)].copy()
            if not gdf_sel.empty:
                zone = gdf_sel[code_field].map(_normalize_zone_key)
                unique_keys = sorted(np.unique(zone.to_numpy()).tolist())
                key_to_idx = {key: idx for idx, key in enumerate(unique_keys)}
                gdf_plot = gdf_sel.copy()
                gdf_plot["zone_idx"] = zone.map(key_to_idx).astype(float)
                name_field = _select_name_field(gdf_plot, code_field=code_field)
                zone_name_by_key = _build_zone_name_by_key(
                    gdf_plot,
                    code_field=code_field,
                    name_field=name_field,
                )

                cmap_geo = plt.get_cmap("tab20", max(2, min(20, len(unique_keys))))
                gdf_plot.plot(
                    column="zone_idx",
                    ax=ax,
                    cmap=cmap_geo,
                    linewidth=0.15,
                    edgecolor="0.35",
                    legend=False,
                )
                denom = max(float(len(unique_keys) - 1), 1.0)
                for key in unique_keys:
                    idx = key_to_idx[key]
                    rgba = cmap_geo(float(idx) / denom)
                    zone_color_by_key[key] = rgba
                    name = zone_name_by_key.get(key, key)
                    cartouches.append((rgba, f"{name} [{key}]"))
                plotted = True

    if not plotted:
        # Fallback display if raw vector cannot be drawn.
        geology_codes = np.asarray(geology_field.encoded_codes, dtype=float)
        geology_masked = np.ma.masked_where(geology_codes <= 0, geology_codes)
        n_classes = max(1, int(np.nanmax(geology_codes)))
        cmap_geo = plt.get_cmap("tab20", min(20, n_classes))
        ax.imshow(
            geology_masked,
            origin="lower",
            extent=[xmin, xmax, ymin, ymax],
            cmap=cmap_geo,
            interpolation="nearest",
            aspect="equal",
        )
        # Build coarse fallback cartouches from encoded classes only.
        unique_codes = np.unique(np.asarray(geology_codes[geology_codes > 0], dtype=int))
        denom = max(float(len(unique_codes) - 1), 1.0)
        for idx, code in enumerate(unique_codes):
            rgba = cmap_geo(float(idx) / denom)
            zone_color_by_key[_normalize_zone_key(code)] = rgba
        for idx, code in enumerate(unique_codes[:18]):
            rgba = cmap_geo(float(idx) / denom)
            cartouches.append((rgba, f"class {int(code)}"))

    ax.set_title("Raw geology (shapefile, real coordinates)", fontsize=TITLE_FONTSIZE)
    ax.set_xlabel("x [m]", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("y [m]", fontsize=LABEL_FONTSIZE)
    ax.tick_params(labelsize=TICK_FONTSIZE)
    ax.set_aspect("equal")
    # Force exactly the same displayed zone as center panel (mesh extent).
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    _disable_axis_offset(ax)
    return cartouches, zone_color_by_key


def _plot_center_mesh_discretization(
    ax,
    *,
    mesh,
    mesh_values,
    field_discretization,
    zone_color_by_key: dict[str, tuple[float, float, float, float]],
    fig,
) -> None:
    """Center panel: FieldParam mapped on intermediate mesh, real coordinates."""
    used_geology_colors = False
    img = None
    if field_discretization is not None and hasattr(field_discretization, "weighted_components"):
        try:
            zone_keys_raw, fractions_by_zone = field_discretization.weighted_components()
            zone_keys = [_normalize_zone_key(key) for key in zone_keys_raw]
            if len(zone_keys) > 0:
                fallback_cmap = plt.get_cmap("tab20", max(2, min(20, len(zone_keys))))
                denom = max(float(len(zone_keys) - 1), 1.0)
                zone_colors = [
                    zone_color_by_key.get(key, fallback_cmap(float(idx) / denom))
                    for idx, key in enumerate(zone_keys)
                ]
                dominant_idx = np.full(int(mesh.n_cells), -1, dtype=int)
                dominant_frac = np.zeros(int(mesh.n_cells), dtype=float)
                for idx, raw_key in enumerate(zone_keys_raw):
                    frac = np.asarray(
                        mesh.to_cell_values(fractions_by_zone[raw_key]),
                        dtype=float,
                    ).reshape(-1)
                    valid = np.isfinite(frac)
                    better = valid & (frac > dominant_frac)
                    dominant_frac[better] = frac[better]
                    dominant_idx[better] = idx

                dominant_grid = np.asarray(
                    mesh.to_cell_values(dominant_idx.astype(float)),
                    dtype=float,
                )
                dominant_masked = np.ma.masked_where(dominant_grid < 0.0, dominant_grid)
                vmax = 0.5 if len(zone_colors) == 1 else float(len(zone_colors) - 0.5)
                img = ax.pcolormesh(
                    mesh.x_plot,
                    mesh.y_plot,
                    dominant_masked,
                    shading="flat",
                    cmap=ListedColormap(zone_colors),
                    vmin=-0.5,
                    vmax=vmax,
                )
                cbar = fig.colorbar(img, ax=ax, shrink=0.72, pad=0.02)
                cbar.set_label(
                    "dominant geology zone on intermediary mesh", fontsize=LABEL_FONTSIZE
                )
                cbar.ax.tick_params(labelsize=TICK_FONTSIZE)
                if len(zone_keys) <= 12:
                    cbar.set_ticks(np.arange(len(zone_keys), dtype=float))
                    cbar.set_ticklabels(zone_keys)
                else:
                    cbar.set_ticks([])
                used_geology_colors = True
        except Exception:
            used_geology_colors = False

    if not used_geology_colors:
        cell_values = np.asarray(mesh.to_cell_values(mesh_values.cell_values), dtype=float)
        img = ax.pcolormesh(
            mesh.x_plot,
            mesh.y_plot,
            cell_values,
            shading="flat",
            cmap="hsv",
        )
        cbar = fig.colorbar(img, ax=ax, shrink=0.72, pad=0.02)
        cbar.set_label("parameter on intermediary mesh", fontsize=LABEL_FONTSIZE)
        cbar.ax.tick_params(labelsize=TICK_FONTSIZE)
        _maybe_scientific_colorbar(cbar, cell_values)

    for j in range(mesh.x_plot.shape[0]):
        ax.plot(mesh.x_plot[j, :], mesh.y_plot[j, :], color="0.80", lw=0.25)
    for i in range(mesh.x_plot.shape[1]):
        ax.plot(mesh.x_plot[:, i], mesh.y_plot[:, i], color="0.80", lw=0.25)

    if used_geology_colors:
        ax.set_title(
            "Discretization on intermediary mesh (geology colors)", fontsize=TITLE_FONTSIZE
        )
    else:
        ax.set_title("Discretization on intermediary mesh", fontsize=TITLE_FONTSIZE)
    ax.set_xlabel("x [m]", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("y [m]", fontsize=LABEL_FONTSIZE)
    ax.tick_params(labelsize=TICK_FONTSIZE)
    ax.set_aspect("equal")
    ax.set_xlim(float(np.nanmin(mesh.x_plot)), float(np.nanmax(mesh.x_plot)))
    ax.set_ylim(float(np.nanmin(mesh.y_plot)), float(np.nanmax(mesh.y_plot)))
    _disable_axis_offset(ax)


def _plot_right_final_grid(ax, *, values_2d: np.ndarray, fig) -> None:
    """Right panel: final solver grid in row/col index space."""
    arr = np.asarray(values_2d, dtype=float)
    img = ax.imshow(
        arr,
        origin="upper",
        cmap="hsv",
        interpolation="nearest",
    )
    cbar = fig.colorbar(img, ax=ax, shrink=0.72, pad=0.02)
    cbar.set_label("parameter value", fontsize=LABEL_FONTSIZE)
    cbar.ax.tick_params(labelsize=TICK_FONTSIZE)
    _maybe_scientific_colorbar(cbar, arr)

    ax.set_title("Final grid (row/col indices)", fontsize=TITLE_FONTSIZE)
    ax.set_xlabel("column", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("row", fontsize=LABEL_FONTSIZE)
    ax.tick_params(labelsize=TICK_FONTSIZE)
    # Draw row/column cell grid on top of final array.
    nrow, ncol = arr.shape
    ax.set_xticks(np.arange(-0.5, ncol, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, nrow, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.22, alpha=0.35)
    ax.tick_params(which="minor", bottom=False, left=False)


def _plot_geology_and_result(
    *,
    cfg: SGridFieldParamDiscretizationConfig,
    geology_field: GeologyField,
    mesh,
    mesh_values,
    field_discretization,
    values_2d: np.ndarray,
    output_path: Path,
    show_plot: bool,
):
    if not show_plot:
        try:
            plt.switch_backend("Agg")
        except Exception:
            pass
    fig, axes = plt.subplots(1, 3, figsize=(24.0, 9.4), dpi=150)
    ax_left, ax_center, ax_right = axes

    cartouches, zone_color_by_key = _plot_left_raw_geology(
        ax_left,
        cfg=cfg,
        geology_field=geology_field,
        mesh=mesh,
    )
    _plot_center_mesh_discretization(
        ax_center,
        mesh=mesh,
        mesh_values=mesh_values,
        field_discretization=field_discretization,
        zone_color_by_key=zone_color_by_key,
        fig=fig,
    )
    _plot_right_final_grid(
        ax_right,
        values_2d=values_2d,
        fig=fig,
    )
    n_cartouche_rows = _add_zone_cartouches(ax_left, cartouches)

    fig.suptitle(
        "Visual QA: raw geology -> mesh discretization -> solver grid",
        fontsize=10,
    )
    bottom_margin = 0.12 + min(0.14, 0.035 * max(0, n_cartouche_rows))
    fig.tight_layout(rect=[0, bottom_margin, 1, 0.95])
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
    maximize_figure_windows(*visible)
    plt.pause(0.05)
    plt.show(block=True)
    for fig in visible:
        plt.close(fig)


def main(argv=None) -> int:
    args = _parse_args(argv)
    if not bool(args.no_show_plot):
        _ensure_gui_backend_for_blocking_show()
    config_path = _resolve_config_path(args.config_file)
    cfg = SGridFieldParamDiscretizationConfig.from_toml(config_path, section=args.section)

    print(f"config={config_path}")
    print("step=run_discretization_case")
    result = run_discretization_case(cfg)
    geology_field = GeologyField.from_dict(cfg.geology)
    field_param = FieldParam.from_dict(cfg.field_param)
    print("step=field_param_to_mesh")
    mesh_values = field_param.to_mesh_field(
        result.field_discretization,
        depth=float(cfg.depth),
    )

    arr = np.asarray(result.values_2d, dtype=float)
    arr3d = np.asarray(result.values_3d, dtype=float)
    print(f"shape={arr.shape}")
    print(f"shape_3d={arr3d.shape}")
    print(f"min={float(np.nanmin(arr)):.6g}")
    print(f"max={float(np.nanmax(arr)):.6g}")

    output_path = _resolve_output_path(args.output_figure, config_path=config_path)
    print("step=build_figure")
    fig = _plot_geology_and_result(
        cfg=cfg,
        geology_field=geology_field,
        mesh=result.mesh,
        mesh_values=mesh_values,
        field_discretization=result.field_discretization,
        values_2d=arr,
        output_path=output_path,
        show_plot=(not bool(args.no_show_plot)),
    )
    if not bool(args.no_show_plot):
        _show_figures_blocking(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
