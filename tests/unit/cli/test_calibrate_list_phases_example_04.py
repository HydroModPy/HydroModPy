"""``--list-phases`` output of example 04 is frozen, through the CLI path.

Each file declares its phases, and each prints, under each phase line,
what its blocks (or its single metric) compare with what. The table reads
declarations only, so this needs no more of the example's data on disk than
loading the two TOML files already needs (``load_toml_calibration`` resolves
a relative ``stream_geometry_path`` against the file, and leaves it as
declared when nothing is found there -- see
``hydromodpy.calibration.runners.cli_runner.resolve_stream_geometry_paths``).

A network output's source is the file's absolute, resolved path in the table
the builder returns, but the CLI prints it relative to the working directory
when it sits under it (``calibrate.py:_shortened_if_under_cwd``), which is
where pytest runs from here, the repository root.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.cli.commands import calibrate as calibrate_cmd

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
    assert lines[2].startswith("1\ttransient_storage\tscipy_nelder_mead\t")
    assert lines[3] == (
        "    hydrograph\tnse_log\tshare 100%\tdischarge, station NANCON (whole-catchment "
        "series)\tvs station NANCON ([data.hydrometry])"
    )
    assert len(lines) == 4


def test_the_composite_file_shows_one_phase_with_two_shares(capsys) -> None:
    out = _list_phases(EXAMPLE_04 / "run_calibration_composite.toml", capsys)

    lines = out.splitlines()
    assert lines[0].startswith("0\tconductivity_and_storage\toptuna\t")
    # A share table {hydrograph = 0.7, network = 0.3}, the network gap normalised.
    assert lines[1] == (
        f"    network\tdistance_gap\tshare 30%\trelease_flux (network)\tvs {GEOMETRY}"
    )
    assert lines[2] == (
        "    hydrograph\tnse_log\tshare 70%\tdischarge, station NANCON (whole-catchment "
        "series)\tvs station NANCON ([data.hydrometry])"
    )
    assert len(lines) == 3


def test_the_protocol_written_by_hand_lists_what_the_protocol_lists(capsys) -> None:
    protocol = _list_phases(EXAMPLE_04 / "run_calibration.toml", capsys)
    by_hand = _list_phases(EXAMPLE_04 / "run_calibration_by_hand.toml", capsys)

    assert by_hand == protocol
