from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from hydromodpy.display.catchment_report.artifacts import artifact_candidate, artifact_spec
from hydromodpy.display.catchment_report.postflight import (
    CatchmentReportPostflightError,
    write_figure_postflight_report,
)
from hydromodpy.display.catchment_report.presets import CatchmentReportPreset


@dataclass(frozen=True)
class _Config:
    output_dir: Path
    preset: CatchmentReportPreset
    artifact_specs: tuple | None = None


def _write_manifest(output_dir: Path, copied: dict[str, Path]) -> None:
    payload = {
        "expected_figure_ids": ["alpha", "beta"],
        "copied_figures": {key: str(path) for key, path in copied.items()},
    }
    output_dir.mkdir(parents=True)
    (output_dir / "block_report_manifest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _config(output_dir: Path) -> _Config:
    preset = CatchmentReportPreset(
        name="test",
        artifact_specs=(
            artifact_spec("alpha", artifact_candidate("context_assets", "alpha.png")),
            artifact_spec("beta", artifact_candidate("context_assets", "beta.png")),
        ),
        block_specs=(),
    )
    return _Config(output_dir=output_dir, preset=preset)


def test_postflight_report_lists_present_and_missing_figures(tmp_path) -> None:
    alpha = tmp_path / "alpha.png"
    alpha.write_text("png", encoding="utf-8")
    _write_manifest(tmp_path / "report", {"alpha": alpha})

    postflight_path = write_figure_postflight_report(_config(tmp_path / "report"), strict=False)

    payload = json.loads(postflight_path.read_text(encoding="utf-8"))
    assert payload["expected_count"] == 2
    assert payload["present_figures"] == ["alpha"]
    assert payload["missing_figures"] == ["beta"]
    assert payload["missing_count"] == 1
    assert payload["dangling_count"] == 0


def test_strict_postflight_fails_on_missing_figures(tmp_path) -> None:
    _write_manifest(tmp_path / "report", {})

    with pytest.raises(CatchmentReportPostflightError) as exc_info:
        write_figure_postflight_report(_config(tmp_path / "report"), strict=True)

    assert "alpha" in str(exc_info.value)
    assert "beta" in str(exc_info.value)
    assert (tmp_path / "report" / "block_report_postflight.json").exists()


def test_postflight_reports_dangling_copied_paths(tmp_path) -> None:
    missing_path = tmp_path / "missing.png"
    _write_manifest(tmp_path / "report", {"alpha": missing_path, "beta": missing_path})

    postflight_path = write_figure_postflight_report(_config(tmp_path / "report"), strict=False)

    payload = json.loads(postflight_path.read_text(encoding="utf-8"))
    assert payload["missing_figures"] == []
    assert payload["dangling_figures"] == ["alpha", "beta"]
    assert payload["dangling_count"] == 2
