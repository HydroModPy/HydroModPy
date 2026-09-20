"""A regional lab materializes one flow job for ten site configurations."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin

from hydromodpy.analysis.testbed.contracts import register_testbed_runner_provider
from hydromodpy.analysis.testbed.regional_lab import RegionalLabProfileLauncher
from hydromodpy.analysis.testbed.regional_lab_types import (
    RegionalLabPlannedCase,
    RegionalLabSiteRecord,
)
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import _delineate
from hydromodpy.spatial.geographic.core.pipeline_steps import prepare_geographic_run
from hydromodpy.spatial.geographic.pipeline import build_geographic_runtime_context
from hydromodpy.spatial.geographic.regional_flow_job import load_regional_flow_job
from hydromodpy.spatial.terrain.numpy_engine import NumpyTerrainEngine
from hydromodpy.workflow.regional_lab_materialization import materialize_regional_lab_flow
from tests._helpers.whitebox_double import FakeWhiteboxBackend


def _write_dem(path: Path) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=8,
        width=8,
        count=1,
        dtype="float64",
        crs="EPSG:2154",
        transform=from_origin(300000, 6700000, 25, 25),
        nodata=-9999.0,
    ) as raster:
        raster.write(np.arange(64, dtype=float).reshape(8, 8), 1)


def _write_child(path: Path, *, dem: Path, root: Path, x: float, y: float, crs: str | None) -> None:
    path.write_text(
        f"""[workflow]
mode = "simulation"

[simulation]
name = "{path.stem}"

[workspace]
project_root = "{root}"

[geographic]
{f'crs_project = "{crs}"' if crs else ""}
dem_correc_type = "fill"
terrain_engine = "numpy_d8"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "{dem}"
x_outlet = {x}
y_outlet = {y}
snap_dist = "50 m"
buff_area = "20%"

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = []

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"
""",
        encoding="utf-8",
    )


def _site(index: int) -> RegionalLabSiteRecord:
    return RegionalLabSiteRecord(
        site_id=f"site_{index}",
        site_label=None,
        cluster_id=None,
        cluster_label=None,
        cluster_family=None,
        cluster_scale=None,
        region_id=None,
        source_selection_id=None,
        site_status=None,
        maturity=None,
        x=None,
        y=None,
        area_km2=None,
        site_tags=(),
        cluster_tags=(),
        enabled=True,
        resolved_paths={},
        raw={},
    )


def test_ten_site_configs_share_one_sealed_flow_job(tmp_path: Path, monkeypatch) -> None:
    dem = tmp_path / "dem.tif"
    _write_dem(dem)
    calls: Counter[str] = Counter()
    for name in ("condition_dem", "drainage_directions", "flow_accumulation"):
        original = getattr(NumpyTerrainEngine, name)

        def counted(self, *args, _name=name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(NumpyTerrainEngine, name, counted)

    cases = []
    for index in range(10):
        config_path = tmp_path / f"site_{index}.toml"
        _write_child(
            config_path,
            dem=dem,
            root=tmp_path / f"workspace_{index}",
            x=300012.5 + 25.0 * (index % 8),
            y=6699887.5,
            crs=None if index == 0 else "EPSG:2154",
        )
        cases.append(
            RegionalLabPlannedCase(
                case_id=f"site_{index}",
                site=_site(index),
                recipe_id="simulation",
                recipe_label="simulation",
                launcher="simulation",
                config_path=config_path,
            )
        )

    first = materialize_regional_lab_flow(cases, output_root=tmp_path / "lab")
    assert first.report["job_count"] == 1
    assert first.report["executed_job_count"] == 1
    assert calls == {"condition_dem": 1, "drainage_directions": 1, "flow_accumulation": 1}
    paths = {
        HydroModPyConfig.from_toml(case.config_path).geographic.reg_fold for case in first.cases
    }
    assert len(paths) == 1
    assert load_regional_flow_job(job_dir=next(iter(paths))).outcome.reused
    geographic = HydroModPyConfig.from_toml(first.cases[0].config_path).geographic
    setup = prepare_geographic_run(config=geographic, out_dir_path=tmp_path / "domain")
    flow, correction, _ = _delineate(config=geographic, setup=setup, routing_dem_path=str(dem))
    assert correction == "fill"
    assert Path(flow.acc).is_file()
    assert Path(setup.paths.watershed_shp).is_file()
    assert calls == {"condition_dem": 1, "drainage_directions": 1, "flow_accumulation": 1}

    second = materialize_regional_lab_flow(cases, output_root=tmp_path / "lab")
    assert second.report["executed_job_count"] == 0
    assert second.report["reused_job_count"] == 1
    assert calls == {"condition_dem": 1, "drainage_directions": 1, "flow_accumulation": 1}


def test_regional_lab_dispatches_ten_distinct_catchments_from_one_job(
    tmp_path: Path, monkeypatch
) -> None:
    dem = tmp_path / "dem.tif"
    _write_dem(dem)
    calls: Counter[str] = Counter()
    for name in ("condition_dem", "drainage_directions", "flow_accumulation"):
        original = getattr(NumpyTerrainEngine, name)

        def counted(self, *args, _name=name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(NumpyTerrainEngine, name, counted)
    catalog = tmp_path / "sites.csv"
    catalog.write_text(
        "site_id,simulation_config\n"
        + "".join(f"site_{index},site_{index}.toml\n" for index in range(10)),
        encoding="utf-8",
    )
    for index in range(10):
        _write_child(
            tmp_path / f"site_{index}.toml",
            dem=dem,
            root=tmp_path / f"workspace_{index}",
            x=300000.0 + (1 + index % 5 + 0.5) * 25.0,
            y=6700000.0 - (1 + index // 5 + 0.5) * 25.0,
            crs="EPSG:2154",
        )
    lab_config = tmp_path / "regional_lab.toml"
    lab_config.write_text(
        """[regional_lab]
lab_id = "ten_sites"
output_root = "lab"
execute = true
share_regional_flow = true

[regional_lab.catalog]
path = "sites.csv"
path_fields = ["simulation_config"]

[[regional_lab.recipe]]
id = "simulation"
launcher = "simulation"
required_fields = ["simulation_config"]
config_path_template = "{simulation_config}"
""",
        encoding="utf-8",
    )

    watersheds: list[Path] = []

    class _Locator:
        def __init__(self, **kwargs):
            pass

        def reverse(self, *args, **kwargs):
            return None

    class _GeographicProvider:
        def materialize_regional_flow(self, cases, *, output_root):
            result = materialize_regional_lab_flow(cases, output_root=output_root)
            return result.cases, result.report

        def run_simulation(self, config_path: Path, *, no_display: bool):
            config = HydroModPyConfig.from_toml(config_path)
            geographic = config.geographic
            result = build_geographic_runtime_context(
                config=geographic,
                out_dir_path=tmp_path / "geography" / config.simulation.name,
                backend=FakeWhiteboxBackend(),
                locator_factory=_Locator,
            )
            watersheds.append(Path(result.paths.watershed_shp))
            return {"name": config.simulation.name}

    register_testbed_runner_provider(_GeographicProvider())
    summary = RegionalLabProfileLauncher(lab_config).run()
    assert summary["planned_case_count"] == 10
    assert summary["failed_case_count"] == 0
    assert summary["regional_flow"]["executed_job_count"] == 1
    assert len(watersheds) == 10
    assert len({gpd.read_file(path).geometry.iloc[0].wkb for path in watersheds}) == 10
    assert calls == {"condition_dem": 1, "drainage_directions": 1, "flow_accumulation": 1}

    repeated = RegionalLabProfileLauncher(lab_config).run()
    assert repeated["regional_flow"]["executed_job_count"] == 0
    assert repeated["reused_case_count"] == 10
    assert calls == {"condition_dem": 1, "drainage_directions": 1, "flow_accumulation": 1}

    changed_config = tmp_path / "site_0.toml"
    changed_config.write_text(
        changed_config.read_text(encoding="utf-8").replace(
            "x_outlet = 300037.5", "x_outlet = 300062.5"
        ),
        encoding="utf-8",
    )
    changed_outlet = RegionalLabProfileLauncher(lab_config).run()
    assert changed_outlet["regional_flow"]["executed_job_count"] == 0
    assert changed_outlet["executed_case_count"] == 1
    assert changed_outlet["reused_case_count"] == 9
    assert calls == {"condition_dem": 1, "drainage_directions": 1, "flow_accumulation": 1}

    with rasterio.open(dem, "r+") as raster:
        data = raster.read(1)
        data[7, 7] += 0.25
        raster.write(data, 1)
    changed_dem = RegionalLabProfileLauncher(lab_config).run()
    assert changed_dem["regional_flow"]["executed_job_count"] == 1
    assert changed_dem["executed_case_count"] == 10
    assert changed_dem["reused_case_count"] == 0
    assert calls == {"condition_dem": 2, "drainage_directions": 2, "flow_accumulation": 2}
