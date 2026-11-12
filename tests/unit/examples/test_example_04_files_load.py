"""Every TOML of example 04 loads, and its calibration files pass the preflight."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.project.api import check

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


@pytest.mark.parametrize("name", CALIBRATIONS)
def test_each_calibration_passes_the_preflight(name: str) -> None:
    """What ``hmp check`` says of the file: a calibration with no error."""
    assert load_toml_with_base_config(EXAMPLE_04 / name, root=ROOT_CONFIG).get("calibration")
    errors = [item.line() for item in check(EXAMPLE_04 / name) if item.severity == "error"]
    assert not errors, errors
