"""A run published with its results and its inputs replays without the workspace it came from.

Step 1 of example 04 runs in a first workspace and is published, which takes
its results and its inputs by default. Under a second disposable HOME, with no
workspace and no data cache, ``hmp replay`` plays the copy again into a fresh
project, its inputs read from ``inputs/`` by content. The head
field comes out the same, to the 16-bit rounding of the stored fields.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr

from tests.e2e._step1_minimal import RUN_NAME, disposable_env, hmp, make_workspace

pytestmark = pytest.mark.e2e

FIELD_PRECISION_RTOL = 2.0**-10
"""Relative step of a float32 rounded to 16 significant bits (see tests/TOLERANCES.md)."""


def _last_head(run_dir: Path) -> np.ndarray:
    root = zarr.open_group(str(run_dir / "fields.zarr"), mode="r", use_consolidated=False)
    head = np.asarray(root["head"])
    return head[-1]


def test_a_published_run_replays_alone_with_the_same_heads(tmp_path) -> None:
    project = make_workspace(tmp_path / "workspace")
    first = disposable_env(tmp_path / "home_first")
    solved = hmp("run", "step1_minimal.toml", cwd=project, env=first)
    assert solved.returncode == 0, solved.stderr[-4000:]
    copy = tmp_path / "published" / RUN_NAME
    published = hmp(
        "publish",
        RUN_NAME,
        "--to",
        str(copy),
        cwd=project,
        env=first,
    )
    assert published.returncode == 0, published.stderr[-4000:]

    second = disposable_env(tmp_path / "home_second")
    replay_project = tmp_path / "replay"
    replay_project.mkdir()
    (replay_project / "project.toml").write_text("", encoding="utf-8")
    replayed = hmp(
        "replay",
        str(copy),
        "-w",
        str(replay_project),
        cwd=replay_project,
        env=second,
    )
    assert replayed.returncode == 0, replayed.stderr[-4000:]

    np.testing.assert_allclose(
        _last_head(replay_project / "runs" / RUN_NAME),
        _last_head(copy),
        rtol=FIELD_PRECISION_RTOL,
    )
