from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _write_minimal_bundle(bundle_dir: Path, *, river_internal_edge: bool = False) -> Path:
    return _write_custom_bundle(
        bundle_dir,
        river_internal_edge=river_internal_edge,
        storage_values=("0.10", "0.15"),
        storage_default=None,
    )


def _write_custom_bundle(
    bundle_dir: Path,
    *,
    river_internal_edge: bool = False,
    storage_values: tuple[str, str] = ("0.10", "0.15"),
    storage_default: float | None = None,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
    hydraulic_properties = {}
    if storage_default is not None:
        hydraulic_properties["storage_coefficient"] = {
            "available": True,
            "unit": "-",
            "values_source": "inline",
            "default_value": float(storage_default),
        }
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "files": {"mesh": "mesh_2d.msh"},
                "hydraulic_properties": hydraulic_properties,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps({"constraints_mode": "geology_only"}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top,z_bottom",
        [
            "0,0.0,0.0,10.0,5.0",
            "1,1.0,0.0,10.0,5.0",
            "2,1.0,1.0,10.0,5.0",
            "3,0.0,1.0,10.0,5.0",
        ],
    )
    _write_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
        [
            f"0,triangle,0,1,2,,0.666667,0.333333,0.5,10.0,10.0,5.0,5.0,1,granite,1.0e-5,{storage_values[0]}",
            f"1,triangle,0,2,3,,0.333333,0.666667,0.5,11.0,11.0,4.0,4.0,2,schist,2.0e-5,{storage_values[1]}",
        ],
    )
    _write_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        [
            "0,0,1,0,,1.0,boundary,false,granite,",
            "1,1,2,0,,1.0,boundary,false,granite,",
            f"2,0,2,0,1,1.414214,internal,{str(bool(river_internal_edge)).lower()},granite,schist",
            "3,2,3,1,,1.0,boundary,false,schist,",
            "4,0,3,1,,1.0,boundary,false,schist,",
        ],
    )
    _write_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [
            "0,granite,1.0",
            "1,schist,1.0",
        ],
    )
    return bundle_dir


def _homogeneous_param(value: object) -> dict[str, object]:
    return {"field": {"kind": "homogeneous", "value": value}}


class _DummyRasterSupport:
    def __init__(
        self,
        *,
        xmin: float,
        xmax: float,
        ymin: float,
        ymax: float,
        dx: float,
        dy: float,
        nrows: int,
        ncols: int,
    ) -> None:
        self.xmin = float(xmin)
        self.xmax = float(xmax)
        self.ymin = float(ymin)
        self.ymax = float(ymax)
        self.dx = float(dx)
        self.dy = float(dy)
        self.nrows = int(nrows)
        self.ncols = int(ncols)
        self.nodata = None


class _DummySurface:
    def __init__(self, values: np.ndarray, support: _DummyRasterSupport) -> None:
        self.values = np.asarray(values, dtype=float)
        self.support = support
