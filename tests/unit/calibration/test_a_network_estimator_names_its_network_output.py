"""A network estimator on the single-metric route must name its network output.

A search with no block reads only the output its ``variable`` names. A file
with ``objective = "distance_gap"``, the default ``variable = "head"`` and a
network output beside it loads, and the runner guards count that output as
scored. The extractor never reads it: it takes the station route on ``head``
and stops at the first trial. Preflight refuses it, and does not blame an
extent table on an output the search never scores.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.calibration.test_preflight import _preflight, _write

_PARAMETERS = """
[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"
"""

_NETWORK = """
[calibration.outputs.net]
support = "network"
stream_geometry_path = "{maximal}"
minimal_stream_geometry_path = "{minimal}"

[calibration.outputs.net.extent]
"""


def _outputs(tmp_path: Path) -> str:
    folder = tmp_path / "data" / "hydrography"
    folder.mkdir(parents=True, exist_ok=True)
    maximal, minimal = folder / "streams.gpkg", folder / "permanent.gpkg"
    maximal.write_bytes(b"maximal")
    minimal.write_bytes(b"minimal")
    return _NETWORK.format(maximal=maximal.as_posix(), minimal=minimal.as_posix())


def _whole_file(tmp_path: Path, *, variable: str | None, regime: str = "transient") -> str:
    route = f'variable = "{variable}"\n' if variable else ""
    return (
        f'[flow]\nflow_regime = "{regime}"\n'
        '[calibration]\nmethod = "bisection"\nobjective = "distance_gap"\n'
        + route
        + _PARAMETERS
        + _outputs(tmp_path)
    )


def _one_phase(tmp_path: Path, *, variable: str) -> str:
    # The section names the estimator too, or the network output would be
    # refused at load for no criterion reading it.
    return (
        '[calibration]\nmethod = "bisection"\nobjective = "distance_gap"\n'
        + _PARAMETERS
        + _outputs(tmp_path)
        + "\n[[calibration.phases]]\n"
        'name = "k_network"\nmethod = "bisection"\nparameters = ["K"]\n'
        f'variable = "{variable}"\nobjective = "distance_gap"\n'
    )


def _refused(findings) -> list:
    return [item for item in findings if "names none this file declares" in item.detail]


def test_a_whole_file_search_on_the_default_variable_is_refused(tmp_path) -> None:
    findings = _preflight(_write(tmp_path, _whole_file(tmp_path, variable=None)))

    [refused] = _refused(findings)
    assert refused.severity == "error"
    assert refused.where == "[calibration]"
    assert "'head'" in refused.detail
    assert "network outputs: net" in refused.detail


def test_a_steady_run_is_not_blamed_on_an_extent_it_never_reads(tmp_path) -> None:
    doc = _whole_file(tmp_path, variable=None, regime="steady")

    findings = _preflight(_write(tmp_path, doc))

    assert len(_refused(findings)) == 1
    assert [item for item in findings if "extent table" in item.detail] == []


def test_a_single_metric_phase_on_a_station_variable_is_refused(tmp_path) -> None:
    findings = _preflight(_write(tmp_path, _one_phase(tmp_path, variable="head")))

    [refused] = _refused(findings)
    assert refused.where == "[[calibration.phases]] 'k_network'"


@pytest.mark.parametrize("route", ["whole_file", "phase"])
def test_a_variable_naming_the_network_output_is_no_finding(tmp_path, route: str) -> None:
    if route == "whole_file":
        doc = _whole_file(tmp_path, variable="net")
    else:
        doc = _one_phase(tmp_path, variable="net")

    assert _refused(_preflight(_write(tmp_path, doc))) == []
