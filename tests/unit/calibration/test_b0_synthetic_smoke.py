from __future__ import annotations

import importlib.util
import math
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "12_calibration_network_transient_b0"
    / "run_synthetic_smoke.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("b0_synthetic_smoke", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_synthetic_smoke_ranks_truth_candidate_first(tmp_path) -> None:
    module = _load_script_module()

    frame = module.run_synthetic_smoke(
        tmp_path,
        mK_values=[0.75, 1.0, 1.25],
        Sy_values=[0.03, 0.05, 0.08],
    )

    best = frame.iloc[0]
    assert best["mK"] == 1.0
    assert best["Sy"] == 0.05
    assert best["rank"] == 1
    assert math.isclose(float(best["objective"]), 0.0, abs_tol=1e-12)
    assert (tmp_path / "truth" / "normalization.json").exists()
    assert (tmp_path / "candidate_scores.csv").exists()
    assert (tmp_path / "summary.json").exists()


def test_synthetic_smoke_cli_writes_outputs(tmp_path, capsys) -> None:
    module = _load_script_module()

    exit_code = module.main(
        [
            "--output-dir",
            str(tmp_path),
            "--mK-values",
            "1.0,1.5",
            "--Sy-values",
            "0.05,0.12",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "best=mK_1__Sy_0.05" in captured.out
    assert (tmp_path / "candidate_scores.json").exists()
