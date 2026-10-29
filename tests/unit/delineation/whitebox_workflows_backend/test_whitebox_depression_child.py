"""Whitebox depression removal in a child interpreter.

Whitebox Workflows 1.3.5 can lose a thread race in ``fill_depressions`` and exit
the process. The child returns the in-process raster, reruns on that race only,
and raises Whitebox's own message on anything else.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import TerrainError
from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
    WhiteboxWorkflowsBackend,
    isolated,
)
from tests._helpers.geotiffs import write_geotiff

pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")

pytestmark = pytest.mark.allow_subprocess

RACE_STDERR = (
    "thread '<unnamed>' panicked at src/tools/hydrology/fill_depressions.rs:191:23:\n"
    "Error unwrapping 'output'\n"
    "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\n"
)


@pytest.fixture
def pitted(tmp_path):
    """A backend and a plane draining east with one pit and one flat, in float32."""
    surface = 100.0 - np.mgrid[0:40, 0:40][1].astype("float64")
    surface[20, 20] -= 30.0
    surface[5:9, 5:9] = 80.0
    dem = write_geotiff(
        tmp_path / "dem.tif", surface, origin=(300000.0, 6800000.0), cell=25.0, nodata=-9999.0, dtype="float32"
    )  # fmt: skip
    backend = WhiteboxWorkflowsBackend()
    return backend, backend.raster.read_raster(str(dem))


def _cells(raster) -> bytes:
    rows = raster.configs.rows
    return np.array([raster.get_row_data(row) for row in range(rows)]).tobytes()


@pytest.mark.parametrize(
    ("correction", "tool", "options"),
    [
        ("fill_depressions_raster", "fill_depressions", {}),
        ("breach_depressions_raster", "breach_depressions_least_cost", {}),
        ("breach_depressions_raster", "breach_depressions_least_cost", {"max_dist": 4, "max_cost": 2.0, "fill_deps": True}),
    ],
)  # fmt: skip
def test_the_child_returns_the_raster_an_in_process_call_returns(
    pitted, correction, tool, options
) -> None:
    backend, dem = pitted
    from_child = getattr(backend.flow, correction)(dem, **options)
    with backend.raster.single_threaded():
        in_process = getattr(backend.raster.env, tool)(dem, **options)
    assert _cells(from_child) == _cells(in_process)
    assert from_child.configs.data_type == in_process.configs.data_type
    assert from_child.configs.nodata == in_process.configs.nodata


def _scripted_run(monkeypatch, outcomes: list[str | None]) -> list[list[str]]:
    """Answer each child with a scripted race (stderr) or the real run (None)."""
    real_run = subprocess.run
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        outcome = outcomes.pop(0)
        if outcome is None:
            return real_run(command, **kwargs)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=outcome)

    monkeypatch.setattr(isolated.subprocess, "run", fake_run)
    return calls


def test_a_child_that_lost_the_race_is_run_again_and_says_so(monkeypatch, pitted, caplog) -> None:
    backend, dem = pitted
    expected = _cells(backend.flow.fill_depressions_raster(dem))
    calls = _scripted_run(monkeypatch, [RACE_STDERR, None])
    with caplog.at_level(logging.WARNING):
        filled = backend.flow.fill_depressions_raster(dem)
    assert len(calls) == 2
    assert _cells(filled) == expected
    assert "lost the thread race" in caplog.text
    assert "Error unwrapping 'output'" in caplog.text


@pytest.mark.parametrize(
    ("outcomes", "match"),
    [
        ([RACE_STDERR] * isolated.MAX_ATTEMPTS, "Error unwrapping 'output'"),
        (["thread '<unnamed>' panicked at src/tools/hydrology/fill_depressions.rs:80:9:\nboom\n"], "boom"),
    ],
    ids=["a_race_on_every_attempt", "any_other_failure_at_once"],
)  # fmt: skip
def test_a_child_failure_is_raised_with_the_child_message(
    monkeypatch, pitted, outcomes, match
) -> None:
    backend, dem = pitted
    expected_calls = len(outcomes)
    calls = _scripted_run(monkeypatch, outcomes)
    with pytest.raises(TerrainError, match=match):
        backend.flow.fill_depressions_raster(dem)
    assert len(calls) == expected_calls


@pytest.mark.parametrize(
    ("env", "tool", "error", "match"),
    [
        # A real child failing, not a scripted one: the parent writes no source.
        (SimpleNamespace(write_raster=lambda raster, path, compress=False: None), "fill_depressions",
         TerrainError, r"exit code 1, attempt 1 of \d"),
        (object(), "d8_pointer", ValueError, "not a Whitebox depression tool"),
    ],
    ids=["a_real_child_failure_with_its_message", "only_the_depression_tools_run_in_a_child"],
)  # fmt: skip
def test_a_child_that_cannot_run_raises_with_its_message(env, tool, error, match) -> None:
    with pytest.raises(error, match=match):
        isolated.run_depression_tool(env, tool, object(), options={}, max_procs=1, verbose=False)


def test_a_verbose_backend_relays_the_log_of_the_child(monkeypatch, capsys, pitted) -> None:
    monkeypatch.setenv("HMP_WHITEBOX_VERBOSE", "1")
    WhiteboxWorkflowsBackend().flow.fill_depressions_raster(pitted[1])
    assert "fill" in capsys.readouterr().out.lower()
