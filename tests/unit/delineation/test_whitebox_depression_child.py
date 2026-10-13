"""Whitebox depression removal in a child interpreter.

Whitebox Workflows 1.3.5 can lose a thread race inside ``fill_depressions`` and
then calls ``process::exit(1)`` from its panic hook. These tests pin what the
child buys: the same raster as an in-process call, a rerun on that race only,
and a raised error with Whitebox's own message on anything else.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import TerrainError
from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
    WhiteboxWorkflowsBackend,
    isolated,
)

pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")

pytestmark = pytest.mark.allow_subprocess

RACE_STDERR = (
    "thread '<unnamed>' panicked at src/tools/hydrology/fill_depressions.rs:191:23:\n"
    "Error unwrapping 'output'\n"
    "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\n"
)


@pytest.fixture
def pitted_dem(tmp_path) -> Path:
    """A plane draining east with one pit and one flat, in float32."""
    rows, cols = np.mgrid[0:40, 0:40]
    surface = 100.0 - cols.astype("float64")
    surface[20, 20] -= 30.0
    surface[5:9, 5:9] = 80.0
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=40,
        width=40,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        nodata=-9999.0,
        transform=rasterio.transform.from_origin(300000.0, 6800000.0, 25.0, 25.0),
    ) as dst:
        dst.write(surface.astype("float32"), 1)
    return path


def _cells(raster) -> bytes:
    rows = raster.configs.rows
    return np.array([raster.get_row_data(row) for row in range(rows)]).tobytes()


@pytest.mark.parametrize(
    ("correction", "tool", "options"),
    [
        ("fill_depressions_raster", "fill_depressions", {}),
        ("breach_depressions_raster", "breach_depressions_least_cost", {}),
        (
            "breach_depressions_raster",
            "breach_depressions_least_cost",
            {"max_dist": 4, "max_cost": 2.0, "fill_deps": True},
        ),
    ],
)
def test_the_child_returns_the_raster_an_in_process_call_returns(
    pitted_dem, correction, tool, options
) -> None:
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(pitted_dem))

    from_child = getattr(backend.flow, correction)(dem, **options)
    with backend.raster.single_threaded():
        in_process = getattr(backend.raster._env, tool)(dem, **options)

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


def test_a_child_that_lost_the_race_is_run_again_and_says_so(
    monkeypatch, pitted_dem, caplog
) -> None:
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(pitted_dem))
    expected = _cells(backend.flow.fill_depressions_raster(dem))
    calls = _scripted_run(monkeypatch, [RACE_STDERR, None])

    with caplog.at_level(logging.WARNING):
        filled = backend.flow.fill_depressions_raster(dem)

    assert len(calls) == 2
    assert _cells(filled) == expected
    assert "lost the thread race" in caplog.text
    assert "Error unwrapping 'output'" in caplog.text


def test_a_race_on_every_attempt_is_raised(monkeypatch, pitted_dem) -> None:
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(pitted_dem))
    calls = _scripted_run(monkeypatch, [RACE_STDERR] * isolated.MAX_ATTEMPTS)

    with pytest.raises(TerrainError, match="Error unwrapping 'output'"):
        backend.flow.fill_depressions_raster(dem)

    assert len(calls) == isolated.MAX_ATTEMPTS


def test_any_other_failure_is_raised_at_once_with_the_child_message(
    monkeypatch, pitted_dem
) -> None:
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(pitted_dem))
    other = "thread '<unnamed>' panicked at src/tools/hydrology/fill_depressions.rs:80:9:\nboom\n"
    calls = _scripted_run(monkeypatch, [other])

    with pytest.raises(TerrainError, match="boom"):
        backend.flow.fill_depressions_raster(dem)

    assert len(calls) == 1


def test_a_real_child_failure_is_raised_with_its_message() -> None:
    """A real child failing, not a scripted one: its own message reaches the caller."""

    class _EnvThatWritesNothing:
        """The parent writes no source, so the child has nothing to read."""

        @staticmethod
        def write_raster(raster, path, compress=False) -> None:
            return None

    with pytest.raises(TerrainError, match=r"exit code 1, attempt 1 of \d"):
        isolated.run_depression_tool(
            _EnvThatWritesNothing(),
            "fill_depressions",
            object(),
            options={},
            max_procs=1,
            verbose=False,
        )


def test_only_the_depression_tools_run_in_a_child() -> None:
    with pytest.raises(ValueError, match="not a Whitebox depression tool"):
        isolated.run_depression_tool(
            object(), "d8_pointer", object(), options={}, max_procs=1, verbose=False
        )
