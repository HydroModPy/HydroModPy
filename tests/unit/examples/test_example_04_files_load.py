"""Every TOML of example 04 loads, and its calibration files pass the preflight."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.config import HydroModPyConfig

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
    assert len(cfg.export) == 11


@pytest.mark.parametrize("name", CALIBRATIONS)
def test_each_calibration_passes_the_preflight(name: str, capsys) -> None:
    code = calibrate_cmd.run(
        argparse.Namespace(
            config=EXAMPLE_04 / name,
            check=True,
            list_phases=False,
            expand=False,
            phase=None,
            profile=None,
        )
    )
    assert code in (None, 0)
    captured = capsys.readouterr()
    assert f"{name}: ready to run." in captured.out + captured.err
