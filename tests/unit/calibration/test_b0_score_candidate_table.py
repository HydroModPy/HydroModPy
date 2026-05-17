from __future__ import annotations

import importlib.util
import math
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "12_calibration_network_transient_b0"
    / "score_candidate_table.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("b0_score_candidate_table", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_load_candidate_specs_defaults_transient_catalog(tmp_path) -> None:
    module = _load_script_module()
    table = tmp_path / "candidates.csv"
    table.write_text(
        "\n".join(
            [
                "candidate_id,mK,Sy,steady_catalog,steady_ref,transient_ref",
                "c1,1.0,0.05,/tmp/steady.duckdb,steady_run,transient_run",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    specs = module.load_candidate_specs(table)

    assert specs == [
        {
            "candidate_id": "c1",
            "mK": "1.0",
            "Sy": "0.05",
            "steady_catalog": "/tmp/steady.duckdb",
            "steady_ref": "steady_run",
            "transient_ref": "transient_run",
            "transient_catalog": "/tmp/steady.duckdb",
        }
    ]


def test_load_candidate_specs_accepts_utf8_bom(tmp_path) -> None:
    module = _load_script_module()
    table = tmp_path / "candidates.csv"
    table.write_text(
        "\ufeffcandidate_id,mK,Sy,steady_catalog,steady_ref,transient_ref\n"
        "named,1.0,0.05,/tmp/steady.duckdb,steady_run,transient_run\n",
        encoding="utf-8",
    )

    specs = module.load_candidate_specs(table)

    assert specs[0]["candidate_id"] == "named"


def test_score_candidate_specs_ranks_completed_before_failed(monkeypatch, tmp_path) -> None:
    module = _load_script_module()
    specs = [
        {"candidate_id": "bad", "mK": "3", "Sy": "0.1"},
        {"candidate_id": "best", "mK": "1", "Sy": "0.05"},
        {"candidate_id": "ok", "mK": "2", "Sy": "0.08"},
    ]

    def fake_score_one(spec, *, truth_dir, catalog_cache):
        del truth_dir, catalog_cache
        if spec["candidate_id"] == "bad":
            return {
                "candidate_id": "bad",
                "mK": 3.0,
                "Sy": 0.1,
                "status": "failed",
                "objective": math.nan,
            }
        objective = 0.0 if spec["candidate_id"] == "best" else 1.5
        return {
            "candidate_id": spec["candidate_id"],
            "mK": float(spec["mK"]),
            "Sy": float(spec["Sy"]),
            "status": "completed",
            "objective": objective,
        }

    monkeypatch.setattr(module, "_score_one_spec", fake_score_one)

    frame = module.score_candidate_specs(specs, truth_dir=tmp_path)

    assert frame["candidate_id"].tolist() == ["best", "ok", "bad"]
    assert frame["rank"].tolist() == [1, 2, 3]
