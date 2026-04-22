"""Provide the smallest read-only example for colleagues using exported meshes.

This module shows how to open the stable exchange formats without touching the
full HydroModPy workflow. It is meant for users who only need mesh reading,
basic value inspection, and a compact summary of what is stored on disk.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    load_extruded_mesh,
    load_extruded_mesh_values,
    load_planar_mesh,
)

DEFAULT_PLANAR_MESH = (
    Path(__file__).resolve().parents[1]
    / "cases"
    / "reference_2d_geology_base"
    / "data"
    / "mesh"
    / "reference_triangles.msh"
)
DEFAULT_VALUES_VTU = (
    Path(__file__).resolve().parents[1]
    / "cases"
    / "reference_3d_fieldparam"
    / "outputs"
    / "reference_3d_postprocess.vtu"
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Minimal read-only example for 2D/3D Gmsh mesh exchange."
    )
    parser.add_argument("--planar-mesh", default=str(DEFAULT_PLANAR_MESH))
    parser.add_argument("--values-vtu", default=str(DEFAULT_VALUES_VTU))
    return parser.parse_args(argv)


def build_read_only_summary(
    *,
    planar_mesh_path: str | Path = DEFAULT_PLANAR_MESH,
    values_vtu_path: str | Path = DEFAULT_VALUES_VTU,
) -> dict[str, object]:
    planar_mesh = load_planar_mesh(planar_mesh_path)
    extruded_mesh = load_extruded_mesh(values_vtu_path)
    mesh_with_values = load_extruded_mesh_values(values_vtu_path, label="field_param_value")
    center_source = int(mesh_with_values.n_cells_2d // 2)
    center_profile = mesh_with_values.extract_vertical_profile(center_source)
    return {
        "planar_mesh_path": str(Path(planar_mesh_path).resolve()),
        "values_vtu_path": str(Path(values_vtu_path).resolve()),
        "planar_mesh_kind": str(planar_mesh.kind),
        "planar_cell_type": str(planar_mesh.cell_type),
        "planar_n_cells": int(planar_mesh.n_cells),
        "planar_bounds": [round(float(v), 6) for v in planar_mesh.bounds],
        "extruded_mesh_kind": str(extruded_mesh.kind),
        "extruded_cell_type": str(extruded_mesh.cell_type_3d),
        "extruded_n_layers": int(extruded_mesh.n_layers),
        "extruded_n_cells_3d": int(extruded_mesh.n_prisms),
        "values_shape_3d": [int(v) for v in np.asarray(mesh_with_values.values_3d).shape],
        "values_mean": round(
            float(np.mean(np.asarray(mesh_with_values.values_3d, dtype=float))), 12
        ),
        "layer_mean_sequence": [
            round(float(layer_stats["mean"]), 12) for layer_stats in mesh_with_values.layer_stats()
        ],
        "center_profile": [round(float(v), 12) for v in center_profile["values"]],
        "center_depth_profile": [round(float(v), 12) for v in center_profile.get("depths", [])],
    }


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary = build_read_only_summary(
        planar_mesh_path=args.planar_mesh,
        values_vtu_path=args.values_vtu,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
