"""``hmp calibrate``: the command that runs, lists or expands the phases of a calibration file.

A protocol is a name a file can carry instead of the phases and objective blocks it stands for.
``--expand`` prints those phases as TOML without running them, ``--list-phases`` prints one row per
phase. ``--set``, ``--overlay`` and ``--case`` vary a file without a copy, as ``hmp run`` does.
Exit codes are typed: 10 file not found, 14 config, 21 calibration, 2 usage.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_USAGE
from hydromodpy.core.exceptions import CalibrationError, ConfigError
from hydromodpy.core.runtime.bounds import Bounds
from tests._helpers.cli_runner import CliRunner

from ._hmp import run_main as _run

pytestmark = pytest.mark.fast

EXAMPLE_04 = Path("examples/projects/04_streamflow_intermittence_in_transient")

# Relative to the repository root, where pytest runs from: the CLI shortens the network output's
# absolute, resolved source to this when it sits under the working directory.
GEOMETRY = "examples/data/hydrography/nancon_stream_network.gpkg"

MODE_CALIBRATION = '[workflow]\nmode = "calibration"\n'

PROTOCOL = textwrap.dedent(
    """
    [calibration]
    protocol = "matching_hydrographic_network"

    [calibration.parameters.K]

    [calibration.parameters.Sy]

    [calibration.outputs.streams]
    support = "network"
    map.complete = "streams.gpkg"

    [[data.hydrometry.sources]]
    station_ids = ["G1"]
    """
)

NO_PROTOCOL = "[calibration]\nseed = 7\n"

SEED_CALIBRATION = """\
[calibration]
seed = 3
save_runs = "best_n"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"
"""

# Flags that --expand cannot be combined with.
EXPAND_REFUSES = [
    pytest.param({"resume": True}, id="resume"),
    pytest.param({"dry_run": True}, id="dry run"),
    pytest.param({"list_phases": True}, id="list phases"),
    pytest.param({"phase": "steady_conductivity"}, id="phase"),
]

# A failure of the API call, the extra flags and the exit code the command maps it to.
API_REFUSALS = [
    pytest.param(
        CalibrationError("residual keeps a constant sign over the bracket"),
        [],
        21,
        "residual keeps a constant sign",
        id="calibration refusal",
    ),
    pytest.param(
        ConfigError("calib.toml: 1 validation error for CalibrationConfig"),
        ["--list-phases"],
        14,
        "validation error",
        id="unreadable config on list phases",
    ),
]


def write_file(tmp_path: Path, text: str, name: str = "calib.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def report(**fields: object) -> CalibrationReport:
    """A real report: the command prints and serializes what the class holds."""
    base = dict(
        session_id="s",
        method="optuna",
        n_trials=1,
        best_cost=None,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
    )
    return CalibrationReport(**{**base, **fields})


def run_command(path: Path, **overrides) -> None:
    """Call the command module with the namespace argparse would build."""
    fields = {
        "config": path,
        "check": False,
        "list_phases": False,
        "phase": None,
        "expand": False,
        "resume": False,
        "dry_run": False,
        "profile": None,
    }
    calibrate_cmd.run(argparse.Namespace(**{**fields, **overrides}))


def printed_phases(path: Path, capsys) -> str:
    run_command(path, list_phases=True)
    return capsys.readouterr().out


def leftovers(tmp_path: Path) -> list[str]:
    return sorted(path.name for path in tmp_path.iterdir() if ".effective." in path.name)


def test_a_missing_file_exits_not_found(monkeypatch) -> None:
    assert _run(monkeypatch, ["hmp", "calibrate", "/nonexistent/calib.toml"]) == 10


def test_a_wrong_extension_is_a_config_error(monkeypatch, tmp_path) -> None:
    bad = write_file(tmp_path, "<?xml version='1.0'?>\n", name="calib.xml")

    assert _run(monkeypatch, ["hmp", "calibrate", str(bad)]) == 14


@pytest.mark.parametrize(("error", "flags", "code", "message"), API_REFUSALS)
def test_api_refusals(monkeypatch, tmp_path, capsys, error, flags, code, message) -> None:
    config = write_file(tmp_path, MODE_CALIBRATION)

    def fake_calibrate(path: Path, **kwargs):
        raise error

    monkeypatch.setattr("hydromodpy.project.api.calibrate", fake_calibrate)

    assert _run(monkeypatch, ["hmp", "calibrate", str(config), *flags]) == code
    assert message in capsys.readouterr().err


def test_success_forwards_the_resolved_path_and_prints_the_summary(
    monkeypatch, tmp_path, capsys
) -> None:
    config = write_file(tmp_path, MODE_CALIBRATION)
    captured: dict[str, object] = {}

    def fake_calibrate(path: Path, *, phase=None, **kwargs):
        captured.update(path=path, phase=phase, kwargs=kwargs)
        return report(best_parameters={"K": 2.1e-4}, best_cost=0.25)

    monkeypatch.setattr("hydromodpy.project.api.calibrate", fake_calibrate)

    code = _run(monkeypatch, ["hmp", "calibrate", str(config)])

    assert code == 0
    assert captured["path"] == config.resolve()
    assert captured["phase"] is None
    environment = captured["kwargs"].pop("environment")
    assert captured["kwargs"] == {"resume": False}
    assert environment.bounds == Bounds()
    err = capsys.readouterr().err
    assert "Calibration finished: calib.toml" in err
    assert "K = 0.00021" in err
    assert "cost: 0.25" in err


def test_no_report_tells_the_api_to_skip_the_session_report(monkeypatch, tmp_path) -> None:
    config = write_file(tmp_path, MODE_CALIBRATION)
    captured: dict[str, object] = {}

    def fake_calibrate(path: Path, *, phase=None, **kwargs):
        captured.update(kwargs)
        return report()

    monkeypatch.setattr("hydromodpy.project.api.calibrate", fake_calibrate)

    assert _run(monkeypatch, ["hmp", "calibrate", str(config), "--no-report"]) == 0
    assert captured["report"] is False


def test_list_phases_runs_no_search(monkeypatch, tmp_path, capsys) -> None:
    config = write_file(tmp_path, MODE_CALIBRATION)
    calls: list[Path] = []

    def fake_calibrate(path: Path, **kwargs):
        assert kwargs["dry_run"] is True, "listing the phases runs no search"
        calls.append(path)
        phase = {
            "name": "steady_k_over_r",
            "description": "zero of the signed gap",
            "method": "bisection",
            "parameters": ["K"],
        }
        plan = {"phases": [phase], "calibration": {}, "protocol": None, "plan": {}}
        return SimpleNamespace(to_dict=lambda: plan)

    monkeypatch.setattr("hydromodpy.project.api.calibrate", fake_calibrate)

    assert _run(monkeypatch, ["hmp", "calibrate", str(config), "--list-phases"]) == 0
    assert calls == [config.resolve()]
    assert "steady_k_over_r" in capsys.readouterr().out


def test_the_protocol_file_lists_a_network_row_and_a_hydrograph_block_row(capsys) -> None:
    lines = printed_phases(EXAMPLE_04 / "run_calibration.toml", capsys).splitlines()

    assert lines[0].startswith("0\tsteady_conductivity\tbisection\t")
    assert lines[1] == (
        f"    network_extension\tdistance_gap\tshare 100%\trelease_flux (network)\tvs {GEOMETRY}"
    )
    assert lines[2] == "    scores on: no window, all of the run"
    assert lines[3].startswith("1\ttransient_storage\tscipy_nelder_mead\t")
    assert lines[4] == (
        "    hydrograph\tnse_log\tshare 100%\tdischarge, station NANCON (whole-catchment "
        "series)\tvs station NANCON ([data.hydrometry])"
    )
    assert lines[5] == "    scores on: window 2001-01-01 to 2002-12-31"
    assert len(lines) == 6


def test_the_protocol_written_by_hand_lists_what_the_protocol_lists(capsys) -> None:
    protocol = printed_phases(EXAMPLE_04 / "run_calibration.toml", capsys)
    by_hand = printed_phases(EXAMPLE_04 / "run_calibration_by_hand.toml", capsys)

    assert by_hand == protocol


def test_expand_prints_the_header_and_the_written_sections(tmp_path, capsys) -> None:
    run_command(write_file(tmp_path, PROTOCOL), expand=True)

    printed = capsys.readouterr().out
    assert "# Expanded from protocol matching_hydrographic_network, version 1.3" in printed
    assert "Abherve et al. 2023, 10.5194/hess-27-3221-2023" in printed
    assert "[calibration.parameters.K]" in printed
    assert "[calibration.outputs.streams]" in printed
    assert "[[calibration.objective_blocks]]" in printed
    assert "[[calibration.phases]]" in printed


def test_the_protocol_delete_hint_is_only_for_an_inherited_protocol(tmp_path, capsys) -> None:
    # A file that names the protocol itself has nothing inherited to drop.
    run_command(write_file(tmp_path, PROTOCOL), expand=True)
    assert "protocol__delete" not in capsys.readouterr().out

    write_file(tmp_path, PROTOCOL, name="project.toml")
    child = write_file(tmp_path, 'base_config = "project.toml"\n', name="run_calibration.toml")
    run_command(child, expand=True)
    assert "# protocol__delete = true" in capsys.readouterr().out


def test_expand_of_a_file_without_a_protocol_says_so(tmp_path, capsys) -> None:
    run_command(write_file(tmp_path, NO_PROTOCOL), expand=True)

    printed = capsys.readouterr().out
    assert "declares no protocol" in printed
    assert "seed = 7" in printed


@pytest.mark.parametrize("overrides", EXPAND_REFUSES)
def test_expand_refuses_other_flags(tmp_path, capsys, overrides) -> None:
    path = write_file(tmp_path, PROTOCOL)

    with pytest.raises(SystemExit) as caught:
        run_command(path, expand=True, **overrides)

    assert caught.value.code == EXIT_USAGE
    assert "--expand" in capsys.readouterr().err


def test_set_changes_what_the_calibration_would_do(tmp_path: Path) -> None:
    config = write_file(tmp_path, SEED_CALIBRATION, name="cal.toml")

    plain = CliRunner().invoke(["calibrate", str(config), "--dry-run"])
    varied = CliRunner().invoke(
        ["calibrate", str(config), "--dry-run", "--set", 'calibration.save_runs="all"']
    )

    assert "save_runs = best_n" in plain.stderr
    assert "save_runs = all" in varied.stderr
    assert "case: cal\n" in varied.stderr
    assert leftovers(tmp_path) == []


def test_set_reaches_the_section_expand_prints(tmp_path: Path) -> None:
    config = write_file(tmp_path, SEED_CALIBRATION, name="cal.toml")

    result = CliRunner().invoke(
        ["calibrate", str(config), "--expand", "--set", "calibration.seed=5"]
    )

    assert result.exit_code == 0
    assert "seed = 5" in result.stdout
    assert "cal.toml declares no protocol" in result.stdout


def test_case_names_the_session(tmp_path: Path) -> None:
    config = write_file(tmp_path, SEED_CALIBRATION, name="cal.toml")

    result = CliRunner().invoke(["calibrate", str(config), "--dry-run", "--case", "x"])

    assert result.exit_code == 0
    assert "case: x\n" in result.stderr
    assert "session: sessions/x" in result.stderr
    assert "calibrated run: runs/x " in result.stderr
    assert leftovers(tmp_path) == []


def test_a_malformed_override_is_a_config_error(tmp_path: Path) -> None:
    config = write_file(tmp_path, SEED_CALIBRATION, name="cal.toml")

    result = CliRunner().invoke(["calibrate", str(config), "--set", "oops"])

    assert result.exit_code == EXIT_CONFIG
    assert "Invalid override" in result.stderr
    assert leftovers(tmp_path) == []
