from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.analysis.comparison.config import (
    ComparisonObservable,
    RuntimeComparisonConfig,
)
from hydromodpy.analysis.comparison.metric_diff import (
    build_comparison_metrics,
    build_unmatched_groups,
)
from hydromodpy.analysis.comparison.runtime import extract_observable_rows
from hydromodpy.analysis.comparison.runtime.observables import select_time_slices
from hydromodpy.analysis.comparison.runtime.series import TimeSlice, VariableSeries
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

from ._comparison_builders import (
    SIM_ID,
    _expected_outlet_flux,
    _write_fake_run_folder,
    _write_simulation_comparison_config,
)


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
    cfg = RuntimeComparisonConfig.from_toml(
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


def test_build_comparison_metrics_does_not_match_incompatible_time_roles() -> None:
    rows = [
        {
            "comparison_id": "demo_compare",
            "simulation_id": "reference",
            "observable": "head_map_first",
            "comparison_time_key": "elapsed_seconds:86400",
            "match_fallback_key": "time_selector:first",
            "time_role": "state_snapshot",
            "value_index": 0,
            "value": 2.0,
            "unit": "m",
            "selection": "map",
            "is_nodata": False,
        },
        {
            "comparison_id": "demo_compare",
            "simulation_id": "candidate",
            "observable": "head_map_first",
            "comparison_time_key": "elapsed_seconds:0",
            "match_fallback_key": "time_selector:first",
            "time_role": "initial_state",
            "value_index": 0,
            "value": 1.0,
            "unit": "m",
            "selection": "map",
            "is_nodata": False,
        },
    ]

    detail, summary = build_comparison_metrics(rows, reference_simulation="reference")
    unmatched = build_unmatched_groups(rows, reference_simulation="reference")

    assert detail == []
    assert summary == []
    assert unmatched == [
        {
            "simulation_id": "candidate",
            "observable": "head_map_first",
            "unit": "m",
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


def test_runtime_observables_supports_explicit_initial_and_first_computed_selectors() -> None:
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
        ),
    )

    initial = select_time_slices(
        series,
        ComparisonObservable(
            name="head_initial",
            variable="watertable_elevation",
            support="map",
            time="initial_state",
        ),
    )
    first_computed = select_time_slices(
        series,
        ComparisonObservable(
            name="head_first_computed",
            variable="watertable_elevation",
            support="map",
            time="first_computed",
        ),
    )

    assert initial[0].time_index == 0
    assert initial[0].is_initial_state
    assert first_computed[0].time_index == 1
    assert not first_computed[0].is_initial_state
