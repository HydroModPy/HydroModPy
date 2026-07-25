"""Shared builders and fakes for mesh-catchment launcher tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.state.paths import scratch_dir_for
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path(config.project_root)
        self.solver_scratch_folder = scratch_dir_for(self.project_root)


class _DummyBatchWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path(config.project_root)
        self.catch_name = str(config.catch_name)
        self.solver_scratch_folder = scratch_dir_for(self.project_root)


class _DummyDomainGeographic:
    pass


class _DummyGeographicFeatures:
    def __init__(self, river_mesh_trace=object()) -> None:
        self.rivers = SimpleNamespace(river_mesh_trace=river_mesh_trace)

    def to_domain_geographic_context(self) -> _DummyDomainGeographic:
        return _DummyDomainGeographic()


def _patch_dummy_geographic_builders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    builder=None,
    river_mesh_trace=object(),
) -> None:
    build_fn = (
        builder
        if builder is not None
        else (lambda **_: _DummyGeographicFeatures(river_mesh_trace=river_mesh_trace))
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.build_geographic_derived_features",
        build_fn,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.build_domain_geographic_context",
        lambda **kwargs: build_fn(**kwargs).to_domain_geographic_context(),
    )


def _write_test_raster(path: Path, *, xmin: float, ymin: float, xmax: float, ymax: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixel_size = 100.0
    width = max(1, int(round((xmax - xmin) / pixel_size)))
    height = max(1, int(round((ymax - ymin) / pixel_size)))
    transform = from_origin(float(xmin), float(ymax), pixel_size, pixel_size)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": -9999.0,
    }
    data = np.ones((height, width), dtype=np.float32)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def _minimal_geology_config(
    *,
    reference_raster_path: str = "data/reference.tif",
) -> dict[str, object]:
    return {
        "source": {
            "path": "data/geology.gpkg",
            "kind": "vector",
            "code_field": "CODE",
            "reference_raster_path": reference_raster_path,
        }
    }


def _minimal_cfg(tmp_path: Path):
    return SimpleNamespace(
        workspace=SimpleNamespace(
            project_root=tmp_path / "projects" / "mesh_catchment_case",
        ),
        geographic=SimpleNamespace(
            uses_synthetic_geographic=lambda: False,
            river_network=SimpleNamespace(enabled=True),
        ),
    )


def _batch_cfg(tmp_path: Path):
    dem_path = tmp_path / "regional_dem.tif"
    _write_test_raster(
        dem_path,
        xmin=0.0,
        ymin=0.0,
        xmax=1000.0,
        ymax=1000.0,
    )
    return SimpleNamespace(
        workspace=WorkspaceConfig(
            project_root=tmp_path / "out" / "mesh_batch",
            root=tmp_path,
        ),
        geographic=GeographicConfig(
            catchment={
                "catch_def": "from_outlet_coord",
                "dem_init_path": dem_path,
                "x_outlet": 389285.910,
                "y_outlet": 6816518.749,
                "snap_dist": "50 m",
                "buff_area": "20%",
            },
            crs_project="EPSG:2154",
        ),
    )
