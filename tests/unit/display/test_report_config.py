from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.display.report_config import ReportConfig

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_html_report_build_at_end_implies_enabled() -> None:
    cfg = ReportConfig.model_validate(
        {"html": {"build_at_end": True, "profile": "catchment_gauged"}}
    )

    assert cfg.html.enabled is True
    assert cfg.html.build_at_end is True
    assert cfg.html.profile == "catchment_gauged"
    assert cfg.html.config_path is None
    assert cfg.html.strict is False


def test_html_report_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="profile"):
        ReportConfig.model_validate({"html": {"profile": "unknown"}})


def test_hydromodpy_config_accepts_report_section(tmp_path: Path) -> None:
    report_config = tmp_path / "catchment_report.toml"
    cfg = HydroModPyConfig.from_dict(
        {
            "workflow": {"mode": "simulation"},
            "geographic": {"source_mode": "synthetic"},
            "report": {
                "html": {
                    "build_at_end": True,
                    "profile": "catchment_gauged",
                    "config_path": str(report_config),
                }
            },
        },
        base_dir=tmp_path,
    )

    assert cfg.report.html.enabled is True
    assert cfg.report.html.build_at_end is True
    assert cfg.report.html.config_path == report_config
    assert cfg.report.html.strict is False


def test_hydromodpy_config_resolves_report_config_path_from_toml(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    report_config = tmp_path / "reports" / "catchment_report.toml"
    config_path = tmp_path / "run.toml"
    config_path.write_text(
        f"""
[workflow]
mode = "simulation"

[workspace]
project_root = "{project_root.as_posix()}"

[geographic]
source_mode = "synthetic"

[report.html]
build_at_end = true
profile = "catchment_gauged"
config_path = "reports/catchment_report.toml"
""".lstrip(),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.report.html.config_path == report_config


def test_nancon_html_report_overlay_loads() -> None:
    config_path = (
        REPO_ROOT
        / "examples"
        / "projects"
        / "02_nancon_watershed"
        / "run_transient_nwt_html_report.toml"
    )

    cfg = HydroModPyConfig.from_toml(config_path)

    assert cfg.simulation.name == "transient_nwt_html_report"
    assert cfg.report.html.enabled is True
    assert cfg.report.html.build_at_end is True
    assert cfg.report.html.profile == "catchment_gauged"
    assert cfg.report.html.strict is False
    assert cfg.report.html.config_path == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "16_nancon_natural_calibration"
        / "catchment_report_transient_nwt_html.toml"
    )
