"""I/O and configuration helpers for the annex mesh-bundle viewer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
    load_catchment_mesh_bundle,
)

DEFAULT_CONFIG_FILE = "mesh_bundle_viewer_example.toml"
DEFAULT_SECTION = "mesh_bundle_viewer"

NUMERIC_COLOR_FIELDS = {
    "area_m2",
    "z_top_centroid",
    "z_top_mean",
}
CATEGORICAL_COLOR_FIELDS = {
    "geology_code",
    "geology_key",
}
ALLOWED_COLOR_FIELDS = NUMERIC_COLOR_FIELDS | CATEGORICAL_COLOR_FIELDS
ALLOWED_TOPOGRAPHY_FIELDS = {
    "z_top_centroid",
    "z_top_mean",
}


@dataclass(frozen=True)
class MeshBundlePlotConfig:
    color_by: str = "geology_key"
    cmap: str = "viridis"
    figsize: tuple[float, float] = (11.0, 9.0)
    dpi: int = 160
    title: str | None = None
    show_topography_panel: bool = True
    topography_color_by: str = "z_top_mean"
    topography_cmap: str = "terrain"
    topography_title: str | None = None
    show_mesh_edges: bool = True
    mesh_edge_color: str = "0.35"
    mesh_edge_linewidth: float = 0.55
    show_boundary_edges: bool = True
    show_geology_interfaces: bool = True
    show_river_edges: bool = True
    annotate_cell_ids: bool = False


@dataclass(frozen=True)
class MeshBundleViewerConfig:
    bundle_dir: Path
    output_figure: Path | None = None
    output_summary_json: Path | None = None
    show_plot: bool = False
    plot: MeshBundlePlotConfig = MeshBundlePlotConfig()


@dataclass(frozen=True)
class LoadedMeshBundleViewerData:
    bundle: CatchmentMeshBundle
    config: MeshBundleViewerConfig


def _require_mapping(raw_value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(raw_value, Mapping):
        raise ValueError(f"{label} must be one TOML table/mapping.")
    return raw_value


def _coerce_optional_text(raw_value: object | None) -> str | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _coerce_bool(raw_value: object, *, label: str) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    raise ValueError(f"{label} must be a boolean.")


def _coerce_positive_int(raw_value: object, *, label: str) -> int:
    try:
        value = int(raw_value)
    except Exception as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{label} must be > 0.")
    return value


def _coerce_non_negative_float(raw_value: object, *, label: str) -> float:
    try:
        value = float(raw_value)
    except Exception as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if value < 0.0:
        raise ValueError(f"{label} must be >= 0.")
    return value


def _coerce_figsize(raw_value: object, *, label: str) -> tuple[float, float]:
    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
        raise ValueError(f"{label} must be a 2-item array like [11.0, 9.0].")
    try:
        width = float(raw_value[0])
        height = float(raw_value[1])
    except Exception as exc:
        raise ValueError(f"{label} must contain numeric values.") from exc
    if width <= 0.0 or height <= 0.0:
        raise ValueError(f"{label} values must be > 0.")
    return (width, height)


def _resolve_path(
    *,
    config_path: Path,
    raw_value: object | None,
    required: bool,
    label: str,
) -> Path | None:
    text = _coerce_optional_text(raw_value)
    if text is None:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    return path


def load_mesh_bundle_viewer_config_from_toml(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
) -> MeshBundleViewerConfig:
    """Load one bundle-viewer configuration from TOML."""
    config_path = Path(config_toml).resolve()
    payload = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    section_payload = _require_mapping(payload.get(section), label=f"[{section}]")

    plot_payload = section_payload.get("plot", {})
    if plot_payload is None:
        plot_payload = {}
    plot_payload = _require_mapping(plot_payload, label=f"[{section}.plot]")

    color_by = str(plot_payload.get("color_by", "geology_key")).strip().lower()
    if color_by not in ALLOWED_COLOR_FIELDS:
        allowed = ", ".join(sorted(ALLOWED_COLOR_FIELDS))
        raise ValueError(f"[{section}.plot].color_by must be one of: {allowed}.")

    topography_color_by = (
        str(plot_payload.get("topography_color_by", "z_top_mean")).strip().lower()
    )
    if topography_color_by not in ALLOWED_TOPOGRAPHY_FIELDS:
        allowed = ", ".join(sorted(ALLOWED_TOPOGRAPHY_FIELDS))
        raise ValueError(
            f"[{section}.plot].topography_color_by must be one of: {allowed}."
        )

    plot_cfg = MeshBundlePlotConfig(
        color_by=color_by,
        cmap=str(plot_payload.get("cmap", "viridis")).strip() or "viridis",
        figsize=_coerce_figsize(
            plot_payload.get("figsize", [11.0, 9.0]),
            label=f"[{section}.plot].figsize",
        ),
        dpi=_coerce_positive_int(
            plot_payload.get("dpi", 160),
            label=f"[{section}.plot].dpi",
        ),
        title=_coerce_optional_text(plot_payload.get("title")),
        show_topography_panel=_coerce_bool(
            plot_payload.get("show_topography_panel", True),
            label=f"[{section}.plot].show_topography_panel",
        ),
        topography_color_by=topography_color_by,
        topography_cmap=(
            str(plot_payload.get("topography_cmap", "terrain")).strip() or "terrain"
        ),
        topography_title=_coerce_optional_text(plot_payload.get("topography_title")),
        show_mesh_edges=_coerce_bool(
            plot_payload.get("show_mesh_edges", True),
            label=f"[{section}.plot].show_mesh_edges",
        ),
        mesh_edge_color=(
            str(plot_payload.get("mesh_edge_color", "0.35")).strip() or "0.35"
        ),
        mesh_edge_linewidth=_coerce_non_negative_float(
            plot_payload.get("mesh_edge_linewidth", 0.55),
            label=f"[{section}.plot].mesh_edge_linewidth",
        ),
        show_boundary_edges=_coerce_bool(
            plot_payload.get("show_boundary_edges", True),
            label=f"[{section}.plot].show_boundary_edges",
        ),
        show_geology_interfaces=_coerce_bool(
            plot_payload.get("show_geology_interfaces", True),
            label=f"[{section}.plot].show_geology_interfaces",
        ),
        show_river_edges=_coerce_bool(
            plot_payload.get("show_river_edges", True),
            label=f"[{section}.plot].show_river_edges",
        ),
        annotate_cell_ids=_coerce_bool(
            plot_payload.get("annotate_cell_ids", False),
            label=f"[{section}.plot].annotate_cell_ids",
        ),
    )

    return MeshBundleViewerConfig(
        bundle_dir=_resolve_path(
            config_path=config_path,
            raw_value=section_payload.get("bundle_dir"),
            required=True,
            label=f"[{section}].bundle_dir",
        ),
        output_figure=_resolve_path(
            config_path=config_path,
            raw_value=section_payload.get("output_figure"),
            required=False,
            label=f"[{section}].output_figure",
        ),
        output_summary_json=_resolve_path(
            config_path=config_path,
            raw_value=section_payload.get("output_summary_json"),
            required=False,
            label=f"[{section}].output_summary_json",
        ),
        show_plot=_coerce_bool(
            section_payload.get("show_plot", False),
            label=f"[{section}].show_plot",
        ),
        plot=plot_cfg,
    )


def load_mesh_bundle_viewer_data(
    config: MeshBundleViewerConfig,
) -> LoadedMeshBundleViewerData:
    """Load one bundle and package it with its viewer configuration."""
    bundle = load_catchment_mesh_bundle(config.bundle_dir)
    return LoadedMeshBundleViewerData(bundle=bundle, config=config)


def load_mesh_bundle_viewer_data_from_toml(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
) -> LoadedMeshBundleViewerData:
    """Load one bundle-viewer dataset directly from TOML."""
    config = load_mesh_bundle_viewer_config_from_toml(config_toml, section=section)
    return load_mesh_bundle_viewer_data(config)


__all__ = [
    "ALLOWED_COLOR_FIELDS",
    "ALLOWED_TOPOGRAPHY_FIELDS",
    "CATEGORICAL_COLOR_FIELDS",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "LoadedMeshBundleViewerData",
    "MeshBundlePlotConfig",
    "MeshBundleViewerConfig",
    "NUMERIC_COLOR_FIELDS",
    "load_mesh_bundle_viewer_config_from_toml",
    "load_mesh_bundle_viewer_data",
    "load_mesh_bundle_viewer_data_from_toml",
]
