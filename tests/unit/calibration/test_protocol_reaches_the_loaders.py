"""Naming a protocol has to change the run, not just the file.

The expansion is written on the whole document, so it has to happen where the
document is read. Both routes read one: the project loader and the calibration
CLI. A protocol that reached neither would validate, persist, and calibrate
nothing at all.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.protocols import protocol_record
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration

_TOML = textwrap.dedent(
    """
    [workspace]
    name = "protocol_probe"

    [simulation.time]
    start_datetime = "2000-01-01"
    end_datetime = "2000-12-31"
    step_value = 1
    step_unit = "day"

    [calibration]
    protocol = "matching_hydrographic_network"

    [calibration.parameters.K]
    bounds = [1e-8, 1e-2]
    transform = "log"
    units = "m/s"

    [calibration.parameters.Sy]
    bounds = [1e-4, 0.5]
    transform = "log"
    units = "-"

    [calibration.outputs.seepage_network]
    support = "network"
    stream_geometry_path = "network.gpkg"
    """
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "protocol.toml"
    path.write_text(_TOML, encoding="utf-8")
    (tmp_path / "network.gpkg").write_bytes(b"")
    return path


def test_the_cli_loader_runs_the_protocol(project: Path) -> None:
    cfg, _raw = load_toml_calibration(project)

    assert cfg.phases is not None
    assert [phase.name for phase in cfg.phases] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert cfg.objective_blocks[0].metric == "distance_gap"


def test_the_loaded_config_still_says_which_protocol_it_ran(project: Path) -> None:
    cfg, _raw = load_toml_calibration(project)

    assert cfg.protocol is not None
    assert cfg.protocol.name == "matching_hydrographic_network"


def test_a_protocol_that_nothing_expanded_is_refused_rather_than_ignored() -> None:
    """Validating [calibration] alone cannot see the window the stages need."""
    with pytest.raises(ValueError, match="protocol"):
        CalibrationConfig.model_validate(
            {
                "protocol": "matching_hydrographic_network",
                "parameters": {"K": {"bounds": [1e-8, 1e-2], "transform": "log"}},
            }
        )


def test_one_stage_of_a_protocol_is_an_ordinary_calibration(project: Path) -> None:
    """A phase no longer declares the method that wrote it, and must not be refused."""
    from hydromodpy.calibration.runners.staged_runner import _phase_config

    cfg, _raw = load_toml_calibration(project)
    assert cfg.phases is not None

    phase_config = _phase_config(cfg, cfg.phases[0])

    assert phase_config.protocol is None
    assert phase_config.phases is None
    assert list(phase_config.parameters) == ["K"]


def test_the_run_records_what_the_protocol_rests_on(project: Path) -> None:
    """A calibrated value that came out of a published method has to say so."""
    from hydromodpy.calibration.protocols import get_protocol

    cfg, _raw = load_toml_calibration(project)
    assert cfg.protocol is not None

    protocol = get_protocol(cfg.protocol.name)
    record = protocol_record(cfg.protocol.name)

    assert record["name"] == protocol.name
    assert record["title"] == protocol.title
    assert record["references"][0].startswith("Abherve")
    assert "10.5194/hess-27-3221-2023" in record["references"][0]


def test_the_staged_report_carries_the_protocol_it_followed() -> None:
    from hydromodpy.calibration.protocols import protocol_record
    from hydromodpy.calibration.runners.staged_runner import StagedCalibrationReport

    report = StagedCalibrationReport(
        phases=(),
        frozen=(),
        root_session_id="abc",
        protocol=protocol_record("matching_hydrographic_network"),
    )

    summary = report.to_dict()
    assert summary["protocol"]["name"] == "matching_hydrographic_network"
    assert summary["protocol"]["references"]


def test_a_hand_written_staged_report_says_nothing_about_a_protocol() -> None:
    from hydromodpy.calibration.runners.staged_runner import StagedCalibrationReport

    summary = StagedCalibrationReport(phases=(), frozen=(), root_session_id="abc").to_dict()

    assert "protocol" not in summary
