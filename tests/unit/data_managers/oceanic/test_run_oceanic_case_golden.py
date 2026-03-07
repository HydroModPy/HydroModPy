"""Golden non-regression test for deterministic oceanic case outputs."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

import pytest

from hydromodpy.data_managers.oceanic.cases.run_oceanic_case import run_oceanic_case_from_toml


GOLDEN_FILE = Path(__file__).resolve().parent / "golden" / "run_oceanic_case_golden.json"


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    raise RuntimeError("Cannot locate repository root from test path")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _dump_toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_dump_toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value type: {type(value)}")


def _render_toml(payload: dict) -> str:
    lines: list[str] = []
    for section in ("oceanic_case", "geographic"):
        lines.append(f"[{section}]")
        for key, value in payload[section].items():
            lines.append(f"{key} = {_dump_toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_full_extraction_test_config(base_config_path: Path, tmp_path: Path) -> Path:
    with base_config_path.open("rb") as stream:
        payload = tomllib.load(stream)

    case_cfg = dict(payload.get("oceanic_case", {}))
    geo_cfg = dict(payload.get("geographic", {}))
    config_dir = base_config_path.parent

    oceanic_path = (config_dir / str(case_cfg["oceanic_path"])).resolve()
    local_csv_path = (config_dir / str(case_cfg["local_csv_path"])).resolve()
    out_path = (tmp_path / "outputs").resolve()
    stable_folder = (out_path / "stable").resolve()

    case_cfg["source"] = "local"
    case_cfg["run_local_extraction"] = True
    case_cfg["display_values"] = ["RSL", "RMSL"]
    case_cfg["oceanic_path"] = str(oceanic_path)
    case_cfg["local_csv_path"] = str(local_csv_path)
    case_cfg["out_path"] = str(out_path)
    geo_cfg["stable_folder"] = str(stable_folder)

    tmp_config_path = tmp_path / "run_oceanic_config_full.toml"
    tmp_config_path.write_text(
        _render_toml(
            {
                "oceanic_case": case_cfg,
                "geographic": geo_cfg,
            }
        ),
        encoding="utf-8",
    )
    return tmp_config_path


def _sanitize_for_golden(summary: dict) -> dict:
    sanitized = dict(summary)
    sanitized.pop("local_extraction_seconds", None)
    sanitized.pop("fetch_msl_seconds", None)
    return sanitized


@pytest.mark.slow
def test_run_oceanic_case_golden(update_goldens: bool, tmp_path: Path) -> None:
    """Check extended oceanic-case summary stays stable on local deterministic input."""
    base_config_path = (
        _repo_root()
        / "hydromodpy"
        / "data_managers"
        / "oceanic"
        / "cases"
        / "run_oceanic_config.toml"
    )
    config_path = _build_full_extraction_test_config(base_config_path, tmp_path)
    actual = run_oceanic_case_from_toml(
        config_path,
        output_json=tmp_path / "oceanic_case_summary.json",
    )
    assert actual.get("run_local_extraction") is True
    assert float(actual.get("local_extraction_seconds", 0.0)) > 0.0
    assert float(actual.get("fetch_msl_seconds", 0.0)) >= 0.0

    figures_root = tmp_path / "outputs" / "results_stable" / "_figures" / "oceanic"
    required_figures = [
        figures_root / "RSLplot.png",
        figures_root / "RMSLplot.png",
    ]
    for figure_path in required_figures:
        assert figure_path.exists(), f"Missing expected oceanic figure: {figure_path}"
        assert figure_path.stat().st_size > 0, f"Empty oceanic figure: {figure_path}"

    sanitized_actual = _sanitize_for_golden(actual)

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
