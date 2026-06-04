from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import hydromodpy.analysis.comparison.audit.audit_engine as audit_engine_module
import hydromodpy.analysis.comparison.audit.audit_io as audit_io_module
from hydromodpy.analysis.comparison.audit import build_equivalence_audit
from hydromodpy.analysis.comparison.audit.audit_io import (
    HEAD_ABOVE_TOP_FRACTION_TOL,
    HEAD_ABOVE_TOP_TOL_M,
    RECHARGE_COMPONENT,
)
from hydromodpy.analysis.comparison.runtime import resolve_bundle_cells
from hydromodpy.cli.commands.run import _infer_workflow_from_sections
from hydromodpy.workflow.dispatch import resolve_workflow


def test_cli_resolves_comparison_workflow(tmp_path: Path) -> None:
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        '[workflow]\nmode = "comparison"\n[comparison]\nbase_simulation_config = "base.toml"\n',
        encoding="utf-8",
    )

    assert resolve_workflow(config_path, cli_workflow=None, require_toml_field=True) == "comparison"
    assert _infer_workflow_from_sections({"comparison": {}}) == "comparison"


def test_resolve_bundle_cells_reads_mesh_input_from_generated_config(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y,area_m2,storage_coefficient",
                "0,12.0,34.0,56.0,0.1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "generated_child.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[workspace]",
                'project_root = "."',
                "",
                "[simulation]",
                'run_id = "demo"',
                "",
                "[mesh_input]",
                'bundle_dir = "bundle"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cells = resolve_bundle_cells(
        tmp_path / "run_without_metrics",
        config_path=config_path,
        expected_size=1,
    )

    assert cells is not None
    assert cells.cell_ids.tolist() == [0]
    assert cells.x.tolist() == [12.0]
    assert cells.area_m2 is not None
    assert cells.area_m2.tolist() == [56.0]


def test_equivalence_audit_flags_physical_config_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_config = tmp_path / "mf6_ref.toml"
    candidate_config = tmp_path / "bouss_candidate.toml"
    common = [
        '[workflow]\nmode = "simulation"',
        "",
        "[simulation.time]",
        'start_datetime = "2020-01-01 00:00:00"',
        'end_datetime = "2020-01-15 00:00:00"',
        'step_value = "7 day"',
        "",
        "[flow]",
        'flow_regime = "transient"',
        'active_sinks_sources = ["recharge"]',
        "active_bc = []",
        "",
        "[flow.param.K]",
        'value = "1e-5 m/s"',
        "",
        "[flow.ic]",
        'type = "top"',
        "",
        "[flow.sinks_sources.recharge]",
        'first_clim = "mean"',
        "",
        "[data.recharge]",
        'date_start = "2020-01-01"',
        'date_end = "2020-01-15"',
        "",
        "[[data.recharge.sources]]",
        'source = "synthetic"',
        'freq = "7D"',
    ]
    ref_config.write_text(
        "\n".join([*common, "values = [1.0, 2.0]"]) + "\n",
        encoding="utf-8",
    )
    candidate_config.write_text(
        "\n".join([*common, "values = [1.0, 4.0]"]) + "\n",
        encoding="utf-8",
    )

    class FakeStore:
        def __init__(self, sim_id: str) -> None:
            self.sim_id = sim_id

        @property
        def connection(self) -> object:
            raise AttributeError("no parameter table")

        def list_simulations(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "sim_id": self.sim_id,
                        "mesh_hash": "same",
                        "n_cells": 1,
                        "n_timesteps": 2,
                        "crs_epsg": 2154,
                    }
                ]
            )

        def query_budget(self, sim_id: str) -> pd.DataFrame:
            assert sim_id == self.sim_id
            return pd.DataFrame()

        def close(self) -> None:
            pass

    def fake_discover_result_store(
        config_path: Path | None,
        *,
        preferred_sim_id: str | None = None,
        preferred_name: str | None = None,
    ) -> tuple[FakeStore, str]:
        del config_path, preferred_name
        sim_id = preferred_sim_id or "sim"
        return FakeStore(sim_id), sim_id

    monkeypatch.setattr(audit_io_module, "discover_result_store", fake_discover_result_store)

    audit = build_equivalence_audit(
        simulation_summaries=[
            {
                "id": "mf6_ref",
                "status": "completed",
                "sim_id": "ref",
                "config_path": str(ref_config),
            },
            {
                "id": "bouss_candidate",
                "status": "completed",
                "sim_id": "candidate",
                "config_path": str(candidate_config),
            },
        ],
        reference_simulation="mf6_ref",
        on_mismatch="warn",
    )

    assert audit["status"] == "warn"
    assert any(
        issue["kind"] == "config_section_mismatch" and issue["field"] == "data.recharge"
        for issue in audit["issues"]
    )


def test_equivalence_audit_ignores_method_specific_drainage_conductance_difference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def physical_config(flow_bc: dict[str, object]) -> dict[str, object]:
        return {
            "sections": {"flow.bc": flow_bc},
            "fingerprints": {"flow.bc": audit_io_module._section_fingerprint(flow_bc)},
        }

    ref_bc = {
        "cauchy": {
            "drainage": {
                "id": "drainage",
                "kind": "cauchy",
                "application_domain": "top",
                "description": "MF6 active top drainage",
                "value": "0.2 m2/s",
            }
        }
    }
    candidate_bc = {
        "cauchy": {
            "drainage": {
                "id": "drainage",
                "kind": "cauchy",
                "application_domain": "top",
                "description": "Boussinesq obstacle case, drainage disabled",
                "value": "0.0 m2/s",
            }
        }
    }

    def fake_load_audit_subject(summary: dict[str, object]) -> dict[str, object]:
        flow_bc = ref_bc if summary["id"] == "mf6_ref" else candidate_bc
        return {
            "id": summary["id"],
            "solver": summary["solver"],
            "status": "loaded",
            "metadata": {},
            "parameters": [],
            "physical_config": physical_config(flow_bc),
            "budget_components": {RECHARGE_COMPONENT: {"series": {"elapsed_seconds:0": 0.0}}},
        }

    monkeypatch.setattr(audit_engine_module, "_load_audit_subject", fake_load_audit_subject)

    audit = build_equivalence_audit(
        simulation_summaries=[
            {"id": "mf6_ref", "solver": "modflow6", "status": "completed"},
            {"id": "bouss_candidate", "solver": "boussinesq", "status": "completed"},
        ],
        reference_simulation="mf6_ref",
        on_mismatch="warn",
    )

    assert audit["status"] == "pass"
    assert audit["issues"] == []
    assert audit["ignored_issues"] == [
        {
            "level": "ignored",
            "kind": "config_section_mismatch",
            "simulation_id": "bouss_candidate",
            "reference_simulation": "mf6_ref",
            "field": "flow.bc",
            "message": (
                "Ignored solver-method drainage conductance difference "
                "between MODFLOW 6 and Boussinesq."
            ),
        }
    ]


def test_equivalence_audit_ignores_modflow6_watertable_above_top(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load_audit_subject(summary: dict[str, object]) -> dict[str, object]:
        return {
            "id": summary["id"],
            "solver": summary["solver"],
            "status": "loaded",
            "metadata": {},
            "parameters": [],
            "physical_config": {"sections": {}, "fingerprints": {}},
            "budget_components": {RECHARGE_COMPONENT: {"series": {"elapsed_seconds:0": 0.0}}},
        }

    def fake_head_bounds_diagnostics(**_: object) -> list[dict[str, object]]:
        return [
            {
                "simulation_id": "mf6_ref",
                "solver": "modflow6",
                "observable": "head_map_last",
                "above_top_fraction": 0.25,
                "above_top_max_m": 1.2,
            }
        ]

    monkeypatch.setattr(audit_engine_module, "_load_audit_subject", fake_load_audit_subject)
    monkeypatch.setattr(
        audit_engine_module,
        "_head_bounds_diagnostics",
        fake_head_bounds_diagnostics,
    )

    audit = build_equivalence_audit(
        simulation_summaries=[
            {"id": "mf6_ref", "solver": "modflow6", "status": "completed"},
            {"id": "bouss_candidate", "solver": "boussinesq", "status": "completed"},
        ],
        reference_simulation="mf6_ref",
        on_mismatch="warn",
    )

    assert audit["status"] == "pass"
    assert audit["issues"] == []
    assert audit["ignored_issues"] == [
        {
            "level": "ignored",
            "kind": "watertable_above_top",
            "simulation_id": "mf6_ref",
            "field": "head_map_last",
            "message": (
                "Ignored MODFLOW 6 watertable-above-top diagnostic; "
                "unconfined heads can be above cell top."
            ),
            "above_top_fraction": 0.25,
            "above_top_max_m": 1.2,
            "fraction_tolerance": HEAD_ABOVE_TOP_FRACTION_TOL,
            "height_tolerance_m": HEAD_ABOVE_TOP_TOL_M,
        }
    ]


def test_equivalence_audit_treats_missing_disabled_recharge_budget_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load_audit_subject(summary: dict[str, object]) -> dict[str, object]:
        series = {"elapsed_seconds:0": 0.0} if summary["id"] == "mf6_ref" else {}
        return {
            "id": summary["id"],
            "status": "loaded",
            "metadata": {},
            "parameters": [],
            "physical_config": {
                "sections": {"flow.active_sinks_sources": []},
                "fingerprints": {},
            },
            "budget_components": {RECHARGE_COMPONENT: {"series": series}},
        }

    monkeypatch.setattr(audit_engine_module, "_load_audit_subject", fake_load_audit_subject)

    audit = build_equivalence_audit(
        simulation_summaries=[
            {"id": "mf6_ref", "status": "completed"},
            {"id": "bouss_candidate", "status": "completed"},
        ],
        reference_simulation="mf6_ref",
        on_mismatch="warn",
    )

    candidate = next(subject for subject in audit["subjects"] if subject["id"] == "bouss_candidate")
    recharge_check = candidate["budget_checks"][RECHARGE_COMPONENT]
    assert audit["status"] == "pass"
    assert recharge_check["status"] == "pass"
    assert recharge_check["n_pairs"] == 1
    assert not any(issue["kind"] == "recharge_budget_mismatch" for issue in audit["issues"])


def test_equivalence_audit_warns_when_configured_recharge_budget_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load_audit_subject(summary: dict[str, object]) -> dict[str, object]:
        series = {"elapsed_seconds:0": 0.0} if summary["id"] == "mf6_ref" else {}
        return {
            "id": summary["id"],
            "status": "loaded",
            "metadata": {},
            "parameters": [],
            "physical_config": {
                "sections": {"flow.active_sinks_sources": ["recharge"]},
                "fingerprints": {},
            },
            "budget_components": {RECHARGE_COMPONENT: {"series": series}},
        }

    monkeypatch.setattr(audit_engine_module, "_load_audit_subject", fake_load_audit_subject)

    audit = build_equivalence_audit(
        simulation_summaries=[
            {"id": "mf6_ref", "status": "completed"},
            {"id": "bouss_candidate", "status": "completed"},
        ],
        reference_simulation="mf6_ref",
        on_mismatch="warn",
    )

    candidate = next(subject for subject in audit["subjects"] if subject["id"] == "bouss_candidate")
    recharge_check = candidate["budget_checks"][RECHARGE_COMPONENT]
    assert audit["status"] == "warn"
    assert recharge_check["status"] == "missing_overlap"
    assert any(issue["kind"] == "recharge_budget_mismatch" for issue in audit["issues"])


def test_equivalence_audit_flags_mixed_initial_state_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load_audit_subject(summary: dict[str, object]) -> dict[str, object]:
        return {
            "id": summary["id"],
            "status": "loaded",
            "metadata": {},
            "parameters": [],
            "physical_config": {"fingerprints": {}},
            "budget_components": {RECHARGE_COMPONENT: {"series": {"elapsed_seconds:86400": 1.0}}},
        }

    monkeypatch.setattr(audit_engine_module, "_load_audit_subject", fake_load_audit_subject)

    audit = build_equivalence_audit(
        simulation_summaries=[
            {"id": "mf6_ref", "status": "completed"},
            {"id": "bouss_candidate", "status": "completed"},
        ],
        reference_simulation="mf6_ref",
        on_mismatch="warn",
        observable_rows=[
            {
                "simulation_id": "mf6_ref",
                "observable": "head_point_series",
                "support": "point",
                "requested_time": "first",
                "resolved_variable": "watertable_elevation",
                "elapsed_seconds": 86400.0,
                "is_initial_state": False,
            },
            {
                "simulation_id": "bouss_candidate",
                "observable": "head_point_series",
                "support": "point",
                "requested_time": "first",
                "resolved_variable": "watertable_elevation",
                "elapsed_seconds": 0.0,
                "is_initial_state": True,
            },
            {
                "simulation_id": "bouss_candidate",
                "observable": "head_point_series",
                "support": "point",
                "requested_time": "first",
                "resolved_variable": "watertable_elevation",
                "elapsed_seconds": 86400.0,
                "is_initial_state": False,
            },
        ],
    )

    assert audit["status"] == "warn"
    assert audit["initial_state_policy"][0]["severity"] == "warning"
    assert any(issue["kind"] == "initial_state_policy_mismatch" for issue in audit["issues"])
