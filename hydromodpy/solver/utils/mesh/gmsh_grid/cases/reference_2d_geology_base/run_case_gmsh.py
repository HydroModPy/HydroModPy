"""Run the reference 2D geology-to-mesh workflow on a planar Gmsh mesh.

This script is the didactic starting point for the Gmsh backend. It loads a
mesh and a geology source from TOML config, discretizes the geology support and
the target FieldParam on the mesh, then builds figures and summary JSON files.

It stays outside the solver stack on purpose, so the reader can understand the
field-to-mesh pipeline without mixing in transport or MODFLOW concerns.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import tomllib
from typing import Any

import geopandas as gpd
from matplotlib import pyplot as plt
from matplotlib.colors import ListedColormap
import matplotlib.ticker as mticker
import numpy as np
from shapely.geometry import box

from hydromodpy.data_managers.variables.geology.config_cases import validate_geology_config_data
from hydromodpy.field.geology.geology_field import GeologyField
from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
    validate_resolved_field_param_data,
)
from hydromodpy.solver.utils._config_helpers import get_nested_section, resolve_path
from hydromodpy.solver.utils.mesh.gmsh_grid import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.plotting_utils import (
    ensure_interactive_backend_for_show,
)
from hydromodpy.solver.utils.mesh.plot_window_utils import maximize_figure_windows

plt.switch_backend("Agg")


DEFAULT_CONFIG_FILE = "case_config_gmsh.toml"
DEFAULT_SECTION = "case"


def _resolve_config_path(raw_config: str | Path) -> Path:
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
        f"Config TOML not found: '{raw_config}'. "
        f"Tried '{cwd_candidate}' and '{script_candidate}'."
    )


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the reference 2D geology-driven case on a Gmsh planar mesh "
            "without any solver coupling."
        )
    )
    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
        help=(
            "Path to case TOML config. "
            f"Default: {DEFAULT_CONFIG_FILE} (cwd first, then script directory)."
        ),
    )
    parser.add_argument("--section", default=DEFAULT_SECTION)
    parser.add_argument("--output-figure", default=None)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--no-show-plot", action="store_true")
    return parser.parse_args(argv)



def _resolve_optional_mapping_path(
    payload: dict[str, Any], *, key: str, base_dir: Path
) -> None:
    raw = payload.get(key)
    if raw is None:
        return
    payload[key] = resolve_path(raw, base_dir=base_dir)


def _resolve_geology_paths(
    payload: Mapping[str, Any], *, base_dir: Path
) -> dict[str, Any]:
    out = dict(payload)
    source = out.get("source")
    if isinstance(source, Mapping):
        source_data = dict(source)
        _resolve_optional_mapping_path(source_data, key="path", base_dir=base_dir)
        _resolve_optional_mapping_path(
            source_data, key="reference_raster_path", base_dir=base_dir
        )
        out["source"] = source_data

    landsea = out.get("landsea")
    if isinstance(landsea, Mapping):
        out["landsea"] = dict(landsea)
    return out


def _resolve_field_param_paths(
    payload: Mapping[str, Any], *, base_dir: Path
) -> dict[str, Any]:
    out = dict(payload)
    heterogeneous = out.get("field_heterogeneous")
    if not isinstance(heterogeneous, Mapping):
        return out
    heterogeneous_data = dict(heterogeneous)
    source = str(heterogeneous_data.get("values_source", "inline")).strip().lower()
    if source == "csv" and heterogeneous_data.get("values_csv_file") is not None:
        heterogeneous_data["values_csv_file"] = resolve_path(
            heterogeneous_data["values_csv_file"],
            base_dir=base_dir,
        )
    out["field_heterogeneous"] = heterogeneous_data
    return out


def _resolve_mesh_paths(
    payload: Mapping[str, Any], *, base_dir: Path
) -> dict[str, Any]:
    out = dict(payload)
    _resolve_optional_mapping_path(out, key="path", base_dir=base_dir)
    return out


def _resolve_optional_output_path(
    config_toml: Path,
    config_value: Any,
    override_value: str | None,
) -> Path | None:
    raw = override_value if override_value is not None else config_value
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (config_toml.parent / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_case_config(config_toml: Path, *, section: str = "case") -> dict[str, Any]:
    payload = tomllib.loads(config_toml.read_text(encoding="utf-8-sig"))
    section_cfg = dict(get_nested_section(payload, section))

    mesh_cfg = _resolve_mesh_paths(
        dict(section_cfg.get("mesh", {})), base_dir=config_toml.parent
    )
    geology_cfg = _resolve_geology_paths(
        dict(section_cfg.get("geology", {})), base_dir=config_toml.parent
    )
    field_param_cfg = _resolve_field_param_paths(
        dict(section_cfg.get("field_param", {})),
        base_dir=config_toml.parent,
    )
    field_param_resolved = resolve_field_param_config_payload(
        field_param_cfg,
        base_dir=config_toml.parent,
        section_label="field_param",
    )

    return {
        "mesh": mesh_cfg,
        "geology": validate_geology_config_data(geology_cfg),
        "field_param": validate_resolved_field_param_data(field_param_resolved),
        "cell_samples_per_axis": (
            None
            if section_cfg.get("cell_samples_per_axis") is None
            else max(2, int(section_cfg["cell_samples_per_axis"]))
        ),
        "depth": float(section_cfg.get("depth", 0.0)),
        "strict_field_spatial_id_match": bool(
            section_cfg.get("strict_field_spatial_id_match", True)
        ),
        "output_figure": section_cfg.get("output_figure"),
        "output_summary_json": section_cfg.get("output_summary_json"),
    }


def _disable_axis_offset(ax) -> None:
    ax.ticklabel_format(style="plain", axis="both", useOffset=False)
    ax.xaxis.get_major_formatter().set_useOffset(False)
    ax.yaxis.get_major_formatter().set_useOffset(False)
    ax.xaxis.get_offset_text().set_visible(False)
    ax.yaxis.get_offset_text().set_visible(False)


def _maybe_scientific_colorbar(cbar, values) -> None:
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


def _build_zone_name_by_key(
    gdf, *, code_field: str, name_field: str | None
) -> dict[str, str]:
    keys = gdf[code_field].map(_normalize_zone_key)
    unique_keys = sorted(np.unique(keys.to_numpy()).tolist())
    if name_field is None:
        return {key: key for key in unique_keys}

    out: dict[str, str] = {}
    for key in unique_keys:
        names = gdf.loc[keys == key, name_field].astype(str).str.strip()
        names = names[
            (names != "") & (names.str.lower() != "nan") & (names.str.lower() != "none")
        ]
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


def _add_zone_cartouches(
    ax, entries: list[tuple[tuple[float, float, float, float], str]]
) -> int:
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


def _draw_mesh_edges(
    ax, mesh: GmshPlanarMesh2D, *, color: str = "0.25", lw: float = 0.35
) -> None:
    for cell in mesh.cells:
        vertices = np.asarray(cell.vertices, dtype=float)
        closed = np.vstack((vertices, vertices[0]))
        ax.plot(closed[:, 0], closed[:, 1], color=color, lw=lw, alpha=0.70)


def _plot_left_raw_geology(
    ax,
    *,
    geology_cfg: Mapping[str, Any],
    geology_field: GeologyField,
    mesh,
    return_zone_colors: bool = False,
) -> (
    list[tuple[tuple[float, float, float, float], str]]
    | tuple[
        list[tuple[tuple[float, float, float, float], str]],
        dict[str, tuple[float, float, float, float]],
    ]
):
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
                    cartouches.append(
                        (rgba, f"{zone_name_by_key.get(key, key)} [{key}]")
                    )
                plotted = True

    if not plotted:
        geology_codes = np.asarray(geology_field.encoded_codes, dtype=float)
        geology_masked = np.ma.masked_where(geology_codes <= 0, geology_codes)
        unique_codes = np.unique(
            np.asarray(geology_codes[geology_codes > 0], dtype=int)
        )
        n_classes = max(1, int(unique_codes.size))
        cmap_geo = plt.get_cmap("tab20", min(20, n_classes))
        img = ax.imshow(
            geology_masked,
            origin="lower",
            extent=[xmin, xmax, ymin, ymax],
            cmap=cmap_geo,
            interpolation="nearest",
            aspect="equal",
        )
        _ = img
        denom = max(float(len(unique_codes) - 1), 1.0)
        for idx, code in enumerate(unique_codes):
            zone_color_by_key[_normalize_zone_key(code)] = cmap_geo(float(idx) / denom)

    _draw_mesh_edges(ax, mesh, color="0.15", lw=0.30)
    ax.set_title("Raw geology + Gmsh mesh", fontsize=9)
    ax.set_xlabel("x [m]", fontsize=7)
    ax.set_ylabel("y [m]", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.set_aspect("equal")
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    _disable_axis_offset(ax)
    if return_zone_colors:
        return cartouches, zone_color_by_key
    return cartouches


def _dominant_zone_indices(
    field_discretization,
) -> tuple[np.ndarray, tuple[str, ...], int, int]:
    zone_keys_raw, fractions_by_zone = field_discretization.weighted_components()
    zone_keys = tuple(_normalize_zone_key(key) for key in zone_keys_raw)
    stack = np.vstack(
        [
            np.asarray(
                field_discretization.mesh.to_cell_values(fractions_by_zone[key]),
                dtype=float,
            ).reshape(-1)
            for key in zone_keys_raw
        ]
    )
    max_fraction = np.nanmax(stack, axis=0)
    dominant_idx = np.argmax(stack, axis=0).astype(float)
    valid = np.isfinite(max_fraction) & (max_fraction > 0.0)
    dominant_idx[~valid] = np.nan
    mixed = int(np.count_nonzero(valid & (max_fraction < 0.999999)))
    undefined = int(np.count_nonzero(~valid))
    return dominant_idx, zone_keys, mixed, undefined


def _plot_center_mesh_geology(
    ax,
    *,
    field_discretization,
    zone_color_by_key: Mapping[str, tuple[float, float, float, float]] | None = None,
    fig,
) -> tuple[tuple[str, ...], int, int]:
    dominant_idx, zone_keys, mixed_count, undefined_count = _dominant_zone_indices(
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
    _disable_axis_offset(ax)
    return zone_keys, mixed_count, undefined_count


def _plot_right_field_values(ax, *, mesh, mesh_values, fig) -> None:
    values = np.asarray(
        mesh.to_cell_values(mesh_values.cell_values), dtype=float
    ).reshape(-1)
    mappable = mesh.plot_cell_values(ax, values, cmap="viridis", show_mesh=True)
    cbar = fig.colorbar(mappable, ax=ax, shrink=0.72, pad=0.02)
    cbar.set_label("field parameter value", fontsize=7)
    cbar.ax.tick_params(labelsize=6)
    _maybe_scientific_colorbar(cbar, values)

    ax.set_title("Final FieldParam values on Gmsh mesh", fontsize=9)
    ax.set_xlabel("x [m]", fontsize=7)
    ax.set_ylabel("y [m]", fontsize=7)
    ax.tick_params(labelsize=6)
    _disable_axis_offset(ax)


def _show_figures_blocking(*figures) -> None:
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _build_summary(
    *,
    mesh: GmshPlanarMesh2D,
    geology_field: GeologyField,
    field_param: FieldParam,
    field_discretization,
    mesh_values,
) -> dict[str, Any]:
    dominant_idx, zone_keys, mixed_count, undefined_count = _dominant_zone_indices(
        field_discretization
    )
    valid_mask = np.isfinite(dominant_idx)
    dominant_counts: dict[str, int] = {}
    for idx, zone_key in enumerate(zone_keys):
        dominant_counts[zone_key] = int(
            np.count_nonzero(dominant_idx[valid_mask] == float(idx))
        )

    values = np.asarray(
        mesh.to_cell_values(mesh_values.cell_values), dtype=float
    ).reshape(-1)
    return {
        "mesh_kind": str(mesh.kind),
        "cell_type": str(mesh.cell_type),
        "n_nodes": int(mesh.n_nodes),
        "n_cells": int(mesh.n_cells),
        "bounds": [float(v) for v in mesh.bounds],
        "field_id": str(geology_field.identifier),
        "field_param_id": str(field_param.identifier),
        "field_param_kind": str(field_param.kind),
        "n_zone_keys": int(len(zone_keys)),
        "zone_keys": [str(v) for v in zone_keys],
        "mixed_cell_count": int(mixed_count),
        "undefined_cell_count": int(undefined_count),
        "dominant_zone_counts": dominant_counts,
        "value_min": round(float(np.nanmin(values)), 12),
        "value_max": round(float(np.nanmax(values)), 12),
        "value_mean": round(float(np.nanmean(values)), 12),
        "value_sum": round(float(np.nansum(values)), 12),
        "value_signature_head": [round(float(v), 12) for v in values[:8]],
    }


def build_reference_mesh_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> GmshPlanarMesh2D:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)
    mesh_cfg = dict(cfg["mesh"])
    return GmshPlanarMesh2D.from_file(
        mesh_cfg["path"],
        cell_type=mesh_cfg.get("cell_type"),
    )


def _build_reference_case_figure(
    *,
    cfg: Mapping[str, Any],
    geology_field: GeologyField,
    mesh: GmshPlanarMesh2D,
    field_discretization,
    mesh_values,
):
    fig, axes = plt.subplots(1, 3, figsize=(24.0, 9.4), dpi=150)
    cartouches, zone_color_by_key = _plot_left_raw_geology(
        axes[0],
        geology_cfg=cfg["geology"],
        geology_field=geology_field,
        mesh=mesh,
        return_zone_colors=True,
    )
    _plot_center_mesh_geology(
        axes[1],
        field_discretization=field_discretization,
        zone_color_by_key=zone_color_by_key,
        fig=fig,
    )
    _plot_right_field_values(axes[2], mesh=mesh, mesh_values=mesh_values, fig=fig)
    n_cartouche_rows = _add_zone_cartouches(axes[0], cartouches)
    fig.suptitle(
        "Visual QA: raw geology -> mesh discretization -> FieldParam values on Gmsh mesh",
        fontsize=10,
    )
    bottom_margin = 0.12 + min(0.14, 0.035 * max(0, n_cartouche_rows))
    fig.tight_layout(rect=[0, bottom_margin, 1, 0.95])
    return fig


def build_reference_case_state_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    config_path = _resolve_config_path(config_toml)
    cfg = _resolve_case_config(config_path, section=section)

    geology_field = GeologyField.from_dict(cfg["geology"])
    field_param = FieldParam.from_dict(cfg["field_param"])
    if bool(cfg["strict_field_spatial_id_match"]) and field_param.is_heterogeneous:
        required_field_id = str(getattr(field_param, "field_spatial_id", "")).strip()
        support_field_id = str(getattr(geology_field, "identifier", "")).strip()
        if (
            required_field_id
            and support_field_id
            and required_field_id != support_field_id
        ):
            raise ValueError(
                "field_param.field_spatial_id does not match geology identifier: "
                f"{required_field_id!r} != {support_field_id!r}"
            )

    mesh = build_reference_mesh_from_toml(config_path, section=section)
    n_sub = int(
        cfg["cell_samples_per_axis"]
        or getattr(geology_field, "default_cell_samples_per_axis", 8)
    )
    field_discretization = geology_field.on_mesh(mesh, cell_samples_per_axis=n_sub)
    mesh_values = field_param.to_mesh_field(
        field_discretization, depth=float(cfg["depth"])
    )
    summary = _build_summary(
        mesh=mesh,
        geology_field=geology_field,
        field_param=field_param,
        field_discretization=field_discretization,
        mesh_values=mesh_values,
    )
    return {
        "config_path": config_path,
        "config": cfg,
        "geology_field": geology_field,
        "field_param": field_param,
        "mesh": mesh,
        "field_discretization": field_discretization,
        "mesh_values": mesh_values,
        "summary": summary,
    }


def run_reference_case_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    output_figure: str | Path | None = None,
    output_summary_json: str | Path | None = None,
    show_plot: bool = False,
) -> dict[str, Any]:
    state = build_reference_case_state_from_toml(config_toml, section=section)
    config_path = Path(state["config_path"])
    cfg = dict(state["config"])
    geology_field = state["geology_field"]
    mesh = state["mesh"]
    field_discretization = state["field_discretization"]
    mesh_values = state["mesh_values"]

    figure_path = _resolve_optional_output_path(
        config_path,
        cfg["output_figure"],
        None if output_figure is None else str(output_figure),
    )
    summary_path = _resolve_optional_output_path(
        config_path,
        cfg["output_summary_json"],
        None if output_summary_json is None else str(output_summary_json),
    )
    summary = dict(state["summary"])

    fig = None
    if figure_path is not None or show_plot:
        if show_plot:
            ensure_interactive_backend_for_show()
        fig = _build_reference_case_figure(
            cfg=cfg,
            geology_field=geology_field,
            mesh=mesh,
            field_discretization=field_discretization,
            mesh_values=mesh_values,
        )
        if figure_path is not None:
            fig.savefig(figure_path)
            summary["output_figure"] = str(figure_path)

    if summary_path is not None:
        _write_json(summary_path, summary)
        summary["output_summary_json"] = str(summary_path)

    if show_plot:
        _show_figures_blocking(fig)
    elif fig is not None:
        plt.close(fig)
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = run_reference_case_from_toml(
        args.config_file,
        section=args.section,
        output_figure=args.output_figure,
        output_summary_json=args.output_summary_json,
        show_plot=(not bool(args.no_show_plot)),
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
