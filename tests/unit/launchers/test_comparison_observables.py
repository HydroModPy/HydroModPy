from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.analysis.comparison.config import RuntimeComparisonConfig
from hydromodpy.analysis.comparison.runtime import (
    _resolve_recorded_output_path,
    extract_observable_rows,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

from ._comparison_builders import (
    OUTLET_CELL_AREA_M2,
    SIM_ID,
    _expected_outlet_flux,
    _FakeCatalog,
    _write_direct_outlet_run_folder,
    _write_fake_run_folder,
    _write_simulation_comparison_config,
    _write_structured_xy_simulation_comparison_config,
)


def test_extract_observable_rows_reads_point_and_strict_outlet(tmp_path: Path) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    store = _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )
    simulation = cfg.comparison.simulation[0]

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        simulation=simulation,
        run_folder=run_folder,
        observables=tuple(cfg.comparison.observable),
        store=store,
        sim_id=SIM_ID,
    )

    assert len(rows) == 2
    head = next(row for row in rows if row["observable"] == "head_at_point")
    outlet = next(row for row in rows if row["observable"] == "outlet_flux")
    assert head["value"] == 21.0
    assert head["selected_cell_index"] == "1"
    assert outlet["value"] == pytest.approx(_expected_outlet_flux(0.8))
    assert outlet["selection"] == "declared_cell"
    assert outlet["selected_cell_index"] == "1"
    assert outlet["time_index"] == 1
    assert outlet["comparison_time_key"] == "time_index:1"
    assert head["time_role"] == "state_snapshot"
    assert outlet["time_role"] == "period_value"
    assert outlet["unit"] == "m3/s"
    assert outlet["native_unit"] == "m3/s"
    assert outlet["derived_from_variable"] == "accumulation_flux"
    assert outlet["conversion_applied"] == "accumulation_flux_m_per_day_to_m3_s"
    assert float(outlet["cell_area_m2"]) == OUTLET_CELL_AREA_M2


def test_extract_observable_rows_reads_seepage_areas_from_seepage_mask(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_seepage_alias"
    bundle_dir = tmp_path / "bundle_seepage_alias"
    store = _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_seepage_alias.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_seepage_alias"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'solver = "modflow6"',
                'mesh_mode = "mesh_input"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "seepage_last"',
                'variable = "seepage_areas"',
                'support = "map"',
                'time = "last"',
                'unit = "-"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_seepage_alias",
        simulation=cfg.comparison.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.comparison.observable),
        store=store,
        sim_id=SIM_ID,
    )

    assert len(rows) == 3
    assert all(row["resolved_variable"] == "seepage_mask" for row in rows)
    assert [float(row["value"]) for row in rows] == pytest.approx([1.0, 1.0, 0.0])


def test_extract_observable_rows_resolves_structured_xy_from_config(
    tmp_path: Path,
) -> None:
    import rasterio
    from rasterio.transform import from_origin

    project_root = tmp_path / "structured_project"
    geographic_dir = project_root / "results_stable" / "geographic"
    geographic_dir.mkdir(parents=True, exist_ok=True)
    raster_path = geographic_dir / "watershed_box_buff_dem.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 2.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.asarray([[1.0, 1.0], [1.0, 1.0]], dtype="float32"), 1)

    simulation_config = tmp_path / "run_structured_nwt.toml"
    simulation_config.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'project_root = "{project_root.as_posix()}"',
                "",
                "[simulation]",
                'run_id = "structured_demo_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow_nwt"]',
                "",
                "[modflownwt.sgrid.planar]",
                'mode = "resample_to_shape"',
                "nx = 2",
                "ny = 2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    run_folder = tmp_path / "structured_run"
    run_folder.mkdir(parents=True, exist_ok=True)
    store = _FakeCatalog(
        run_folder / "simulation.zarr",
        {
            "watertable_elevation": np.asarray(
                [[10.0, 20.0, 30.0, 40.0], [11.0, 21.0, 31.0, 41.0]],
                dtype=float,
            ),
            "accumulation_flux": np.asarray(
                [[0.1, 0.4, 0.2, 0.3], [0.3, 0.8, 0.5, 0.6]],
                dtype=float,
            ),
        },
    )

    comparison_config = tmp_path / "config_structured_xy.toml"
    _write_structured_xy_simulation_comparison_config(
        comparison_config,
        run_folder=run_folder,
        simulation_config_path=simulation_config,
    )
    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(comparison_config),
        config_path=comparison_config,
    )

    rows = extract_observable_rows(
        comparison_id="demo_structured_xy",
        simulation=cfg.comparison.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.comparison.observable),
        config_path=cfg.resolve_simulation_config_path(cfg.comparison.simulation[0]),
        store=store,
        sim_id=SIM_ID,
    )

    head = next(row for row in rows if row["observable"] == "head_xy_point")
    outlet = next(row for row in rows if row["observable"] == "outlet_flux_xy")
    assert head["value"] == 21.0
    assert head["selected_cell_index"] == "1"
    assert outlet["value"] == pytest.approx(0.8 / 86400.0)
    assert outlet["selected_cell_index"] == "1"


def test_extract_observable_rows_reads_direct_scalar_outlet_flux(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_direct"
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    store = _write_direct_outlet_run_folder(run_folder, outlet_value=1.25)
    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        simulation=cfg.comparison.simulation[0],
        run_folder=run_folder,
        observables=(cfg.comparison.observable[1],),
        store=store,
        sim_id=SIM_ID,
    )

    assert len(rows) == 1
    outlet = rows[0]
    assert outlet["value"] == pytest.approx(1.5)
    assert outlet["resolved_variable"] == "outlet_discharge_east_side_m3_s"
    assert outlet["selection"] == "native_outlet_series"
    assert outlet["unit"] == "m3/s"
    assert outlet["conversion_applied"] == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX keeps WSL mount paths unchanged")
def test_resolve_recorded_output_path_keeps_wsl_mount_path_on_posix() -> None:
    path = _resolve_recorded_output_path(
        "/mnt/c/codes/HydroModPy/examples",
        base_dir=Path("/tmp"),
    )

    assert path is not None
    assert path.as_posix() == "/mnt/c/codes/HydroModPy/examples"


def test_extract_observable_rows_masks_depth_using_head_nodata(tmp_path: Path) -> None:
    run_folder = tmp_path / "run_depth_mask"
    run_folder.mkdir(parents=True, exist_ok=True)
    store = _FakeCatalog(
        run_folder / "simulation.zarr",
        {
            "watertable_elevation": np.asarray(
                [[10.0, -9999.0, 12.0], [11.0, -9999.0, 13.0]],
                dtype=float,
            ),
            "watertable_depth": np.asarray(
                [[1.0, 10000.0, 3.0], [2.0, 10001.0, 4.0]],
                dtype=float,
            ),
        },
    )

    config_path = tmp_path / "config_comparison_depth.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_depth_mask"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "depth_max_last"',
                'variable = "watertable_depth"',
                'support = "map"',
                'time = "last"',
                'reducer = "max"',
                'unit = "m"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_depth_mask",
        simulation=cfg.comparison.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.comparison.observable),
        store=store,
        sim_id=SIM_ID,
    )

    assert len(rows) == 1
    assert rows[0]["observable"] == "depth_max_last"
    assert rows[0]["value"] == 4.0


def test_outlet_without_location_requires_explicit_proxy_opt_in(tmp_path: Path) -> None:
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[comparison.observable]]",
                'name = "outlet_flux"',
                'variable = "outlet_flux"',
                'support = "outlet"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outlet observables require"):
        RuntimeComparisonConfig.from_toml(
            load_toml_with_base_config(config_path),
            config_path=config_path,
        )
