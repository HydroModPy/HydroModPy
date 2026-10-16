"""Every TOML of example 04 loads, and its calibration files pass the preflight."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.sites.check import check_project
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

pytestmark = pytest.mark.fast

EXAMPLE_04 = Path(__file__).resolve().parents[3] / (
    "examples/projects/04_streamflow_intermittence_in_transient"
)
FILES = sorted(path.name for path in EXAMPLE_04.glob("*.toml"))
CALIBRATIONS = (
    "run_calibration.toml",
    "run_calibration_api_daily.toml",
    "run_calibration_bdtopage.toml",
    "run_calibration_by_hand.toml",
    "run_calibration_composite.toml",
)


def test_the_example_ships_the_expected_files() -> None:
    steps = [name for name in FILES if name.startswith("step")]
    assert steps == [
        "step1_minimal.toml",
        "step2_local_data.toml",
        "step3_api_data.toml",
        "step4_transient.toml",
        "step5_export.toml",
        "step6_soil_reservoir.toml",
    ]
    assert set(CALIBRATIONS) <= set(FILES)
    assert "run_calibration_protocol_by_hand.toml" not in FILES


@pytest.mark.parametrize("name", FILES)
def test_each_file_loads(name: str) -> None:
    HydroModPyConfig.from_toml(EXAMPLE_04 / name)


def test_the_project_carries_no_calibration() -> None:
    calibration = HydroModPyConfig.from_toml(EXAMPLE_04 / "project.toml").calibration
    assert calibration is None or (not calibration.phases and calibration.protocol is None)


def test_the_export_step_writes_one_request_per_kind() -> None:
    cfg = HydroModPyConfig.from_toml(EXAMPLE_04 / "step5_export.toml")
    assert len(cfg.export) == 10


@pytest.mark.parametrize("name", FILES)
def test_each_file_draws_figures_and_writes_exports(name: str) -> None:
    cfg = HydroModPyConfig.from_toml(EXAMPLE_04 / name)
    assert cfg.display.figures
    assert cfg.export


@pytest.mark.parametrize("name", CALIBRATIONS)
def test_each_calibration_passes_the_preflight(name: str) -> None:
    """What ``hmp config check`` says of the file: a calibration with no error."""
    report = check_project(EXAMPLE_04 / name)
    assert report.kind == "calibration"
    assert report.ok, report.errors


def test_the_project_names_its_catchment_and_its_window_once() -> None:
    """[site] carries the gauge, [metrics] the window; no station is written twice."""
    raw = load_toml_with_base_config(EXAMPLE_04 / "project.toml")
    assert "workspace" not in raw
    for variable in ("hydrometry", "recharge", "runoff"):
        assert "station_ids" not in raw["data"][variable]["sources"][0]

    cfg = HydroModPyConfig.from_toml(EXAMPLE_04 / "project.toml")
    assert cfg.site is not None and cfg.site.name == "nancon"
    assert cfg.site.gauge == "NANCON"
    assert cfg.metrics is not None and cfg.metrics.window is not None
    assert (str(cfg.metrics.window.start), str(cfg.metrics.window.end)) == (
        "2001-01-01",
        "2002-12-31",
    )
    for variable in ("hydrometry", "recharge", "runoff"):
        assert getattr(cfg.data, variable).sources[0].station_ids == ["NANCON"]


@pytest.mark.parametrize("name", FILES)
def test_no_file_writes_a_retired_key(name: str) -> None:
    raw = load_toml_with_base_config(EXAMPLE_04 / name)
    assert "workspace" not in raw
    assert raw.get("simulation", {}).get("if_exists") != "replace"
    assert "rerun_best_with_outputs" not in raw.get("calibration", {})
