"""Shared builders, fakes, and config writers for comparison launcher tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import hydromodpy

# Structured-shape resolution needs the solver registry provider, which the
# deferred bootstrap installs only on first real use. Force it here so every
# importing test file gets it regardless of run order.
hydromodpy.bootstrap()

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
        "hydromodpy.analysis.comparison.runtime.metadata.discover_result_store",
        _discover,
    )


def _write_base_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
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
                '[workflow]\nmode = "simulation"',
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


def _write_boussinesq_run_folder(
    run_folder: Path,
    bundle_dir: Path,
    *,
    residual_history_m3_s: np.ndarray | None = None,
) -> _FakeCatalog:
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
    if residual_history_m3_s is not None:
        state["residual_history_m3_s"] = np.asarray(residual_history_m3_s, dtype=float)
    (run_folder / "_boussinesq_summary.json").write_text(
        json.dumps({"bundle_dir": str(bundle_dir)}),
        encoding="utf-8",
    )
    np.savez(run_folder / "_boussinesq_state_history.npz", **state)
    return _FakeCatalog(run_folder / "simulation.zarr", {"boussinesq_state": state})


def _expected_outlet_flux(value_m_per_day: float) -> float:
    return value_m_per_day * OUTLET_CELL_AREA_M2 / 86400.0
