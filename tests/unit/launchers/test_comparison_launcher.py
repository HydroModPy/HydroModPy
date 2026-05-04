from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.analysis.comparison.child_materialization import (
    materialize_child_configs,
)
from hydromodpy.analysis.comparison.config import (
    ComparisonConfig,
    ComparisonObservable,
)
from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig
from hydromodpy.analysis.comparison.experiment_launcher import (
    SimulationComparisonLauncher,
)
from hydromodpy.analysis.comparison.exports import (
    _load_catalog_budget_rows,
    write_boussinesq_obstacle_diagnostics_export,
    write_budget_exports,
)
from hydromodpy.analysis.comparison.metric_diff import (
    build_comparison_metrics,
    build_unmatched_groups,
)
from hydromodpy.analysis.comparison.run_backend import ChildRunResult
from hydromodpy.analysis.comparison.runtime import (
    _resolve_recorded_output_path,
    extract_observable_rows,
    load_variable_series,
)
from hydromodpy.analysis.comparison.runtime_observables import select_time_slices
from hydromodpy.analysis.comparison.runtime_series import TimeSlice, VariableSeries
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

OUTLET_CELL_AREA_M2 = 10.0
SIM_ID = "sim-test"


class _FakeCatalog:
    def __init__(self, path: Path, root: dict[str, object]) -> None:
        self.zarr_path = path
        self._root = root
        self.closed = False

    def open_zarr(self, sim_id: str) -> SimpleNamespace:
        if sim_id != SIM_ID:
            raise KeyError(sim_id)
        return SimpleNamespace(root=self._root, close=lambda: None)

    @property
    def connection(self) -> object:
        raise AttributeError("fake catalog does not expose SQL parameters")

    def list_simulations(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "sim_id": SIM_ID,
                    "mesh_hash": "same",
                    "n_cells": 3,
                    "n_timesteps": 2,
                    "crs_epsg": 2154,
                }
            ]
        )

    def close(self) -> None:
        self.closed = True


def _patch_result_store(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[Path, _FakeCatalog],
) -> None:
    def _discover(
        config_path: Path | None,
        *,
        preferred_sim_id: str | None = None,
        preferred_name: str | None = None,
    ):
        if config_path is None:
            if len(mapping) == 1:
                return next(iter(mapping.values())), SIM_ID
            return None, None
        store = mapping.get(Path(config_path).resolve())
        if store is None and len(mapping) == 1:
            store = next(iter(mapping.values()))
        if store is None:
            return None, None
        return store, SIM_ID

    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.experiment_launcher.discover_result_store",
        _discover,
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.visuals_payloads.discover_result_store",
        _discover,
    )
    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.runtime_metadata.discover_result_store",
        _discover,
    )


def _write_base_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
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
    import rasterio
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


def _write_simulation_comparison_config(path: Path, run_folder: Path) -> None:
    simulation_config = path.parent / f"{path.stem}_mf6_demo.toml"
    simulation_config.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "",
                "[simulation]",
                'run_id = "mf6_demo"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                'output_root = "comparison_outputs"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'solver = "modflow6"',
                'mesh_mode = "mesh_catchment"',
                f'simulation_config = "{simulation_config.as_posix()}"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "head_at_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "x = 10.0",
                "y = 0.0",
                'time = "last"',
                'unit = "m"',
                "",
                "[[comparison.observable]]",
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


def _write_comparison_anchors(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[comparison_anchors.demo.reference]",
                "x = 10.0",
                "y = 0.0",
                "",
                "[comparison_anchors.demo.outlet]",
                "x = 10.0",
                "y = 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_visual_simulation_comparison_config(
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
                "[comparison]",
                'comparison_id = "demo_visual_compare"',
                'output_root = "comparison_outputs"',
                'reference_simulation = "mf6_demo"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[comparison.audit]",
                'on_mismatch = "warn"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'label = "MF6 reference"',
                'solver = "modflow6"',
                'mesh_mode = "structured"',
                f'simulation_config = "{reference_config_path.as_posix()}"',
                f'run_folder = "{reference_run_folder.as_posix()}"',
                "",
                "[[comparison.simulation]]",
                'id = "nwt_demo"',
                'label = "NWT candidate"',
                'solver = "modflownwt"',
                'mesh_mode = "structured"',
                f'simulation_config = "{candidate_config_path.as_posix()}"',
                f'run_folder = "{candidate_run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "head_map"',
                'variable = "watertable_elevation"',
                'support = "map"',
                'time = "last"',
                'reducer = "identity"',
                'unit = "m"',
                "",
                "[[comparison.observable]]",
                'name = "head_left_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
                'time = "all"',
                'unit = "m"',
                "",
                "[[comparison.observable]]",
                'name = "head_right_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 2",
                'time = "all"',
                'unit = "m"',
                "",
                "[[comparison.observable]]",
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


def _write_structured_xy_simulation_comparison_config(
    path: Path,
    *,
    run_folder: Path,
    simulation_config_path: Path,
) -> None:
    path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_structured_xy"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "nwt_demo"',
                'solver = "modflownwt"',
                'mesh_mode = "structured"',
                f'simulation_config = "{simulation_config_path.as_posix()}"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "head_xy_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "x = 1.4",
                "y = 1.6",
                'time = "last"',
                'unit = "m"',
                "",
                "[[comparison.observable]]",
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
) -> _FakeCatalog:
    run_folder.mkdir(parents=True, exist_ok=True)
    store = _FakeCatalog(
        run_folder / "simulation.zarr",
        {
            "watertable_elevation": np.asarray(
                [
                    np.asarray([10.0, 20.0, 30.0]) + head_offset,
                    np.asarray([11.0, 21.0, 31.0]) + head_offset,
                ],
                dtype=float,
            ),
            "accumulation_flux": np.asarray(
                [
                    np.asarray([0.1, 0.4, 0.2]) + accumulation_offset,
                    np.asarray([0.3, 0.8, 0.5]) + accumulation_offset,
                ],
                dtype=float,
            ),
            "seepage_mask": np.asarray(
                [
                    np.asarray([0.0, 1.0, 0.0]),
                    np.asarray([1.0, 1.0, 0.0]),
                ],
                dtype=float,
            ),
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
    return store


def _write_direct_outlet_run_folder(run_folder: Path, *, outlet_value: float) -> _FakeCatalog:
    run_folder.mkdir(parents=True, exist_ok=True)
    return _FakeCatalog(
        run_folder / "simulation.zarr",
        {
            "outlet_discharge_east_side_m3_s": np.asarray(
                [[outlet_value], [outlet_value + 0.25]],
                dtype=float,
            )
        },
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


def _write_boussinesq_run_folder(run_folder: Path, bundle_dir: Path) -> _FakeCatalog:
    run_folder.mkdir(parents=True, exist_ok=True)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y,area_m2,storage_coefficient,z_top_mean,z_bottom_mean",
                "0,0.0,0.0,5.0,0.08,11.0,9.8",
                f"1,10.0,0.0,{OUTLET_CELL_AREA_M2},0.08,12.2,11.55",
                "2,20.0,0.0,7.0,0.08,13.0,11.8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    state = {
        "recharge_rate_history_m_s": np.asarray(
            [[1.0e-8, 2.0e-8, 1.5e-8], [2.0e-8, 1.0e-8, 2.5e-8]],
            dtype=float,
        ),
        "well_flux_history_m3_s": np.asarray(
            [[-0.01, -0.02, 0.0], [-0.01, -0.015, 0.0]],
            dtype=float,
        ),
        "head_history_m": np.asarray(
            [[10.0, 11.0, 12.0], [10.5, 11.25, 12.5]],
            dtype=float,
        ),
        "saturation_excess_history_m_s": np.asarray(
            [[0.0, 0.02, 0.01], [0.01, 0.03, 0.0]],
            dtype=float,
        ),
        "dry_deficit_history_m_s": np.asarray(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.005, 0.0],
            ],
            dtype=float,
        ),
        "drainage_flux_history_m3_s": np.asarray(
            [
                [0.05, 0.15, 0.07],
                [0.08, 0.3, 0.1],
            ],
            dtype=float,
        ),
        "period_lengths_seconds": np.asarray([3600.0], dtype=float),
    }
    (run_folder / "_boussinesq_summary.json").write_text(
        json.dumps({"bundle_dir": str(bundle_dir)}),
        encoding="utf-8",
    )
    np.savez(run_folder / "_boussinesq_state_history.npz", **state)
    return _FakeCatalog(run_folder / "simulation.zarr", {"boussinesq_state": state})


def _expected_outlet_flux(value_m_per_day: float) -> float:
    return value_m_per_day * OUTLET_CELL_AREA_M2 / 86400.0


def test_comparison_config_resolves_paths(tmp_path: Path) -> None:
    run_folder = tmp_path / "runs" / "mf6_demo"
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)

    cfg = ComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.comparison_root == (tmp_path / "comparison_outputs").resolve()
    assert cfg.comparison.comparison_id == "demo_compare"
    assert cfg.resolve_simulation_run_folder(cfg.comparison.simulation[0]) == run_folder.resolve()
    assert cfg.comparison.observable[1].reducer == "sum"


def test_comparison_config_applies_anchor_file(tmp_path: Path) -> None:
    anchors_path = tmp_path / "comparison_points.toml"
    _write_comparison_anchors(anchors_path)
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_anchor_compare"',
                'anchors_file = "comparison_points.toml"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[comparison.observable]]",
                'name = "head_at_anchor"',
                'variable = "watertable_elevation"',
                'support = "point"',
                'anchor_id = "demo.reference"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = ComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    observable = cfg.comparison.observable[0]
    assert observable.anchor_id == "demo.reference"
    assert observable.x == 10.0
    assert observable.y == 0.0


def test_comparison_config_accepts_canonical_anchor_file(tmp_path: Path) -> None:
    anchors_path = tmp_path / "comparison_points.toml"
    anchors_path.write_text(
        "\n".join(
            [
                "[comparison_anchors.demo.reference]",
                "x = 11.0",
                "y = 1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_anchor_compare"',
                'anchors_file = "comparison_points.toml"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[comparison.observable]]",
                'name = "head_at_anchor"',
                'variable = "watertable_elevation"',
                'support = "point"',
                'anchor_id = "demo.reference"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = ComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.comparison is cfg.comparison
    assert cfg.comparison.observable[0].x == 11.0
    assert cfg.comparison.observable[0].y == 1.0


def test_materialize_simulation_config_writes_base_overlay(tmp_path: Path) -> None:
    base_config = tmp_path / "run_flow_common.toml"
    _write_base_simulation_config(base_config)
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                'base_simulation_config = "run_flow_common.toml"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                "",
                "[comparison.simulation.overlay.mesh_input]",
                'bundle_dir = "results_stable/mesh/bundle"',
                "",
                "[[comparison.observable]]",
                'name = "head_cell"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = SimulationComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    generated = materialize_child_configs(cfg)[0].config_path

    assert generated is not None
    raw = load_toml_with_base_config(generated)
    assert raw["simulation"]["run_id"] == "demo_compare__bouss_demo"
    assert raw["simulation"]["process"][0]["solvers"] == ["boussinesq"]
    assert (
        raw["mesh_input"]["bundle_dir"]
        == (tmp_path / "results_stable" / "mesh" / "bundle").resolve().as_posix()
    )


def test_extract_observable_rows_reads_point_and_strict_outlet(tmp_path: Path) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    store = _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    cfg = ComparisonConfig.from_toml(
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
    cfg = ComparisonConfig.from_toml(
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
                'workflow = "simulation"',
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
    cfg = ComparisonConfig.from_toml(
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
    cfg = ComparisonConfig.from_toml(
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


def test_extract_observable_rows_reads_boussinesq_outlet_flux(tmp_path: Path) -> None:
    run_folder = tmp_path / "run_bouss"
    bundle_dir = tmp_path / "bundle_bouss"
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    cfg = ComparisonConfig.from_toml(
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
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)

    config_path = tmp_path / "config_comparison_bouss_map.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_bouss_map"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                'mesh_mode = "mesh_input"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
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
    cfg = ComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_bouss_map",
        simulation=cfg.comparison.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.comparison.observable),
        store=store,
        sim_id=SIM_ID,
    )

    assert len(rows) == 3
    assert all(row["resolved_variable"] == "drainage_flux_history_m3_s" for row in rows)
    assert all(row["unit"] == "m/day" for row in rows)
    assert all(row["conversion_applied"] == "drainage_flux_m3_s_to_m_per_day" for row in rows)
    first_value = float(rows[0]["value"])
    assert first_value == pytest.approx((0.08 / 5.0) * 86400.0)


def test_load_variable_series_derives_boussinesq_surface_excess_flux(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_surface_excess"
    bundle_dir = tmp_path / "bundle_bouss_surface_excess"
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)

    series = load_variable_series(
        run_folder=run_folder,
        variable="surface_excess_flux",
        store=store,
        sim_id=SIM_ID,
    )

    assert series.variable_name == "surface_excess_total_m3_s"
    assert len(series.slices) == 2
    assert float(series.slices[0].values[0]) == pytest.approx(0.27)
    assert float(series.slices[1].values[0]) == pytest.approx(0.35)


def test_load_variable_series_derives_boussinesq_dry_deficit_flux(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_dry_deficit"
    bundle_dir = tmp_path / "bundle_bouss_dry_deficit"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    series = load_variable_series(
        run_folder=run_folder,
        variable="dry_deficit_flux",
    )

    assert series.variable_name == "dry_deficit_total_m3_s"
    assert len(series.slices) == 2
    assert float(series.slices[0].values[0]) == pytest.approx(0.0)
    assert float(series.slices[1].values[0]) == pytest.approx(0.005 * OUTLET_CELL_AREA_M2)


def test_extract_observable_rows_reads_surface_excess_map_and_series(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_surface_compare"
    bundle_dir = tmp_path / "bundle_bouss_surface_compare"
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)

    config_path = tmp_path / "config_comparison_surface_excess.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_surface_excess"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                'mesh_mode = "mesh_input"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "surface_excess_flux_series"',
                'variable = "surface_excess_flux"',
                'support = "cell_mask"',
                'time = "all"',
                'reducer = "sum"',
                'unit = "m3/s"',
                "",
                "[[comparison.observable]]",
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
    cfg = ComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_surface_excess",
        simulation=cfg.comparison.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.comparison.observable),
        store=store,
        sim_id=SIM_ID,
    )

    series_rows = [row for row in rows if row["observable"] == "surface_excess_flux_series"]
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_folder = tmp_path / "run_bouss_budget"
    bundle_dir = tmp_path / "bundle_bouss_budget"
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)

    comparison_root = tmp_path / "comparison"
    config_path = tmp_path / "run_bouss_budget.toml"
    config_path.write_text('[workspace]\nproject_root = "."\n', encoding="utf-8")
    _patch_result_store(monkeypatch, {config_path.resolve(): store})
    artifacts, rows = write_budget_exports(
        comparison_root=comparison_root,
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Bouss demo",
                "solver": "boussinesq",
                "mesh_mode": "mesh_input",
                "status": "completed",
                "run_folder": str(run_folder),
                "config_path": str(config_path),
            }
        ],
    )

    assert artifacts
    assert any(row["component"] == "surface_excess_total_m3_s" for row in rows)
    assert any(row["component"] == "comparable_outflow_total_m3_s" for row in rows)
    assert any(row["component"] == "dry_deficit_total_m3_s" for row in rows)
    assert any(row["component"] == "storage_change_total_m3_s" for row in rows)
    recharge_row = next(
        row
        for row in rows
        if row["component"] == "recharge_total_m3_s" and int(row["period_index"]) == 0
    )
    storage_row = next(
        row
        for row in rows
        if row["component"] == "storage_change_total_m3_s" and int(row["period_index"]) == 0
    )
    residual_row = next(
        row
        for row in rows
        if row["component"] == "closure_residual_m3_s" and int(row["period_index"]) == 0
    )
    dry_row = next(
        row
        for row in rows
        if row["component"] == "dry_deficit_total_m3_s" and int(row["period_index"]) == 0
    )
    comparable_row = next(
        row
        for row in rows
        if row["component"] == "comparable_outflow_total_m3_s" and int(row["period_index"]) == 0
    )
    assert int(recharge_row["time_index"]) == 1
    assert recharge_row["time_role"] == "period_value"
    assert recharge_row["period_start_seconds"] == pytest.approx(0.0)
    assert recharge_row["period_end_seconds"] == pytest.approx(3600.0)
    assert not recharge_row["is_initial_state"]
    assert float(recharge_row["value"]) == pytest.approx(3.75e-7)
    assert float(storage_row["value"]) == pytest.approx(0.68 / 3600.0)
    assert float(dry_row["value"]) == pytest.approx(0.005 * OUTLET_CELL_AREA_M2)
    assert float(comparable_row["value"]) == pytest.approx(0.35 + 0.48)
    assert math.isfinite(float(residual_row["value"]))
    assert float(residual_row["value"]) == pytest.approx(
        3.75e-7 - 0.025 + 0.005 * OUTLET_CELL_AREA_M2 - 0.48 - 0.35 - (0.68 / 3600.0)
    )


def test_write_budget_exports_uses_child_config_bundle_when_run_folder_has_no_mesh_metadata(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "generated_configs"
    bundle_dir = tmp_path / "bundle_from_child_config"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)
    (run_folder / "_boussinesq_summary.json").unlink()

    config_dir = tmp_path / "comparison" / "_generated_configs"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "bouss_candidate.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "",
                "[mesh_input]",
                'bundle_dir = "../../bundle_from_child_config"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts, rows = write_budget_exports(
        comparison_root=tmp_path / "comparison",
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Bouss demo",
                "solver": "boussinesq",
                "mesh_mode": "mesh_input",
                "status": "completed",
                "run_folder": str(run_folder),
                "config_path": str(config_path),
            }
        ],
    )

    assert artifacts
    assert any(row["component"] == "recharge_total_m3_s" for row in rows)


def test_write_boussinesq_obstacle_diagnostics_exports_bounds_and_dry_deficit(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_obstacles"
    bundle_dir = tmp_path / "bundle_bouss_obstacles"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    artifacts, rows = write_boussinesq_obstacle_diagnostics_export(
        comparison_root=tmp_path / "comparison",
        simulation_summaries=[
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
    assert rows
    last = next(row for row in rows if int(row["time_index"]) == 1)
    assert float(last["min_head_above_bottom_m"]) == pytest.approx(-0.3)
    assert float(last["max_head_below_bottom_m"]) == pytest.approx(0.3)
    assert int(last["head_below_bottom_cell_count"]) == 1
    assert float(last["negative_storage_volume_m3"]) == pytest.approx(0.24)
    assert int(last["dry_deficit_active_cell_count"]) == 1
    assert float(last["dry_deficit_total_m3_s"]) == pytest.approx(0.005 * OUTLET_CELL_AREA_M2)


def test_catalog_budget_rows_are_normalized_to_elapsed_seconds_and_m3_s(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mf6_child.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "",
                "[simulation]",
                'name = "mf6_budget_demo"',
                "",
                "[simulation.time]",
                'start_datetime = "2020-01-01 00:00:00"',
                'end_datetime = "2020-01-02 00:00:00"',
                'step_value = "1 day"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeBudgetStore:
        def query_budget(self, sim_id: str) -> pd.DataFrame:
            assert sim_id == "mf6-demo"
            return pd.DataFrame(
                [
                    {
                        "timestep": 0,
                        "component": "rcha",
                        "flux_in": 2.5,
                        "flux_out": 0.0,
                        "unit": "m3/d",
                    },
                    {
                        "timestep": 0,
                        "component": "chd",
                        "flux_in": 0.1,
                        "flux_out": 0.4,
                        "unit": "m3/d",
                    },
                    {
                        "timestep": 0,
                        "component": "sto-sy",
                        "flux_in": 0.2,
                        "flux_out": 1.0,
                        "unit": "m3/d",
                    },
                    {
                        "timestep": 1,
                        "component": "rcha",
                        "flux_in": 0.0,
                        "flux_out": 0.0,
                        "unit": "m3/s",
                    },
                ]
            )

    rows = _load_catalog_budget_rows(
        {
            "id": "mf6_ref",
            "label": "MF6 reference",
            "solver": "modflow6",
            "mesh_mode": "mesh_input",
            "config_path": str(config_path),
        },
        FakeBudgetStore(),
        "mf6-demo",
    )

    by_component = {row["component"]: row for row in rows if int(row["time_index"]) == 0}
    assert by_component["recharge_total_m3_s"]["elapsed_seconds"] == pytest.approx(86400.0)
    assert by_component["recharge_total_m3_s"]["time_role"] == "period_value"
    assert by_component["recharge_total_m3_s"]["period_index"] == 0
    assert by_component["recharge_total_m3_s"]["period_start_seconds"] == pytest.approx(0.0)
    assert by_component["recharge_total_m3_s"]["period_end_seconds"] == pytest.approx(86400.0)
    assert not by_component["recharge_total_m3_s"]["is_initial_state"]
    assert by_component["recharge_total_m3_s"]["unit"] == "m3/s"
    assert by_component["recharge_total_m3_s"]["value"] == pytest.approx(2.5)
    assert by_component["prescribed_head_out_total_m3_s"]["value"] == pytest.approx(0.3)
    assert by_component["storage_change_total_m3_s"]["value"] == pytest.approx(0.8)
    assert by_component["closure_residual_m3_s"]["value"] == pytest.approx(1.4)


@pytest.mark.skipif(os.name == "nt", reason="POSIX keeps WSL mount paths unchanged")
def test_resolve_recorded_output_path_keeps_wsl_mount_path_on_posix() -> None:
    path = _resolve_recorded_output_path(
        "/mnt/c/codes/HydroModPy/examples",
        base_dir=Path("/tmp"),
    )

    assert path is not None
    assert path.as_posix() == "/mnt/c/codes/HydroModPy/examples"


@pytest.mark.skipif(os.name != "nt", reason="WSL bundle-path normalization is Windows-specific")
def test_extract_observable_rows_resolves_wsl_bundle_path_on_windows(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_wsl"
    bundle_dir = tmp_path / "bundle_bouss_wsl"
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)

    resolved_bundle = bundle_dir.resolve()
    drive = resolved_bundle.drive.rstrip(":").lower()
    tail = str(resolved_bundle)[2:].replace("\\", "/").lstrip("/")
    wsl_bundle = f"/mnt/{drive}/{tail}"
    (run_folder / "_boussinesq_summary.json").write_text(
        json.dumps({"bundle_dir": wsl_bundle}),
        encoding="utf-8",
    )

    config_path = tmp_path / "config_comparison_wsl.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare_wsl_bundle"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[comparison.observable]]",
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
    cfg = ComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    rows = extract_observable_rows(
        comparison_id="demo_compare_wsl_bundle",
        simulation=cfg.comparison.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.comparison.observable),
        store=store,
        sim_id=SIM_ID,
    )

    outlet = rows[0]
    assert outlet["value"] == pytest.approx(0.3)


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
    cfg = ComparisonConfig.from_toml(
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
        ComparisonConfig.from_toml(
            load_toml_with_base_config(config_path),
            config_path=config_path,
        )


def test_simulation_comparison_launcher_reuses_existing_run_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    store = _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    _patch_result_store(monkeypatch, {config_path.resolve(): store})

    summary = SimulationComparisonLauncher(config_path).run()

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


def test_simulation_comparison_launcher_generates_visual_figures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_run = tmp_path / "reference_run"
    candidate_run = tmp_path / "candidate_run"
    reference_bundle = tmp_path / "reference_bundle"
    candidate_bundle = tmp_path / "candidate_bundle"
    reference_store = _write_fake_run_folder(reference_run, reference_bundle)
    candidate_store = _write_fake_run_folder(
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

    config_path = tmp_path / "config_comparison_visuals.toml"
    _write_visual_simulation_comparison_config(
        config_path,
        reference_run_folder=reference_run,
        candidate_run_folder=candidate_run,
        reference_config_path=reference_solver_config,
        candidate_config_path=candidate_solver_config,
    )
    _patch_result_store(
        monkeypatch,
        {
            reference_solver_config.resolve(): reference_store,
            candidate_solver_config.resolve(): candidate_store,
        },
    )

    summary = SimulationComparisonLauncher(config_path).run()

    figures = summary["comparison_figures"]
    assert summary["comparison_figures_dir"]
    assert {item["kind"] for item in figures} == {
        "case_configuration",
        "map_comparison",
        "difference_map",
        "map_triptych",
        "timeseries",
        "point_dashboard",
        "simulated_active_network_figures_skipped_json",
    }
    for item in figures:
        figure_path = Path(item["path"])
        assert figure_path.exists()
        assert figure_path.stat().st_size > 0

    report_text = Path(summary["comparison_report_md"]).read_text(encoding="utf-8")
    assert "## Figures" in report_text
    assert "head_map" in report_text
    assert "outlet_flux_series" in report_text


def test_simulation_comparison_launcher_writes_chronicles_native_flux_and_runtime_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_run = tmp_path / "reference_run"
    candidate_run = tmp_path / "candidate_run"
    reference_bundle = tmp_path / "reference_bundle"
    candidate_bundle = tmp_path / "candidate_bundle"
    reference_store = _write_fake_run_folder(reference_run, reference_bundle)
    candidate_store = _write_fake_run_folder(
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

    config_path = tmp_path / "config_comparison_outputs.toml"
    _write_visual_simulation_comparison_config(
        config_path,
        reference_run_folder=reference_run,
        candidate_run_folder=candidate_run,
        reference_config_path=reference_solver_config,
        candidate_config_path=candidate_solver_config,
    )
    _patch_result_store(
        monkeypatch,
        {
            reference_solver_config.resolve(): reference_store,
            candidate_solver_config.resolve(): candidate_store,
        },
    )

    summary = SimulationComparisonLauncher(config_path).run()

    artifact_kinds = {item["kind"] for item in summary["comparison_data_artifacts"]}
    assert "timeseries_long_csv" in artifact_kinds
    assert "native_timeseries_long_csv" in artifact_kinds
    assert "execution_times_csv" in artifact_kinds

    figure_kinds = {item["kind"] for item in summary["comparison_figures"]}
    assert "native_flux_panel" in figure_kinds
    assert "execution_time_bars" in figure_kinds
    assert "point_dashboard" in figure_kinds


def test_simulation_comparison_launcher_generates_structured_figures_from_run_folder_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_run = tmp_path / "reference_structured_run"
    candidate_run = tmp_path / "candidate_structured_run"
    reference_store = _FakeCatalog(
        reference_run / "simulation.zarr",
        {
            "watertable_elevation": np.asarray(
                [[10.0, 20.0, 30.0, 40.0], [11.0, 21.0, 31.0, 41.0]],
                dtype=float,
            )
        },
    )
    candidate_store = _FakeCatalog(
        candidate_run / "simulation.zarr",
        {
            "watertable_elevation": np.asarray(
                [[10.5, 20.5, 30.5, 40.5], [11.5, 21.5, 31.5, 41.5]],
                dtype=float,
            )
        },
    )
    reference_run.mkdir(parents=True, exist_ok=True)
    candidate_run.mkdir(parents=True, exist_ok=True)
    _write_solver_grid_template(reference_run, nx=2, ny=2)
    _write_solver_grid_template(candidate_run, nx=2, ny=2)
    reference_solver_config = tmp_path / "structured_reference.toml"
    candidate_solver_config = tmp_path / "structured_candidate.toml"
    _write_structured_solver_config(reference_solver_config, solver="modflow6", nx=2, ny=2)
    _write_structured_solver_config(candidate_solver_config, solver="modflownwt", nx=2, ny=2)

    config_path = tmp_path / "config_comparison_structured_reuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_structured_reuse_visuals"',
                'output_root = "comparison_outputs"',
                'reference_simulation = "mf6_demo"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[comparison.audit]",
                'on_mismatch = "warn"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'label = "MF6 reference"',
                'solver = "modflow6"',
                'mesh_mode = "structured"',
                f'run_folder = "{reference_run.as_posix()}"',
                f'simulation_config = "{reference_solver_config.as_posix()}"',
                "",
                "[[comparison.simulation]]",
                'id = "nwt_demo"',
                'label = "NWT candidate"',
                'solver = "modflownwt"',
                'mesh_mode = "structured"',
                f'run_folder = "{candidate_run.as_posix()}"',
                f'simulation_config = "{candidate_solver_config.as_posix()}"',
                "",
                "[[comparison.observable]]",
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
    _patch_result_store(
        monkeypatch,
        {
            reference_solver_config.resolve(): reference_store,
            candidate_solver_config.resolve(): candidate_store,
        },
    )

    summary = SimulationComparisonLauncher(config_path).run()

    figures = summary["comparison_figures"]
    assert {item["kind"] for item in figures} == {
        "case_configuration",
        "map_comparison",
        "difference_map",
        "map_triptych",
        "simulated_active_network_figures_skipped_json",
    }
    for item in figures:
        figure_path = Path(item["path"])
        assert figure_path.exists()
        assert figure_path.stat().st_size > 0


def test_simulation_comparison_launcher_infers_completed_run_folder_from_declared_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "solver_scratch"
    simulation_config = tmp_path / "run_solver.toml"
    simulation_config.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "[workspace]",
                'project_root = "project/demo"',
                f'solver_scratch_folder = "{scratch.as_posix()}"',
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

    actual_run_folder = scratch / "demo_run" / "flow_main__boussinesq"
    actual_run_folder.mkdir(parents=True, exist_ok=True)
    (actual_run_folder / "_metrics.json").write_text("{}", encoding="utf-8")
    comparison_config = tmp_path / "config_comparison.toml"
    comparison_config.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                "[comparison.execution]",
                "run_simulations = true",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                f'simulation_config = "{simulation_config.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "head_cell"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    class _RootConfigProvider:
        def from_toml(self, _config_path: Path):
            return SimpleNamespace(
                workspace=SimpleNamespace(solver_scratch_folder=scratch),
                simulation=SimpleNamespace(run_id="demo_run"),
            )

    monkeypatch.setattr(
        launcher_module,
        "get_root_config_provider",
        lambda: _RootConfigProvider(),
    )

    launcher = SimulationComparisonLauncher(comparison_config)
    child = materialize_child_configs(launcher.cfg)[0]
    summary = launcher._summary_from_run_result(
        child,
        ChildRunResult(
            config_path=simulation_config,
            returncode=0,
            wall_time_seconds=0.25,
            sim_id=SIM_ID,
            stdout="",
            stderr="",
        ),
    )

    assert summary["status"] == "completed"
    assert Path(summary["run_folder"]) == actual_run_folder.resolve()


def test_simulation_comparison_launcher_reuse_infers_process_output_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "solver_scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    class _RootConfigProvider:
        def from_toml(self, _config_path: Path):
            return SimpleNamespace(
                workspace=SimpleNamespace(solver_scratch_folder=scratch),
                simulation=SimpleNamespace(run_id="ex12_demo_mod_bouss_tri"),
            )

    monkeypatch.setattr(
        launcher_module,
        "get_root_config_provider",
        lambda: _RootConfigProvider(),
    )

    resolved = SimulationComparisonLauncher._infer_run_folder_from_config(
        tmp_path / "config.toml",
        solver_name="boussinesq",
    )

    assert resolved.name == "ex12_demo_mod_bouss_tri"


def test_build_comparison_metrics_against_reference(tmp_path: Path) -> None:
    reference_run = tmp_path / "reference"
    candidate_run = tmp_path / "candidate"
    bundle_dir = tmp_path / "bundle"
    reference_store = _write_fake_run_folder(reference_run, bundle_dir)
    candidate_store = _write_fake_run_folder(
        candidate_run,
        bundle_dir,
        head_offset=2.0,
        accumulation_offset=0.1,
    )
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, reference_run)
    cfg = ComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )
    reference_simulation = cfg.comparison.simulation[0]
    candidate_simulation = reference_simulation.model_copy(
        update={"id": "candidate", "label": "candidate"}
    )

    rows = []
    rows.extend(
        extract_observable_rows(
            comparison_id="demo_compare",
            simulation=reference_simulation,
            run_folder=reference_run,
            observables=tuple(cfg.comparison.observable),
            store=reference_store,
            sim_id=SIM_ID,
        )
    )
    rows.extend(
        extract_observable_rows(
            comparison_id="demo_compare",
            simulation=candidate_simulation,
            run_folder=candidate_run,
            observables=tuple(cfg.comparison.observable),
            store=candidate_store,
            sim_id=SIM_ID,
        )
    )

    detail, summary = build_comparison_metrics(rows, reference_simulation="mf6_demo")

    assert len(detail) == 2
    summary_by_observable = {row["observable"]: row for row in summary}
    assert summary_by_observable["head_at_point"]["mae"] == 2.0
    assert summary_by_observable["outlet_flux"]["mae"] == pytest.approx(_expected_outlet_flux(0.1))


def test_build_comparison_metrics_aligns_last_selection_across_time_indices() -> None:
    rows = [
        {
            "comparison_id": "demo_compare",
            "simulation_id": "reference",
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
            "simulation_id": "candidate",
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

    detail, summary = build_comparison_metrics(rows, reference_simulation="reference")

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
                "simulation_id": "reference",
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
            "simulation_id": "candidate",
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
                "simulation_id": "candidate",
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

    detail, summary = build_comparison_metrics(rows, reference_simulation="reference")
    unmatched = build_unmatched_groups(rows, reference_simulation="reference")

    assert len(detail) == 3
    assert summary[0]["n_pairs"] == 3
    assert summary[0]["mae"] == 0.5
    assert unmatched == [
        {
            "simulation_id": "candidate",
            "observable": "outlet_flux_series",
            "unit": "m3/s",
            "n_rows": 1,
            "reason": "missing aligned reference row or unit mismatch",
        }
    ]


def test_runtime_observables_integer_time_selects_non_initial_snapshot() -> None:
    series = VariableSeries(
        variable_name="watertable_elevation",
        source_path=Path("memory"),
        slices=(
            TimeSlice(
                time_key=0,
                time_index=0,
                values=np.array([10.0]),
                elapsed_seconds=0.0,
                is_initial_state=True,
            ),
            TimeSlice(
                time_key=1,
                time_index=1,
                values=np.array([11.0]),
                elapsed_seconds=86400.0,
                is_initial_state=False,
            ),
            TimeSlice(
                time_key=2,
                time_index=2,
                values=np.array([12.0]),
                elapsed_seconds=172800.0,
                is_initial_state=False,
            ),
        ),
    )
    observable = ComparisonObservable(
        name="head_after_first_step",
        variable="watertable_elevation",
        support="map",
        time=0,
    )

    selected = select_time_slices(series, observable)

    assert len(selected) == 1
    assert selected[0].time_index == 1
    assert not selected[0].is_initial_state
