"""Every TOML of example 04 loads, and the calibration files of the Nancon fixture pass the preflight."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.project.api import check

pytestmark = pytest.mark.fast

TESTS = Path(__file__).resolve().parents[2]
EXAMPLE_04 = TESTS.parent / "examples/projects/04_streamflow_intermittence_in_transient"
NANCON = TESTS / "fixtures/projects/nancon_intermittence"
FILES = sorted(path.name for path in EXAMPLE_04.glob("*.toml"))
CALIBRATIONS = sorted(path.name for path in NANCON.glob("run_calibration*.toml"))


def test_the_example_ships_its_project_file() -> None:
    assert "project.toml" in FILES


@pytest.mark.parametrize("name", FILES)
def test_each_example_file_loads(name: str) -> None:
    assert load_toml_with_base_config(EXAMPLE_04 / name, root=ROOT_CONFIG)


def test_the_fixture_holds_the_five_calibration_files() -> None:
    assert CALIBRATIONS == [
        "run_calibration.toml",
        "run_calibration_api_daily.toml",
        "run_calibration_bdtopage.toml",
        "run_calibration_by_hand.toml",
        "run_calibration_composite.toml",
    ]


@pytest.mark.parametrize("name", CALIBRATIONS)
def test_each_calibration_passes_the_preflight(name: str) -> None:
    """What ``hmp check`` says of the file: a calibration with no error."""
    assert load_toml_with_base_config(NANCON / name, root=ROOT_CONFIG).get("calibration")
    errors = [item.line() for item in check(NANCON / name) if item.severity == "error"]
    assert not errors, errors
