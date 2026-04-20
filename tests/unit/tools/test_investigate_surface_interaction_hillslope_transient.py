from __future__ import annotations

import numpy as np
from pathlib import Path

from tools.investigate_surface_interaction_hillslope_transient import (
    DT_DAYS,
    RECHARGE_SERIES_MM_DAY,
    _apply_transient_payload,
    _comparison_plot_style,
    _integrate_structured_flux_m3_day,
    _load_boussinesq_east_boundary_edge_mask,
    _load_scalar_series_m3_day,
    _select_snapshot_indices,
)
from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle


def test_select_snapshot_indices_uses_nearest_unique_steps() -> None:
    elapsed_days = np.asarray([10.0, 20.0, 30.0, 40.0, 50.0], dtype=float)
    selected = _select_snapshot_indices(elapsed_days, (9.0, 19.0, 21.0, 51.0))
    assert selected == [0, 1, 4]


def test_integrate_structured_flux_m3_day_sums_cellwise_discharge() -> None:
    values = np.asarray(
        [
            [[1.0, 2.0], [3.0, 4.0]],
            [[0.5, 0.5], [0.5, 0.5]],
        ],
        dtype=float,
    )
    integrated = _integrate_structured_flux_m3_day(values, dx_m=10.0, dy_m=5.0)
    np.testing.assert_allclose(
        integrated,
        np.asarray([10.0, 2.0], dtype=float) * 86400.0,
    )


def test_load_scalar_series_m3_day_reads_single_value_per_step(tmp_path: Path) -> None:
    payload = {
        0: np.asarray([1.0e-3], dtype=float),
        1: np.asarray([2.0e-3], dtype=float),
    }
    np.save(tmp_path / "outlet_discharge_east_side_m3_s.npy", payload)
    loaded = _load_scalar_series_m3_day(tmp_path, "outlet_discharge_east_side_m3_s")
    np.testing.assert_allclose(loaded, np.asarray([86.4, 172.8], dtype=float))


def test_load_boussinesq_east_boundary_edge_mask_selects_only_east_boundary(tmp_path: Path) -> None:
    (tmp_path / "nodes.csv").write_text(
        "\n".join(
            [
                "node_id,x,y,z_top,z_bottom",
                "0,0.0,0.0,10.0,0.0",
                "1,1.0,0.0,10.0,0.0",
                "2,0.0,1.0,10.0,0.0",
                "3,1.0,1.0,10.0,0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "edges.csv").write_text(
        "\n".join(
            [
                "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
                "0,0,2,0,,1.0,boundary,false,zone_1,",
                "1,1,3,0,,1.0,boundary,false,zone_1,",
                "2,0,1,0,,1.0,boundary,false,zone_1,",
                "3,2,3,0,,1.0,boundary,false,zone_1,",
                "4,0,3,0,1,1.414,internal,false,zone_1,zone_1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mask = _load_boussinesq_east_boundary_edge_mask(tmp_path)
    np.testing.assert_array_equal(mask, np.asarray([False, True, False, False, False]))


def test_apply_transient_payload_sets_modflow6_tgrid_first_period_transient() -> None:
    payload = _apply_transient_payload({}, solver="modflow6", hydraulic_conductivity_m_s=2.0e-5)
    assert payload["modflow6"]["tgrid"]["firstpersteady"] is False


def test_apply_transient_payload_sets_period_aligned_synthetic_recharge_frequency() -> None:
    payload = _apply_transient_payload({}, solver="modflownwt", hydraulic_conductivity_m_s=2.0e-5)
    source = payload["data"]["recharge"]["sources"][0]
    assert source["freq"] == f"{int(DT_DAYS)}D"
    assert source["values"] == [float(value) for value in RECHARGE_SERIES_MM_DAY]


def test_comparison_plot_style_keeps_nwt_as_points_only() -> None:
    style = _comparison_plot_style("modflownwt")
    assert style["linestyle"] == "None"
    assert style["marker"] == "o"
    assert style["linewidth"] == 0.0


def test_write_irregular_strip_bundle_writes_gmsh_and_bundle_tables(tmp_path: Path) -> None:
    bundle_dir = write_irregular_strip_bundle(
        tmp_path / "bundle",
        nx_seed=5,
        ny_seed=2,
        length_x_m=100.0,
        width_y_m=10.0,
        z_top_m=lambda x_m: 10.0 + 0.01 * np.asarray(x_m, dtype=float),
        z_bottom_m=lambda x_m: -5.0 + 0.01 * np.asarray(x_m, dtype=float),
        hydraulic_conductivity_m_s=1.0e-4,
        storage_coefficient=0.1,
        seed=42,
        base_mesh_size_m=8.0,
    )
    assert (bundle_dir / "mesh_2d.msh").exists()
    assert (bundle_dir / "nodes.csv").exists()
    assert (bundle_dir / "cells.csv").exists()
    assert (bundle_dir / "edges.csv").exists()
    assert (bundle_dir / "metadata.json").exists()
