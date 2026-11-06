"""``hmp calibrate --expand`` prints the phases a protocol writes.

A protocol is a name a file can carry instead of the phases and objective
blocks it stands for. ``--expand`` prints those phases and blocks as TOML, so
a reader can see what would run without running it, and paste the result into
a hand-written file that deviates from the protocol on purpose."""

from __future__ import annotations

import argparse
import textwrap
import tomllib
from pathlib import Path

import pytest

from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.cli.helpers import EXIT_USAGE

_PROTOCOL = textwrap.dedent(
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


_NO_PROTOCOL = textwrap.dedent(
    """
    [calibration]
    seed = 7
    """
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text(content, encoding="utf-8")
    return path


def _run(path: Path, **overrides) -> None:
    fields = {
        "config": path,
        "list_phases": False,
        "phase": None,
        "expand": False,
        "resume": False,
        "dry_run": False,
    }
    fields.update(overrides)
    calibrate_cmd.run(argparse.Namespace(**fields))


def test_expand_prints_the_header_and_the_written_sections(tmp_path, capsys) -> None:
    path = _write(tmp_path, _PROTOCOL)

    _run(path, expand=True)

    printed = capsys.readouterr().out
    assert "# Expanded from protocol matching_hydrographic_network, version 1.3" in printed
    assert "Abherve et al. 2023, 10.5194/hess-27-3221-2023" in printed
    assert "[calibration.parameters.K]" in printed
    assert "[calibration.outputs.streams]" in printed
    assert "[[calibration.objective_blocks]]" in printed
    assert "[[calibration.phases]]" in printed


def test_the_protocol_delete_hint_is_only_for_an_inherited_protocol(tmp_path, capsys) -> None:
    """A file that names the protocol itself has nothing inherited to drop."""
    own = _write(tmp_path, _PROTOCOL)
    _run(own, expand=True)
    assert "protocol__delete" not in capsys.readouterr().out

    (tmp_path / "project.toml").write_text(_PROTOCOL, encoding="utf-8")
    child = tmp_path / "run_calibration.toml"
    child.write_text('base_config = "project.toml"\n', encoding="utf-8")
    _run(child, expand=True)
    assert "# protocol__delete = true" in capsys.readouterr().out


def test_expand_on_a_file_without_a_protocol_says_so(tmp_path, capsys) -> None:
    path = _write(tmp_path, _NO_PROTOCOL)

    _run(path, expand=True)

    printed = capsys.readouterr().out
    assert "declares no protocol" in printed
    assert "seed = 7" in printed


def test_expand_prints_pasteable_toml(tmp_path, capsys) -> None:
    """The body, comments aside, parses back to the whole section, protocol aside."""
    path = _write(tmp_path, _PROTOCOL)

    _run(path, expand=True)

    printed = capsys.readouterr().out
    body = "\n".join(line for line in printed.splitlines() if not line.startswith("#"))
    parsed = tomllib.loads(body)

    assert [phase["name"] for phase in parsed["calibration"]["phases"]] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert parsed["calibration"]["objective_blocks"][0]["name"] == "network_extension"
    assert set(parsed["calibration"]["parameters"]) == {"K", "Sy"}
    assert "protocol" not in parsed["calibration"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"resume": True},
        {"dry_run": True},
        {"list_phases": True},
        {"phase": "steady_conductivity"},
    ],
)
def test_expand_refuses_other_flags(tmp_path, capsys, overrides) -> None:
    path = _write(tmp_path, _PROTOCOL)

    with pytest.raises(SystemExit) as caught:
        _run(path, expand=True, **overrides)

    assert caught.value.code == EXIT_USAGE
    assert "--expand" in capsys.readouterr().err


pytestmark = pytest.mark.fast


EXAMPLE_04 = Path("examples/projects/04_streamflow_intermittence_in_transient")


# Relative to the repository root, where pytest runs from: the CLI shortens
# the network output's absolute, resolved source to this when it sits under
# the working directory.
GEOMETRY = "examples/data/hydrography/nancon_stream_network.gpkg"


def _list_phases(path: Path, capsys) -> str:
    calibrate_cmd.run(
        argparse.Namespace(
            config=path, check=False, list_phases=True, expand=False, phase=None, profile=None
        )
    )
    return capsys.readouterr().out


def test_the_protocol_file_shows_a_network_row_and_a_hydrograph_block_row(capsys) -> None:
    out = _list_phases(EXAMPLE_04 / "run_calibration.toml", capsys)

    lines = out.splitlines()
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


def test_the_composite_file_shows_one_phase_with_two_shares(capsys) -> None:
    out = _list_phases(EXAMPLE_04 / "run_calibration_composite.toml", capsys)

    lines = out.splitlines()
    assert lines[0].startswith("0\tconductivity_and_storage\toptuna\t")
    # A share table {hydrograph = 0.7, network = 0.3}, the network gap normalized.
    assert lines[1] == (
        f"    network\tdistance_mean\tshare 30%\trelease_flux (network)\tvs {GEOMETRY}"
    )
    assert lines[2] == (
        "    hydrograph\tnse_log\tshare 70%\tdischarge, station NANCON (whole-catchment "
        "series)\tvs station NANCON ([data.hydrometry])"
    )
    # The file writes only the start: the end comes from the project's [metrics] window.
    assert lines[3] == "    scores on: window 2001-01-01 to 2002-12-31"
    assert len(lines) == 4


def test_the_protocol_written_by_hand_lists_what_the_protocol_lists(capsys) -> None:
    protocol = _list_phases(EXAMPLE_04 / "run_calibration.toml", capsys)
    by_hand = _list_phases(EXAMPLE_04 / "run_calibration_by_hand.toml", capsys)

    assert by_hand == protocol
