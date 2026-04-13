from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.analysis.comparison.config import MethodComparisonConfig
from hydromodpy.analysis.comparison.exports import write_budget_exports
from launchers.method_comparison.launcher import MethodComparisonLauncher
from hydromodpy.analysis.comparison.metrics import (
    build_comparison_metrics,
    build_unmatched_groups,
)
from hydromodpy.analysis.comparison.runtime import (
    extract_observable_rows,
    load_variable_series,
    materialize_variant_config,
)

OUTLET_CELL_AREA_M2 = 10.0


def _load_launchers_main_module():
    module_path = Path(__file__).resolve().parents[3] / "launchers" / "__main__.py"
    spec = importlib.util.spec_from_file_location(
        "launchers_main_method_comparison_test_module",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_base_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "project/base_case"',
                "",
                "[simulation]",
                'run_id = "base_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow6"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_structured_solver_config(path: Path, *, solver: str, nx: int, ny: int) -> None:
    path.write_text(
        "\n".join(
            [
                f"[{solver}.sgrid.planar]",
                "dx = 100.0",
                "dy = 100.0",
                f"nx = {nx}",
                f"ny = {ny}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_solver_grid_template(run_folder: Path, *, nx: int, ny: int) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    run_folder.mkdir(parents=True, exist_ok=True)
    raster_path = run_folder / "_solver_grid_template.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, float(ny), 1.0, 1.0),
    ) as dataset:
        dataset.write(np.ones((ny, nx), dtype="float32"), 1)


def _write_method_comparison_config(path: Path, run_folder: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                'output_root = "comparison_outputs"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                'solver = "modflow6"',
                'mesh_mode = "mesh_catchment"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_at_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "x = 10.0",
                "y = 0.0",
                'time = "last"',
                'unit = "m"',
                "",
                "[[method_comparison.observable]]",
                'name = "outlet_flux"',
                'variable = "outlet_flux"',
                'support = "outlet"',
                "cell_index = 1",
                'time = "last"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_method_comparison_anchors(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[method_comparison_anchors.demo.reference]",
                "x = 10.0",
                "y = 0.0",
                "",
                "[method_comparison_anchors.demo.outlet]",
                "x = 10.0",
                "y = 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_visual_method_comparison_config(
    path: Path,
    *,
    reference_run_folder: Path,
    candidate_run_folder: Path,
    reference_config_path: Path,
    candidate_config_path: Path,
) -> None:
    path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_visual_compare"',
                'output_root = "comparison_outputs"',
                "run_variants = false",
                'reference_variant = "mf6_demo"',
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                'label = "MF6 reference"',
                'solver = "modflow6"',
                'mesh_mode = "structured"',
                f'simulation_config = "{reference_config_path.as_posix()}"',
                f'run_folder = "{reference_run_folder.as_posix()}"',
                "",
                "[[method_comparison.variant]]",
                'id = "nwt_demo"',
                'label = "NWT candidate"',
                'solver = "modflownwt"',
                'mesh_mode = "structured"',
                f'simulation_config = "{candidate_config_path.as_posix()}"',
                f'run_folder = "{candidate_run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_map"',
                'variable = "watertable_elevation"',
                'support = "map"',
                'time = "last"',
                'reducer = "identity"',
                'unit = "m"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_left_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
                'time = "all"',
                'unit = "m"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_right_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 2",
                'time = "all"',
                'unit = "m"',
                "",
                "[[method_comparison.observable]]",
                'name = "outlet_flux_series"',
                'variable = "outlet_flux"',
                'support = "outlet"',
                "cell_index = 1",
                'time = "all"',
                'unit = "m3/s"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_structured_xy_method_comparison_config(
    path: Path,
    *,
    run_folder: Path,
    simulation_config_path: Path,
) -> None:
    path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_structured_xy"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "nwt_demo"',
                'solver = "modflownwt"',
                'mesh_mode = "structured"',
                f'simulation_config = "{simulation_config_path.as_posix()}"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_xy_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "x = 1.4",
                "y = 1.6",
                'time = "last"',
                'unit = "m"',
                "",
                "[[method_comparison.observable]]",
                'name = "outlet_flux_xy"',
                'variable = "outlet_flux"',
                'support = "outlet"',
                "x = 1.4",
                "y = 1.6",
                'time = "last"',
                'unit = "m3/s"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_fake_run_folder(
    run_folder: Path,
    bundle_dir: Path,
    *,
    head_offset: float = 0.0,
    accumulation_offset: float = 0.0,
) -> None:
    postprocess_dir = run_folder / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        postprocess_dir / "watertable_elevation.npy",
        {
            0: np.asarray([10.0, 20.0, 30.0]) + head_offset,
            1: np.asarray([11.0, 21.0, 31.0]) + head_offset,
        },
    )
    np.save(
        postprocess_dir / "accumulation_flux.npy",
        {
            0: np.asarray([0.1, 0.4, 0.2]) + accumulation_offset,
            1: np.asarray([0.3, 0.8, 0.5]) + accumulation_offset,
        },
    )
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y,area_m2",
                "0,0.0,0.0,5.0",
                f"1,10.0,0.0,{OUTLET_CELL_AREA_M2}",
                "2,20.0,0.0,7.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_folder / "_metrics.json").write_text(
        json.dumps({"mesh_output_exchange_bundle_dir": str(bundle_dir)}),
        encoding="utf-8",
    )


def _write_direct_outlet_run_folder(run_folder: Path, *, outlet_value: float) -> None:
    postprocess_dir = run_folder / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        postprocess_dir / "outlet_discharge_east_side_m3_s.npy",
        {0: np.asarray([outlet_value]), 1: np.asarray([outlet_value + 0.25])},
    )


def _write_native_timeseries_csv(
    run_folder: Path,
    *,
    accumulation_values: list[float],
    drain_values: list[float],
) -> None:
    timeseries_dir = run_folder / "_postprocess" / "_timeseries"
    timeseries_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        "date;accumulation_flux;outflow_drain",
    ]
    for index, (accumulation, drain) in enumerate(zip(accumulation_values, drain_values)):
        rows.append(f"{index};{accumulation};{drain}")
    (timeseries_dir / "_simulated_timeseries.csv").write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _write_boussinesq_run_folder(run_folder: Path, bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y,area_m2,storage_coefficient",
                "0,0.0,0.0,5.0,0.08",
                f"1,10.0,0.0,{OUTLET_CELL_AREA_M2},0.08",
                "2,20.0,0.0,7.0,0.08",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    np.savez(
        run_folder / "_boussinesq_state_history.npz",
        recharge_rate_history_m_s=np.asarray(
            [
                [1.0e-8, 2.0e-8, 1.5e-8],
                [2.0e-8, 1.0e-8, 2.5e-8],
            ],
            dtype=float,
        ),
        well_flux_history_m3_s=np.asarray(
            [
                [-0.01, -0.02, 0.0],
                [-0.01, -0.015, 0.0],
            ],
            dtype=float,
        ),
        head_history_m=np.asarray(
            [
                [10.0, 11.0, 12.0],
                [10.5, 11.25, 12.5],
            ],
            dtype=float,
        ),
        saturation_excess_history_m_s=np.asarray(
            [
                [0.0, 0.02, 0.01],
                [0.01, 0.03, 0.0],
            ],
            dtype=float,
        ),
        drainage_flux_history_m3_s=np.asarray(
            [
                [0.05, 0.15, 0.07],
                [0.08, 0.3, 0.1],
            ],
            dtype=float,
        ),
        period_lengths_seconds=np.asarray([3600.0], dtype=float),
    )
    (run_folder / "_boussinesq_summary.json").write_text(
        json.dumps({"bundle_dir": str(bundle_dir)}),
        encoding="utf-8",
    )


def _expected_outlet_flux(value_m_per_day: float) -> float:
    return value_m_per_day * OUTLET_CELL_AREA_M2 / 86400.0


def test_method_comparison_config_resolves_paths(tmp_path: Path) -> None:
    run_folder = tmp_path / "runs" / "mf6_demo"
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)

    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.comparison_root == (tmp_path / "comparison_outputs").resolve()
    assert cfg.method_comparison.comparison_id == "demo_compare"
    assert cfg.resolve_variant_run_folder(
        cfg.method_comparison.variant[0]
    ) == run_folder.resolve()
    assert cfg.method_comparison.observable[1].reducer == "sum"


@pytest.mark.parametrize(
    ("config_name", "expected_mesh_modes", "expected_supports"),
    [
        (
            "run_method_comparison_mf6_vs_nwt_same_regular_mesh.toml",
            ["structured", "structured"],
            ["point", "point", "map", "outlet"],
        ),
        (
            "run_method_comparison_mf6_vs_nwt_different_meshes.toml",
            ["mesh_input", "structured"],
            ["map", "map"],
        ),
        (
            "run_method_comparison_mf6_vs_nwt_different_meshes_demonstrative.toml",
            ["mesh_input", "structured"],
            ["point", "point", "point", "outlet", "map", "map", "map"],
        ),
        (
            "run_method_comparison_example12_multi_method_moderate.toml",
            ["structured", "structured", "mesh_input", "mesh_input"],
            ["point", "point", "point", "outlet", "map", "map", "map", "cell_mask", "map"],
        ),
        (
            "run_method_comparison_example12_fast_shared_mesh.toml",
            ["mesh_input", "mesh_input"],
            ["point", "outlet", "map", "map"],
        ),
        (
            "run_method_comparison_example12_extensive_mf6_vs_nwt.toml",
            ["structured", "structured"],
            ["point", "outlet", "map", "map"],
        ),
        (
            "run_method_comparison_headwater_100km2_outlet_2_backends.toml",
            ["mesh_input", "mesh_input", "mesh_input"],
            ["point", "outlet", "map", "map"],
        ),
        (
            "run_method_comparison_headwater_100km2_outlet_2_transient_pulsed_recharge_backends.toml",
            ["mesh_input", "mesh_input", "mesh_input"],
            ["point", "outlet", "map", "map"],
        ),
        (
            "run_method_comparison_headwater_100km2_outlet_2_transient_cycling_recharge_heterogeneous_backends.toml",
            ["mesh_input", "mesh_input", "mesh_input"],
            ["point", "outlet", "map", "map"],
        ),
    ],
)
def test_example_method_comparison_configs_load(
    config_name: str,
    expected_mesh_modes: list[str],
    expected_supports: list[str],
) -> None:
    config_path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "projects"
        / "launcher_simulation"
        / config_name
    )

    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert [variant.mesh_mode for variant in cfg.method_comparison.variant] == expected_mesh_modes
    assert [observable.support for observable in cfg.method_comparison.observable] == expected_supports
    for observable in cfg.method_comparison.observable:
        if observable.anchor_id is not None:
            assert observable.x is not None
            assert observable.y is not None


def test_method_comparison_config_applies_anchor_file(tmp_path: Path) -> None:
    anchors_path = tmp_path / "method_comparison_points.toml"
    _write_method_comparison_anchors(anchors_path)
    config_path = tmp_path / "config_method_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_anchor_compare"',
                'anchors_file = "method_comparison_points.toml"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_at_anchor"',
                'variable = "watertable_elevation"',
                'support = "point"',
                'anchor_id = "demo.reference"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    observable = cfg.method_comparison.observable[0]
    assert observable.anchor_id == "demo.reference"
    assert observable.x == 10.0
    assert observable.y == 0.0


def test_materialize_variant_config_writes_base_overlay(tmp_path: Path) -> None:
    base_config = tmp_path / "run_flow_common.toml"
    _write_base_simulation_config(base_config)
    config_path = tmp_path / "config_method_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                'base_simulation_config = "run_flow_common.toml"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                "",
                "[method_comparison.variant.overlay.mesh_input]",
                'bundle_dir = "results_stable/mesh/bundle"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_cell"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    generated = materialize_variant_config(
        cfg=cfg,
        variant=cfg.method_comparison.variant[0],
    )

    assert generated is not None
    raw = load_toml_with_base_config(generated)
    assert raw["simulation"]["run_id"] == "bouss_demo"
    assert raw["simulation"]["process"][0]["solvers"] == ["boussinesq"]
    assert raw["mesh_input"]["bundle_dir"] == "results_stable/mesh/bundle"


def test_extract_observable_rows_reads_point_and_strict_outlet(tmp_path: Path) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )
    variant = cfg.method_comparison.variant[0]

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        variant=variant,
        run_folder=run_folder,
        observables=tuple(cfg.method_comparison.observable),
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
    assert outlet["unit"] == "m3/s"
    assert outlet["native_unit"] == "m3/s"
    assert outlet["derived_from_variable"] == "accumulation_flux"
    assert outlet["conversion_applied"] == "accumulation_flux_m_per_day_to_m3_s"
    assert float(outlet["cell_area_m2"]) == OUTLET_CELL_AREA_M2


def test_extract_observable_rows_resolves_structured_xy_from_config(tmp_path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
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
                "[workspace]",
                f'project_root = "{project_root.as_posix()}"',
                "",
                "[simulation]",
                'run_id = "structured_demo_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflownwt"]',
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
    postprocess_dir = run_folder / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        postprocess_dir / "watertable_elevation.npy",
        {
            0: np.asarray([10.0, 20.0, 30.0, 40.0]),
            1: np.asarray([11.0, 21.0, 31.0, 41.0]),
        },
    )
    np.save(
        postprocess_dir / "accumulation_flux.npy",
        {
            0: np.asarray([0.1, 0.4, 0.2, 0.3]),
            1: np.asarray([0.3, 0.8, 0.5, 0.6]),
        },
    )

    comparison_config = tmp_path / "config_structured_xy.toml"
    _write_structured_xy_method_comparison_config(
        comparison_config,
        run_folder=run_folder,
        simulation_config_path=simulation_config,
    )
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(comparison_config),
        config_path=comparison_config,
    )

    rows = extract_observable_rows(
        comparison_id="demo_structured_xy",
        variant=cfg.method_comparison.variant[0],
        run_folder=run_folder,
        observables=tuple(cfg.method_comparison.observable),
        config_path=cfg.resolve_variant_config_path(cfg.method_comparison.variant[0]),
    )

    head = next(row for row in rows if row["observable"] == "head_xy_point")
    outlet = next(row for row in rows if row["observable"] == "outlet_flux_xy")
    assert head["value"] == 21.0
    assert head["selected_cell_index"] == "1"
    assert outlet["value"] == pytest.approx(0.8 / 86400.0)
    assert outlet["selected_cell_index"] == "1"


def test_extract_observable_rows_reads_direct_scalar_outlet_flux(tmp_path: Path) -> None:
    run_folder = tmp_path / "run_direct"
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)
    _write_direct_outlet_run_folder(run_folder, outlet_value=1.25)
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        variant=cfg.method_comparison.variant[0],
        run_folder=run_folder,
        observables=(cfg.method_comparison.observable[1],),
    )

    assert len(rows) == 1
    outlet = rows[0]
    assert outlet["value"] == pytest.approx(1.5)
    assert outlet["resolved_variable"] == "outlet_discharge_east_side_m3_s"
    assert outlet["selection"] == "native_outlet_series"
    assert outlet["unit"] == "m3/s"
    assert outlet["conversion_applied"] == ""


def test_extract_observable_rows_reads_boussinesq_outlet_flux(tmp_path: Path) -> None:
    run_folder = tmp_path / "run_bouss"
    bundle_dir = tmp_path / "bundle_bouss"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        variant=cfg.method_comparison.variant[0],
        run_folder=run_folder,
        observables=(cfg.method_comparison.observable[1],),
    )

    assert len(rows) == 1
    outlet = rows[0]
    assert outlet["value"] == pytest.approx(0.3)
    assert outlet["resolved_variable"] == "drainage_flux_history_m3_s"
    assert outlet["selection"] == "declared_cell"
    assert outlet["unit"] == "m3/s"
    assert outlet["conversion_applied"] == ""


def test_extract_observable_rows_converts_boussinesq_drainage_map_to_outflow_drain(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_map"
    bundle_dir = tmp_path / "bundle_bouss_map"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    config_path = tmp_path / "config_method_comparison_bouss_map.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_bouss_map"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                'mesh_mode = "mesh_input"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "drain_map"',
                'variable = "outflow_drain"',
                'support = "map"',
                'time = "last"',
                'unit = "m/day"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_bouss_map",
        variant=cfg.method_comparison.variant[0],
        run_folder=run_folder,
        observables=tuple(cfg.method_comparison.observable),
    )

    assert len(rows) == 3
    assert all(row["resolved_variable"] == "drainage_flux_history_m3_s" for row in rows)
    assert all(row["unit"] == "m/day" for row in rows)
    assert all(
        row["conversion_applied"] == "drainage_flux_m3_s_to_m_per_day"
        for row in rows
    )
    first_value = float(rows[0]["value"])
    assert first_value == pytest.approx((0.08 / 5.0) * 86400.0)


def test_load_variable_series_derives_boussinesq_surface_excess_flux(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_surface_excess"
    bundle_dir = tmp_path / "bundle_bouss_surface_excess"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    series = load_variable_series(
        run_folder=run_folder,
        variable="surface_excess_flux",
    )

    assert series.variable_name == "surface_excess_total_m3_s"
    assert len(series.slices) == 2
    assert float(series.slices[0].values[0]) == pytest.approx(0.27)
    assert float(series.slices[1].values[0]) == pytest.approx(0.35)


def test_extract_observable_rows_reads_surface_excess_map_and_series(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_surface_compare"
    bundle_dir = tmp_path / "bundle_bouss_surface_compare"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    config_path = tmp_path / "config_method_comparison_surface_excess.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_surface_excess"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                'mesh_mode = "mesh_input"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "surface_excess_flux_series"',
                'variable = "surface_excess_flux"',
                'support = "cell_mask"',
                'time = "all"',
                'reducer = "sum"',
                'unit = "m3/s"',
                "",
                "[[method_comparison.observable]]",
                'name = "surface_excess_map_last"',
                'variable = "surface_excess_rate"',
                'support = "map"',
                'time = "last"',
                'unit = "m/day"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_surface_excess",
        variant=cfg.method_comparison.variant[0],
        run_folder=run_folder,
        observables=tuple(cfg.method_comparison.observable),
    )

    series_rows = [
        row for row in rows if row["observable"] == "surface_excess_flux_series"
    ]
    map_rows = [row for row in rows if row["observable"] == "surface_excess_map_last"]
    assert [float(row["value"]) for row in series_rows] == pytest.approx([0.27, 0.35])
    assert all(row["unit"] == "m3/s" for row in series_rows)
    assert all(row["resolved_variable"] == "surface_excess_total_m3_s" for row in series_rows)
    assert len(map_rows) == 3
    assert all(row["resolved_variable"] == "saturation_excess_history_m_s" for row in map_rows)
    assert all(row["conversion_applied"] == "surface_excess_m_s_to_m_per_day" for row in map_rows)
    assert float(map_rows[0]["value"]) == pytest.approx(0.01 * 86400.0)


def test_write_budget_exports_derives_boussinesq_budget_timeseries(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_budget"
    bundle_dir = tmp_path / "bundle_bouss_budget"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    comparison_root = tmp_path / "comparison"
    artifacts, rows = write_budget_exports(
        comparison_root=comparison_root,
        variant_summaries=[
            {
                "id": "bouss_demo",
                "label": "Bouss demo",
                "solver": "boussinesq",
                "mesh_mode": "mesh_input",
                "status": "completed",
                "run_folder": str(run_folder),
            }
        ],
    )

    assert artifacts
    assert any(row["component"] == "surface_excess_total_m3_s" for row in rows)
    assert any(row["component"] == "storage_change_total_m3_s" for row in rows)
    recharge_row = next(
        row
        for row in rows
        if row["component"] == "recharge_total_m3_s" and int(row["time_index"]) == 0
    )
    storage_row = next(
        row
        for row in rows
        if row["component"] == "storage_change_total_m3_s" and int(row["time_index"]) == 1
    )
    residual_row = next(
        row
        for row in rows
        if row["component"] == "closure_residual_m3_s" and int(row["time_index"]) == 1
    )
    assert float(recharge_row["value"]) == pytest.approx(3.55e-7)
    assert float(storage_row["value"]) == pytest.approx(0.68 / 3600.0)
    assert math.isfinite(float(residual_row["value"]))


@pytest.mark.skipif(os.name != "nt", reason="WSL bundle-path normalization is Windows-specific")
def test_extract_observable_rows_resolves_wsl_bundle_path_on_windows(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_wsl"
    bundle_dir = tmp_path / "bundle_bouss_wsl"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    resolved_bundle = bundle_dir.resolve()
    drive = resolved_bundle.drive.rstrip(":").lower()
    tail = str(resolved_bundle)[2:].replace("\\", "/").lstrip("/")
    wsl_bundle = f"/mnt/{drive}/{tail}"
    (run_folder / "_boussinesq_summary.json").write_text(
        json.dumps({"bundle_dir": wsl_bundle}),
        encoding="utf-8",
    )

    config_path = tmp_path / "config_method_comparison_wsl.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare_wsl_bundle"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "outlet_flux"',
                'variable = "outlet_flux"',
                'support = "outlet"',
                "x = 10.0",
                "y = 0.0",
                'time = "last"',
                'unit = "m3/s"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_compare_wsl_bundle",
        variant=cfg.method_comparison.variant[0],
        run_folder=run_folder,
        observables=tuple(cfg.method_comparison.observable),
    )

    outlet = rows[0]
    assert outlet["value"] == pytest.approx(0.3)


def test_extract_observable_rows_masks_depth_using_head_nodata(tmp_path: Path) -> None:
    run_folder = tmp_path / "run_depth_mask"
    postprocess_dir = run_folder / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        postprocess_dir / "watertable_elevation.npy",
        {0: np.asarray([10.0, -9999.0, 12.0]), 1: np.asarray([11.0, -9999.0, 13.0])},
    )
    np.save(
        postprocess_dir / "watertable_depth.npy",
        {0: np.asarray([1.0, 10000.0, 3.0]), 1: np.asarray([2.0, 10001.0, 4.0])},
    )

    config_path = tmp_path / "config_method_comparison_depth.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_depth_mask"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
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
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_depth_mask",
        variant=cfg.method_comparison.variant[0],
        run_folder=run_folder,
        observables=tuple(cfg.method_comparison.observable),
    )

    assert len(rows) == 1
    assert rows[0]["observable"] == "depth_max_last"
    assert rows[0]["value"] == 4.0


def test_outlet_without_location_requires_explicit_proxy_opt_in(tmp_path: Path) -> None:
    config_path = tmp_path / "config_method_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[method_comparison.observable]]",
                'name = "outlet_flux"',
                'variable = "outlet_flux"',
                'support = "outlet"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outlet observables require"):
        MethodComparisonConfig.from_toml(
            load_toml_with_base_config(config_path),
            config_path=config_path,
        )


def test_method_comparison_launcher_reuses_existing_run_folder(tmp_path: Path) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)

    summary = MethodComparisonLauncher(config_path).run()

    manifest_path = Path(summary["manifest_path"])
    observables_csv = Path(summary["observables_csv"])
    assert manifest_path.exists()
    assert observables_csv.exists()
    assert summary["n_observable_rows"] == 2
    with observables_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["observable"] for row in rows} == {
        "head_at_point",
        "outlet_flux",
    }
    assert Path(summary["comparison_metrics_csv"]).exists()
    assert Path(summary["comparison_differences_csv"]).exists()
    assert Path(summary["comparison_report_md"]).exists()


def test_method_comparison_launcher_generates_visual_figures(tmp_path: Path) -> None:
    reference_run = tmp_path / "reference_run"
    candidate_run = tmp_path / "candidate_run"
    reference_bundle = tmp_path / "reference_bundle"
    candidate_bundle = tmp_path / "candidate_bundle"
    _write_fake_run_folder(reference_run, reference_bundle)
    _write_fake_run_folder(
        candidate_run,
        candidate_bundle,
        head_offset=1.5,
        accumulation_offset=0.2,
    )

    reference_solver_config = tmp_path / "run_reference_solver.toml"
    candidate_solver_config = tmp_path / "run_candidate_solver.toml"
    _write_structured_solver_config(
        reference_solver_config,
        solver="modflow6",
        nx=3,
        ny=1,
    )
    _write_structured_solver_config(
        candidate_solver_config,
        solver="modflownwt",
        nx=3,
        ny=1,
    )

    config_path = tmp_path / "config_method_comparison_visuals.toml"
    _write_visual_method_comparison_config(
        config_path,
        reference_run_folder=reference_run,
        candidate_run_folder=candidate_run,
        reference_config_path=reference_solver_config,
        candidate_config_path=candidate_solver_config,
    )

    summary = MethodComparisonLauncher(config_path).run()

    figures = summary["comparison_figures"]
    assert summary["comparison_figures_dir"]
    assert {item["kind"] for item in figures} == {
        "map_comparison",
        "difference_map",
        "timeseries",
        "point_dashboard",
    }
    for item in figures:
        figure_path = Path(item["path"])
        assert figure_path.exists()
        assert figure_path.stat().st_size > 0

    report_text = Path(summary["comparison_report_md"]).read_text(encoding="utf-8")
    assert "## Figures" in report_text
    assert "head_map" in report_text
    assert "outlet_flux_series" in report_text


def test_method_comparison_launcher_writes_chronicles_native_flux_and_runtime_outputs(
    tmp_path: Path,
) -> None:
    reference_run = tmp_path / "reference_run"
    candidate_run = tmp_path / "candidate_run"
    reference_bundle = tmp_path / "reference_bundle"
    candidate_bundle = tmp_path / "candidate_bundle"
    _write_fake_run_folder(reference_run, reference_bundle)
    _write_fake_run_folder(
        candidate_run,
        candidate_bundle,
        head_offset=1.5,
        accumulation_offset=0.2,
    )
    _write_native_timeseries_csv(
        reference_run,
        accumulation_values=[0.1, 0.2, 0.3],
        drain_values=[0.05, 0.08, 0.09],
    )
    _write_native_timeseries_csv(
        candidate_run,
        accumulation_values=[0.12, 0.18, 0.31],
        drain_values=[0.04, 0.09, 0.11],
    )
    (reference_run / "_metrics.json").write_text(
        json.dumps(
            {
                "mesh_output_exchange_bundle_dir": str(reference_bundle),
                "wall_time_seconds": 12.5,
                "solvers": ["modflow6"],
                "success": True,
            }
        ),
        encoding="utf-8",
    )
    (candidate_run / "_metrics.json").write_text(
        json.dumps(
            {
                "mesh_output_exchange_bundle_dir": str(candidate_bundle),
                "wall_time_seconds": 25.0,
                "solvers": ["modflownwt"],
                "success": True,
            }
        ),
        encoding="utf-8",
    )

    reference_solver_config = tmp_path / "run_reference_solver.toml"
    candidate_solver_config = tmp_path / "run_candidate_solver.toml"
    _write_structured_solver_config(reference_solver_config, solver="modflow6", nx=3, ny=1)
    _write_structured_solver_config(candidate_solver_config, solver="modflownwt", nx=3, ny=1)

    config_path = tmp_path / "config_method_comparison_outputs.toml"
    _write_visual_method_comparison_config(
        config_path,
        reference_run_folder=reference_run,
        candidate_run_folder=candidate_run,
        reference_config_path=reference_solver_config,
        candidate_config_path=candidate_solver_config,
    )

    summary = MethodComparisonLauncher(config_path).run()

    artifact_kinds = {item["kind"] for item in summary["comparison_data_artifacts"]}
    assert "timeseries_long_csv" in artifact_kinds
    assert "native_timeseries_long_csv" in artifact_kinds
    assert "execution_times_csv" in artifact_kinds

    figure_kinds = {item["kind"] for item in summary["comparison_figures"]}
    assert "native_flux_panel" in figure_kinds
    assert "execution_time_bars" in figure_kinds
    assert "point_dashboard" in figure_kinds


def test_method_comparison_launcher_generates_structured_figures_from_run_folder_template(
    tmp_path: Path,
) -> None:
    reference_run = tmp_path / "reference_structured_run"
    candidate_run = tmp_path / "candidate_structured_run"
    for run_folder in (reference_run, candidate_run):
        postprocess_dir = run_folder / "_postprocess"
        postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        reference_run / "_postprocess" / "watertable_elevation.npy",
        {0: np.asarray([10.0, 20.0, 30.0, 40.0]), 1: np.asarray([11.0, 21.0, 31.0, 41.0])},
    )
    np.save(
        candidate_run / "_postprocess" / "watertable_elevation.npy",
        {0: np.asarray([10.5, 20.5, 30.5, 40.5]), 1: np.asarray([11.5, 21.5, 31.5, 41.5])},
    )
    _write_solver_grid_template(reference_run, nx=2, ny=2)
    _write_solver_grid_template(candidate_run, nx=2, ny=2)

    config_path = tmp_path / "config_method_comparison_structured_reuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_structured_reuse_visuals"',
                'output_root = "comparison_outputs"',
                "run_variants = false",
                'reference_variant = "mf6_demo"',
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                'label = "MF6 reference"',
                'solver = "modflow6"',
                'mesh_mode = "structured"',
                f'run_folder = "{reference_run.as_posix()}"',
                "",
                "[[method_comparison.variant]]",
                'id = "nwt_demo"',
                'label = "NWT candidate"',
                'solver = "modflownwt"',
                'mesh_mode = "structured"',
                f'run_folder = "{candidate_run.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_map_last"',
                'variable = "watertable_elevation"',
                'support = "map"',
                'time = "last"',
                'unit = "m"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MethodComparisonLauncher(config_path).run()

    figures = summary["comparison_figures"]
    assert {item["kind"] for item in figures} == {"map_comparison", "difference_map"}
    for item in figures:
        figure_path = Path(item["path"])
        assert figure_path.exists()
        assert figure_path.stat().st_size > 0


def test_method_comparison_launcher_prefers_model_full_path_for_completed_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulation_config = tmp_path / "run_solver.toml"
    simulation_config.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "project/demo"',
                "",
                "[simulation]",
                'run_id = "demo_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["boussinesq"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    actual_run_folder = tmp_path / "results_simulations" / "flow_main__boussinesq"
    actual_run_folder.mkdir(parents=True, exist_ok=True)
    (actual_run_folder / "_metrics.json").write_text("{}", encoding="utf-8")
    comparison_config = tmp_path / "config_method_comparison.toml"
    comparison_config.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                "run_variants = true",
                "",
                "[[method_comparison.variant]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                f'simulation_config = "{simulation_config.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_cell"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class _FakeHydroModPyLauncher:
        def __init__(self, config_path: Path) -> None:
            self.config_path = config_path

        def run(self):
            return SimpleNamespace(
                setup=SimpleNamespace(
                    workspace=SimpleNamespace(
                        simulations_folder=tmp_path / "results_simulations"
                    ),
                    run_id="demo_run",
                ),
                get_model_for_solver=lambda _solver_name: SimpleNamespace(
                    full_path=actual_run_folder
                ),
            )

    import launchers

    monkeypatch.setattr(launchers, "HydroModPyLauncher", _FakeHydroModPyLauncher)
    monkeypatch.setattr(
        "launchers.method_comparison.launcher.read_variant_run_metadata",
        lambda _run_folder: {},
    )
    import launchers.method_comparison.launcher as launcher_module

    monkeypatch.setattr(
        launcher_module.HydroModPyConfig,
        "from_toml",
        classmethod(
            lambda _cls, _config_path: SimpleNamespace(
                workspace=SimpleNamespace(
                    simulations_folder=tmp_path / "project_root" / "results_simulations"
                ),
                simulation=SimpleNamespace(run_id="demo_run_reuse"),
            )
        ),
    )

    launcher = MethodComparisonLauncher(comparison_config)
    summary = launcher._run_or_reuse_variant(launcher.cfg.method_comparison.variant[0])

    assert summary["status"] == "completed"
    assert Path(summary["run_folder"]) == actual_run_folder


def test_method_comparison_launcher_reuse_infers_process_output_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_path
    _ = monkeypatch
    config_path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "projects"
        / "launcher_simulation"
        / "run_demonstrative_annual_moderate_boussinesq_precomputed_mesh_input.toml"
    )

    resolved = MethodComparisonLauncher._infer_run_folder_from_config(
        config_path,
        solver_name="boussinesq",
    )

    assert resolved.name == "flow_main__boussinesq"
    assert resolved.exists()


def test_build_comparison_metrics_against_reference(tmp_path: Path) -> None:
    reference_run = tmp_path / "reference"
    candidate_run = tmp_path / "candidate"
    bundle_dir = tmp_path / "bundle"
    _write_fake_run_folder(reference_run, bundle_dir)
    _write_fake_run_folder(
        candidate_run,
        bundle_dir,
        head_offset=2.0,
        accumulation_offset=0.1,
    )
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, reference_run)
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )
    reference_variant = cfg.method_comparison.variant[0]
    candidate_variant = reference_variant.model_copy(
        update={"id": "candidate", "label": "candidate"}
    )

    rows = []
    rows.extend(
        extract_observable_rows(
            comparison_id="demo_compare",
            variant=reference_variant,
            run_folder=reference_run,
            observables=tuple(cfg.method_comparison.observable),
        )
    )
    rows.extend(
        extract_observable_rows(
            comparison_id="demo_compare",
            variant=candidate_variant,
            run_folder=candidate_run,
            observables=tuple(cfg.method_comparison.observable),
        )
    )

    detail, summary = build_comparison_metrics(rows, reference_variant="mf6_demo")

    assert len(detail) == 2
    summary_by_observable = {row["observable"]: row for row in summary}
    assert summary_by_observable["head_at_point"]["mae"] == 2.0
    assert summary_by_observable["outlet_flux"]["mae"] == pytest.approx(
        _expected_outlet_flux(0.1)
    )


def test_build_comparison_metrics_aligns_last_selection_across_time_indices() -> None:
    rows = [
        {
            "comparison_id": "demo_compare",
            "variant_id": "reference",
            "observable": "head_map_last",
            "comparison_time_key": "time_index:2",
            "match_fallback_key": "time_selector:last",
            "value_index": 0,
            "value": 10.0,
            "unit": "m",
            "selection": "map",
            "is_nodata": False,
        },
        {
            "comparison_id": "demo_compare",
            "variant_id": "candidate",
            "observable": "head_map_last",
            "comparison_time_key": "time_index:3",
            "match_fallback_key": "time_selector:last",
            "value_index": 0,
            "value": 12.0,
            "unit": "m",
            "selection": "map",
            "is_nodata": False,
        },
    ]

    detail, summary = build_comparison_metrics(rows, reference_variant="reference")

    assert len(detail) == 1
    assert detail[0]["reference_match_strategy"] == "fallback_time_key"
    assert detail[0]["reference_match_key"] == "time_selector:last"
    assert summary[0]["n_pairs"] == 1
    assert summary[0]["mae"] == 2.0


def test_build_comparison_metrics_aligns_non_initial_steps_and_keeps_initial_unmatched() -> None:
    rows = []
    for index, value in enumerate((1.0, 2.0, 3.0)):
        rows.append(
            {
                "comparison_id": "demo_compare",
                "variant_id": "reference",
                "observable": "outlet_flux_series",
                "comparison_time_key": f"time_index:{index}",
                "match_fallback_key": f"non_initial_order:{index}",
                "value_index": 0,
                "value": value,
                "unit": "m3/s",
                "selection": "nearest_declared_outlet_point",
                "is_nodata": False,
            }
        )

    rows.append(
        {
            "comparison_id": "demo_compare",
            "variant_id": "candidate",
            "observable": "outlet_flux_series",
            "comparison_time_key": "elapsed_seconds:0",
            "match_fallback_key": "initial_state",
            "value_index": 0,
            "value": 0.0,
            "unit": "m3/s",
            "selection": "nearest_declared_outlet_point",
            "is_nodata": False,
        }
    )
    for index, value in enumerate((1.5, 2.5, 3.5)):
        rows.append(
            {
                "comparison_id": "demo_compare",
                "variant_id": "candidate",
                "observable": "outlet_flux_series",
                "comparison_time_key": f"elapsed_seconds:{(index + 1) * 1000}",
                "match_fallback_key": f"non_initial_order:{index}",
                "value_index": 0,
                "value": value,
                "unit": "m3/s",
                "selection": "nearest_declared_outlet_point",
                "is_nodata": False,
            }
        )

    detail, summary = build_comparison_metrics(rows, reference_variant="reference")
    unmatched = build_unmatched_groups(rows, reference_variant="reference")

    assert len(detail) == 3
    assert summary[0]["n_pairs"] == 3
    assert summary[0]["mae"] == 0.5
    assert unmatched == [
        {
            "variant_id": "candidate",
            "observable": "outlet_flux_series",
            "unit": "m3/s",
            "n_rows": 1,
            "reason": "missing aligned reference row or unit mismatch",
        }
    ]


def test_launchers_cli_method_comparison_run_dispatches_to_launcher(monkeypatch) -> None:
    module = _load_launchers_main_module()
    captured: dict[str, Path] = {}

    config_path = Path("sample_method_comparison.toml")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_method_comparison_launcher", _fake_runner)

    code = module.main(["method-comparison", "run", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()
