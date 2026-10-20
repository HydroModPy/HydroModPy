"""The frozen document of a session reads the files its search read, and names its window.

``sessions/<case>/config.toml`` is the base of a promotion after the fact,
which has to hash the model the search hashed. A geometry path is anchored to
the file that declares it; read from two folders deeper, a bare filename found
nothing, stayed relative, and moved the hash of every trial. The window the
session scored its objective on closes an open bound with the declared period
and reads the last phase of a staged calibration.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.calibration.runners.session import freeze_session_config, objective_window_of
from hydromodpy.results.metric_rule import DateWindow

pytestmark = pytest.mark.unit

CASE = """\
[site]
name = "nancon"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"

[calibration]
method = "grid"
max_trials = 3

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
target = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "net.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def _case(tmp_path: Path, text: str = CASE) -> Path:
    project = tmp_path / "workspace" / "projects" / "nancon"
    project.mkdir(parents=True)
    hydrography = tmp_path / "workspace" / "data" / "hydrography"
    hydrography.mkdir(parents=True)
    (hydrography / "net.gpkg").write_bytes(b"gpkg")
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    path = project / "calage.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_frozen_document_finds_the_map_the_search_read(tmp_path) -> None:
    path = _case(tmp_path)
    cfg, raw = load_toml_calibration(path)
    session_dir = path.parent / "sessions" / "calage"
    session_dir.mkdir(parents=True)

    frozen = freeze_session_config(session_dir, raw, cfg)
    again, _ = load_toml_calibration(frozen)

    read = str(cfg.outputs["net"].stream_geometry_path)
    assert read == str((tmp_path / "workspace" / "data" / "hydrography" / "net.gpkg").resolve())
    assert str(again.outputs["net"].stream_geometry_path) == read
    assert str(tmp_path) not in frozen.read_text(encoding="utf-8")


def test_an_open_end_is_the_end_of_the_declared_period(tmp_path) -> None:
    path = _case(
        tmp_path,
        CASE.replace(
            "max_trials = 3\n", 'max_trials = 3\nscoring_window = { start = "2001-01-01" }\n'
        ),
    )
    cfg, raw = load_toml_calibration(path)

    assert objective_window_of(cfg, raw) == DateWindow(
        start=date(2001, 1, 1), end=date(2002, 12, 31)
    )


def test_no_window_is_the_whole_declared_period(tmp_path) -> None:
    cfg, raw = load_toml_calibration(_case(tmp_path))

    assert objective_window_of(cfg, raw) == DateWindow(
        start=date(2000, 1, 1), end=date(2002, 12, 31)
    )


def test_a_search_that_skips_samples_names_no_window(tmp_path) -> None:
    path = _case(
        tmp_path, CASE.replace("max_trials = 3\n", "max_trials = 3\nwarmup_periods = 12\n")
    )
    cfg, raw = load_toml_calibration(path)

    assert objective_window_of(cfg, raw) is None


def test_a_staged_calibration_names_the_window_of_its_last_phase(tmp_path) -> None:
    staged = CASE + (
        "\n[calibration.parameters.Sy]\n"
        "bounds = [0.01, 0.3]\n"
        'target = "flow.param.Sy.field.value"\n'
        "\n[[calibration.phases]]\n"
        'name = "steady_k"\n'
        'method = "bisection"\n'
        'parameters = ["K"]\n'
        'objective_blocks = ["network"]\n'
        "\n[[calibration.phases]]\n"
        'name = "transient_sy"\n'
        'method = "grid"\n'
        'parameters = ["Sy"]\n'
        'objective_blocks = ["network"]\n'
        'depends_on = "steady_k"\n'
        "\n[calibration.phases.scoring_window]\n"
        'start = "2001-06-01"\n'
    )
    cfg, raw = load_toml_calibration(_case(tmp_path, staged))

    assert objective_window_of(cfg, raw) == DateWindow(
        start=date(2001, 6, 1), end=date(2002, 12, 31)
    )
