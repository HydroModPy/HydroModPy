"""``hmp calibrate --expand`` prints the phases a protocol writes.

A protocol is a name a file can carry instead of the phases and objective
blocks it stands for. ``--expand`` prints those phases and blocks as TOML, so
a reader can see what would run without running it, and paste the result into
a hand-written file that deviates from the protocol on purpose.
"""

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
    stream_geometry_path = "streams.gpkg"
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
    fields = {"config": path, "check": False, "list_phases": False, "phase": None, "expand": False}
    fields.update(overrides)
    calibrate_cmd.run(argparse.Namespace(**fields))


def test_expand_prints_the_header_and_the_written_sections(tmp_path, capsys) -> None:
    path = _write(tmp_path, _PROTOCOL)

    _run(path, expand=True)

    printed = capsys.readouterr().out
    assert "# Expanded from protocol matching_hydrographic_network, version 1.0" in printed
    assert "Abherve et al. 2023, 10.5194/hess-27-3221-2023" in printed
    assert "protocol__delete = true" in printed
    assert "[[calibration.objective_blocks]]" in printed
    assert "[[calibration.phases]]" in printed


def test_expand_on_a_file_without_a_protocol_says_so(tmp_path, capsys) -> None:
    path = _write(tmp_path, _NO_PROTOCOL)

    _run(path, expand=True)

    printed = capsys.readouterr().out
    assert "declares no protocol" in printed
    assert "seed = 7" in printed


def test_expand_prints_pasteable_toml(tmp_path, capsys) -> None:
    """The body, comments aside, parses back to the same phases and blocks."""
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
    assert "protocol" not in parsed["calibration"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"check": True},
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
