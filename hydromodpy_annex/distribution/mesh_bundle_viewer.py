"""Facade module for the annex mesh-bundle viewer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
)

from hydromodpy_annex.distribution.mesh_bundle_viewer_io import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_SECTION,
    LoadedMeshBundleViewerData,
    MeshBundlePlotConfig,
    MeshBundleViewerConfig,
    load_mesh_bundle_viewer_config_from_toml,
    load_mesh_bundle_viewer_data,
    load_mesh_bundle_viewer_data_from_toml,
)
from hydromodpy_annex.distribution.mesh_bundle_visualization import (
    build_mesh_bundle_figure,
    has_continuous_node_topography,
)


def build_mesh_bundle_viewer_summary(
    bundle: CatchmentMeshBundle,
    *,
    config: MeshBundleViewerConfig,
) -> dict[str, Any]:
    """Return one compact summary of the loaded bundle and viewer choices."""
    geometry_keys = sorted(
        {
            str(cell.geology_key)
            for cell in bundle.cells
            if str(cell.geology_key).strip() != ""
        }
    )
    metadata = dict(bundle.metadata)
    return {
        "summary_schema_version": "mesh_bundle_viewer_v1",
        "bundle_dir": str(bundle.bundle_dir),
        "mesh_path": str(bundle.mesh_path),
        "n_nodes": int(bundle.n_nodes),
        "n_cells": int(bundle.n_cells),
        "n_edges": int(bundle.n_edges),
        "crs": metadata.get("crs"),
        "constraints_mode": metadata.get("constraints_mode"),
        "geology_available": bool(metadata.get("geology", {}).get("available", False)),
        "geology_keys": geometry_keys,
        "river_edge_count": int(sum(1 for edge in bundle.edges if bool(edge.is_river))),
        "boundary_edge_count": int(
            sum(1 for edge in bundle.edges if str(edge.edge_kind) == "boundary")
        ),
        "geology_interface_edge_count": int(
            sum(
                1
                for edge in bundle.edges
                if str(edge.edge_kind) == "geology_interface"
            )
        ),
        "color_by": str(config.plot.color_by),
        "show_topography_panel": bool(config.plot.show_topography_panel),
        "topography_color_by": str(config.plot.topography_color_by),
        "topography_render_mode": (
            "node_continuous"
            if has_continuous_node_topography(bundle)
            else "cell_fallback"
        ),
        "output_figure": (
            None if config.output_figure is None else str(config.output_figure)
        ),
        "output_summary_json": (
            None
            if config.output_summary_json is None
            else str(config.output_summary_json)
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def run_mesh_bundle_viewer(
    config: MeshBundleViewerConfig,
) -> dict[str, Any]:
    """Load, plot, and summarize one exported catchment mesh bundle."""
    loaded = load_mesh_bundle_viewer_data(config)
    summary = build_mesh_bundle_viewer_summary(loaded.bundle, config=loaded.config)
    fig = build_mesh_bundle_figure(loaded.bundle, config=loaded.config)

    if loaded.config.output_figure is not None:
        loaded.config.output_figure.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(loaded.config.output_figure)

    if loaded.config.output_summary_json is not None:
        _write_json(loaded.config.output_summary_json, summary)

    from matplotlib import pyplot as plt

    if loaded.config.show_plot:
        plt.show()
    else:
        plt.close(fig)
    return summary


def run_mesh_bundle_viewer_from_toml(
    config_toml: str | Path,
    *,
    section: str = DEFAULT_SECTION,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run the mesh-bundle viewer directly from one TOML file."""
    config = load_mesh_bundle_viewer_config_from_toml(config_toml, section=section)
    if output_json is not None:
        config = replace(config, output_summary_json=Path(output_json).resolve())
    return run_mesh_bundle_viewer(config)


__all__ = [
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_SECTION",
    "LoadedMeshBundleViewerData",
    "MeshBundlePlotConfig",
    "MeshBundleViewerConfig",
    "build_mesh_bundle_figure",
    "build_mesh_bundle_viewer_summary",
    "has_continuous_node_topography",
    "load_mesh_bundle_viewer_config_from_toml",
    "load_mesh_bundle_viewer_data",
    "load_mesh_bundle_viewer_data_from_toml",
    "run_mesh_bundle_viewer",
    "run_mesh_bundle_viewer_from_toml",
]
