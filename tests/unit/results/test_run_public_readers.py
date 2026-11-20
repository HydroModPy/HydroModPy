"""Readers of ``results`` that other layers call instead of reaching into a run.

Acting faces of a budget component, the calibration sessions of a source and the
latest delivery of each published pair. The particle readers are in ``test_particles.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.calibration_trials import calibration_sessions
from hydromodpy.results.run.array import acting_faces, acting_faces_over_run


class _Store:
    def __init__(self, root: dict) -> None:
        self.root = root
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _run_over(root: dict, **catalog_members) -> SimpleNamespace:
    """A run whose store holds ``root``, recording every opening."""
    opened: list[_Store] = []

    def open_zarr(_sim_id):
        opened.append(_Store(root))
        return opened[-1]

    return SimpleNamespace(
        sim_id="sim-readers",
        opened=opened,
        _catalog=SimpleNamespace(open_zarr=open_zarr, **catalog_members),
    )


def test_no_session_gives_an_empty_frame() -> None:
    frame = calibration_sessions(object())

    assert isinstance(frame, pd.DataFrame)
    assert frame.empty


def test_a_block_that_is_not_the_mesh_is_refused() -> None:
    with pytest.raises(ValueError, match="'drain' budget holds 3 values"):
        acting_faces(np.zeros((2, 3)), "drain", 4)


def test_a_missing_component_is_refused() -> None:
    run = _run_over({"budget": {}})

    with pytest.raises(ValueError, match="'drain' budget is not an array"):
        acting_faces_over_run(run, ["drain"], 4)
    assert run.opened[0].closed


def test_latest_delivery_of_each_pair(tmp_path: Path) -> None:
    # ``Run.deliveries`` reads ``published.jsonl`` and keeps the last line of a pair.
    from hydromodpy.results.publication import PublishedLine, append_published
    from hydromodpy.results.run.view import Run

    for state, attempts in (("pending", 0), ("delivered", 1)):
        append_published(
            tmp_path,
            PublishedLine(
                kind="delivery",
                file="exports/head_last.tif",
                destination="/data/depot/head_last.tif",
                state=state,
                sha256="a" * 64,
                bytes=3,
                attempts=attempts,
                published_at=datetime(2026, 11, 10, tzinfo=UTC),
            ),
        )
    run = Run("sim", SimpleNamespace(run_dir_for=lambda sim_id: tmp_path))  # type: ignore[arg-type]

    assert [(line.state, line.attempts) for line in run.deliveries] == [("delivered", 1)]
