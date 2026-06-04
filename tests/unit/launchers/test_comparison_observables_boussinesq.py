from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.config import RuntimeComparisonConfig
from hydromodpy.analysis.comparison.runtime import (
    extract_observable_rows,
    load_variable_series,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

from ._comparison_builders import (
    OUTLET_CELL_AREA_M2,
    SIM_ID,
    _write_boussinesq_run_folder,
    _write_simulation_comparison_config,
)


def test_extract_observable_rows_reads_boussinesq_outlet_flux(tmp_path: Path) -> None:
    run_folder = tmp_path / "run_bouss"
    bundle_dir = tmp_path / "bundle_bouss"
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
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
    cfg = RuntimeComparisonConfig.from_toml(
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
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)

    series = load_variable_series(
        run_folder=run_folder,
        variable="dry_deficit_flux",
        store=store,
        sim_id=SIM_ID,
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
    cfg = RuntimeComparisonConfig.from_toml(
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
    cfg = RuntimeComparisonConfig.from_toml(
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
