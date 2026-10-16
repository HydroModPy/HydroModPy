from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.analysis.comparison.runtime import extract_observable_rows

from ._comparison_builders import (
    OUTLET_CELL_AREA_M2,
    SIM_ID,
    _expected_outlet_flux,
    _FakeSource,
    _spec_from_toml,
    _write_direct_outlet_run_folder,
    _write_fake_run_folder,
    _write_simulation_comparison_config,
)


def test_extract_observable_rows_reads_point_and_strict_outlet(tmp_path: Path) -> None:
    run_folder = tmp_path / "run"
    store = _write_fake_run_folder(run_folder)
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    cfg = _spec_from_toml(config_path)
    simulation = cfg.simulation[0]

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        simulation=simulation,
        run_folder=run_folder,
        observables=tuple(cfg.observable),
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
    store = _write_fake_run_folder(run_folder)
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
                'mesh_mode = "triangle"',
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
    cfg = _spec_from_toml(config_path)

    rows = extract_observable_rows(
        comparison_id="demo_seepage_alias",
        simulation=cfg.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.observable),
        store=store,
        sim_id=SIM_ID,
    )

    assert len(rows) == 3
    assert all(row["resolved_variable"] == "seepage_mask" for row in rows)
    assert [float(row["value"]) for row in rows] == pytest.approx([1.0, 1.0, 0.0])


def test_extract_observable_rows_reads_direct_scalar_outlet_flux(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_direct"
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    store = _write_direct_outlet_run_folder(run_folder, outlet_value=1.25)
    cfg = _spec_from_toml(config_path)

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        simulation=cfg.simulation[0],
        run_folder=run_folder,
        observables=(cfg.observable[1],),
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


def test_extract_observable_rows_masks_depth_using_head_nodata(tmp_path: Path) -> None:
    run_folder = tmp_path / "run_depth_mask"
    run_folder.mkdir(parents=True, exist_ok=True)
    store = _FakeSource(
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
    cfg = _spec_from_toml(config_path)

    rows = extract_observable_rows(
        comparison_id="demo_depth_mask",
        simulation=cfg.simulation[0],
        run_folder=run_folder,
        observables=tuple(cfg.observable),
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
        _spec_from_toml(config_path)
