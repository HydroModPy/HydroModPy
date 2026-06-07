"""Golden non-regression test for deterministic intermittency case outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.data.variables.intermittency.cases.run_intermittency_case import (
    run_intermittency_case_from_toml,
)

GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "run_intermittency_case_golden.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    raise RuntimeError("Cannot locate repository root from test path")


@pytest.mark.slow
def test_run_intermittency_case_golden(update_goldens: bool, tmp_path: Path) -> None:
    """Check intermittency-case summary stays stable on local deterministic input."""
    base_config_path = (
        _repo_root()
        / "hydromodpy"
        / "data"
        / "variables"
        / "intermittency"
        / "cases"
        / "run_intermittency_config.toml"
    )
    actual = run_intermittency_case_from_toml(
        base_config_path,
        output_json=tmp_path / "intermittency_case_summary.json",
    )

    sanitized_actual = json.loads(json.dumps(actual))

    if update_goldens:
        _write_json(GOLDEN_FILE, sanitized_actual)
        return

    if not GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE)
    assert sanitized_actual == expected
