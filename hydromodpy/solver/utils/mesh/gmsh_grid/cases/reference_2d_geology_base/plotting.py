"""Plotting helpers for the reference 2D geology-on-Gmsh case."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import geopandas as gpd
import matplotlib.ticker as mticker
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import ListedColormap
from shapely.geometry import box

from hydromodpy.solver.utils.mesh.gmsh_grid import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.plot_window_utils import maximize_figure_windows
from hydromodpy.spatial.field.geology.geology_field import GeologyField

from .reporting import dominant_zone_indices, normalize_zone_key


def disable_axis_offset(ax) -> None:
    """Disable offset formatting on both axes for projected coordinates."""

    ax.ticklabel_format(style="plain", axis="both", useOffset=False)
    ax.xaxis.get_major_formatter().set_useOffset(False)
    ax.yaxis.get_major_formatter().set_useOffset(False)
    ax.xaxis.get_offset_text().set_visible(False)
    ax.yaxis.get_offset_text().set_visible(False)


def maybe_scientific_colorbar(cbar, values) -> None:
    """Switch the colorbar formatter when values span extreme magnitudes."""

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
    keys = gdf[code_field].map(normalize_zone_key)
    unique_keys = sorted(np.unique(keys.to_numpy()).tolist())
    if name_field is None:
        return {key: key for key in unique_keys}

    out: dict[str, str] = {}
    for key in unique_keys:
        names = gdf.loc[keys == key, name_field].astype(str).str.strip()
        names = names[(names != "") & (names.str.lower() != "nan") & (names.str.lower() != "none")]
        out[key] = str(names.value_counts().index[0]) if not names.empty else key
    return out


def add_zone_cartouches(ax, entries: list[tuple[tuple[float, float, float, float], str]]) -> int:
    """Add one small legend-like cartouche strip under the raw-geology panel."""

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
        x = 0.02 + col * 0.49
        y = y0 - row * row_step
        short = label if len(label) <= 42 else (label[:39] + "...")
        ax.text(
            x,
            y,
            short,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=6,
            color="0.10",
            bbox={
                "boxstyle": "round,pad=0.14",
                "fc": rgba,
                "ec": "0.30",
                "lw": 0.35,
                "alpha": 0.98,
            },
            clip_on=False,
        )
    return n_rows


def _draw_mesh_edges(ax, mesh: GmshPlanarMesh2D, *, color: str = "0.25", lw: float = 0.35) -> None:
    for cell in mesh.cells:
        vertices = np.asarray(cell.vertices, dtype=float)
        closed = np.vstack((vertices, vertices[0]))
        ax.plot(closed[:, 0], closed[:, 1], color=color, lw=lw, alpha=0.70)


def plot_left_raw_geology(
    ax,
    *,
    geology_cfg: Mapping[str, object],
    geology_field: GeologyField,
    mesh,
    return_zone_colors: bool = False,
):
    """Plot raw geology support clipped to the mesh extent plus mesh edges."""

    source_cfg = dict(geology_cfg.get("source", {}))
    source_kind = str(source_cfg.get("kind", "auto")).strip().lower()
    source_path = Path(str(source_cfg.get("path", "")))
    code_field = str(source_cfg.get("code_field", "CODE_LEG")).strip()

    xmin = float(np.nanmin(mesh.x_plot))
    xmax = float(np.nanmax(mesh.x_plot))
    ymin = float(np.nanmin(mesh.y_plot))
    ymax = float(np.nanmax(mesh.y_plot))
    mesh_bbox = box(xmin, ymin, xmax, ymax)

    cartouches: list[tuple[tuple[float, float, float, float], str]] = []
    zone_color_by_key: dict[str, tuple[float, float, float, float]] = {}
    plotted = False
    if source_kind in {"vector", "auto"} and source_path.exists():
        gdf = gpd.read_file(source_path)
        if not gdf.empty and code_field in gdf.columns:
            gdf_sel = gdf[gdf.intersects(mesh_bbox)].copy()
            if not gdf_sel.empty:
                zone = gdf_sel[code_field].map(normalize_zone_key)
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
                    cartouches.append((rgba, f"{zone_name_by_key.get(key, key)} [{key}]"))
                plotted = True

    if not plotted:
        geology_codes = np.asarray(geology_field.encoded_codes, dtype=float)
        geology_masked = np.ma.masked_where(geology_codes <= 0, geology_codes)
        unique_codes = np.unique(np.asarray(geology_codes[geology_codes > 0], dtype=int))
        n_classes = max(1, int(unique_codes.size))
        cmap_geo = plt.get_cmap("tab20", min(20, n_classes))
        ax.imshow(
            geology_masked,
            origin="lower",
            extent=[xmin, xmax, ymin, ymax],
            cmap=cmap_geo,
            interpolation="nearest",
            aspect="equal",
        )
        denom = max(float(len(unique_codes) - 1), 1.0)
        for idx, code in enumerate(unique_codes):
            zone_color_by_key[normalize_zone_key(code)] = cmap_geo(float(idx) / denom)

    _draw_mesh_edges(ax, mesh, color="0.15", lw=0.30)
    ax.set_title("Raw geology + Gmsh mesh", fontsize=9)
    ax.set_xlabel("x [m]", fontsize=7)
    ax.set_ylabel("y [m]", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_aspect("equal")
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    disable_axis_offset(ax)
    if return_zone_colors:
        return cartouches, zone_color_by_key
    return cartouches


def plot_center_mesh_geology(
    ax,
    *,
    field_discretization,
    zone_color_by_key: Mapping[str, tuple[float, float, float, float]] | None = None,
    fig,
) -> tuple[tuple[str, ...], int, int]:
    """Plot the dominant geology zone per mesh cell."""

    dominant_idx, zone_keys, mixed_count, undefined_count = dominant_zone_indices(
        field_discretization
    )
    mesh = field_discretization.mesh
    fallback_cmap = plt.get_cmap("tab20", max(2, min(20, len(zone_keys))))
    denom = max(float(len(zone_keys) - 1), 1.0)
    zone_colors = [
        (
            zone_color_by_key.get(key, fallback_cmap(float(idx) / denom))
            if zone_color_by_key is not None
            else fallback_cmap(float(idx) / denom)
        )
        for idx, key in enumerate(zone_keys)
    ]
    mappable = mesh.plot_cell_values(
        ax,
        dominant_idx,
        cmap=ListedColormap(zone_colors),
        show_mesh=True,
        vmin=-0.5,
        vmax=(0.5 if len(zone_keys) == 1 else float(len(zone_keys) - 0.5)),
    )
    cbar = fig.colorbar(mappable, ax=ax, shrink=0.72, pad=0.02)
    cbar.set_label("dominant geology zone on Gmsh mesh", fontsize=7)
    cbar.ax.tick_params(labelsize=6)
    if len(zone_keys) <= 12:
        cbar.set_ticks(np.arange(len(zone_keys), dtype=float))
        cbar.set_ticklabels(zone_keys)
    else:
        cbar.set_ticks([])

    ax.set_title(
        f"Geology discretized on Gmsh mesh (left colors)\nmixed={mixed_count} | undefined={undefined_count}",
        fontsize=9,
    )
    ax.set_xlabel("x [m]", fontsize=7)
    ax.set_ylabel("y [m]", fontsize=7)
    ax.tick_params(labelsize=6)
    disable_axis_offset(ax)
    return zone_keys, mixed_count, undefined_count


def plot_right_field_values(ax, *, mesh, mesh_values, fig) -> None:
    """Plot the final FieldParam values on the planar mesh."""

    values = np.asarray(mesh.to_cell_values(mesh_values.cell_values), dtype=float).reshape(-1)
    mappable = mesh.plot_cell_values(ax, values, cmap="viridis", show_mesh=True)
    cbar = fig.colorbar(mappable, ax=ax, shrink=0.72, pad=0.02)
    cbar.set_label("field parameter value", fontsize=7)
    cbar.ax.tick_params(labelsize=6)
    maybe_scientific_colorbar(cbar, values)

    ax.set_title("Final FieldParam values on Gmsh mesh", fontsize=9)
    ax.set_xlabel("x [m]", fontsize=7)
    ax.set_ylabel("y [m]", fontsize=7)
    ax.tick_params(labelsize=6)
    disable_axis_offset(ax)


def show_figures_blocking(*figures) -> None:
    """Show figures with best-effort window management for manual QA."""

    visible = [fig for fig in figures if fig is not None]
    if not visible:
        return
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


def build_reference_case_figure(
    *,
    cfg: Mapping[str, object],
    geology_field: GeologyField,
    mesh: GmshPlanarMesh2D,
    field_discretization,
    mesh_values,
):
    """Build the 3-panel QA figure used by the reference 2D case."""

    fig, axes = plt.subplots(1, 3, figsize=(24.0, 9.4), dpi=150)
    cartouches, zone_color_by_key = plot_left_raw_geology(
        axes[0],
        geology_cfg=cfg["geology"],
        geology_field=geology_field,
        mesh=mesh,
        return_zone_colors=True,
    )
    plot_center_mesh_geology(
        axes[1],
        field_discretization=field_discretization,
        zone_color_by_key=zone_color_by_key,
        fig=fig,
    )
    plot_right_field_values(axes[2], mesh=mesh, mesh_values=mesh_values, fig=fig)
    n_cartouche_rows = add_zone_cartouches(axes[0], cartouches)
    fig.suptitle(
        "Visual QA: raw geology -> mesh discretization -> FieldParam values on Gmsh mesh",
        fontsize=10,
    )
    bottom_margin = 0.12 + min(0.14, 0.035 * max(0, n_cartouche_rows))
    fig.tight_layout(rect=[0, bottom_margin, 1, 0.95])
    return fig


__all__ = [
    "build_reference_case_figure",
    "disable_axis_offset",
    "maybe_scientific_colorbar",
    "plot_center_mesh_geology",
    "plot_left_raw_geology",
    "plot_right_field_values",
    "show_figures_blocking",
]
