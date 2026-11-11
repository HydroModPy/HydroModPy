"""A run published with its results and its inputs replays without the workspace it came from.

Step 1 of example 04 runs in a first workspace and is published, which takes
its results and its inputs by default. Under a second disposable HOME, with no
workspace and no data cache, ``hmp replay`` plays the copy again into a fresh
project, its inputs read from ``inputs/`` by content. The replay is classed
``bit`` in its manifest, and its last head equals the one of the copy value by
value.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr

from hydromodpy.results.record.manifest import read_seal
from tests.e2e._step1_minimal import RUN_NAME, disposable_env, hmp, make_workspace

pytestmark = pytest.mark.e2e


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

    (replay_dir,) = sorted((replay_project / "runs").glob(f"{RUN_NAME}*"))
    replay = read_seal(replay_dir).lineage.replay
    assert replay is not None
    assert replay.class_ == "bit"
    np.testing.assert_array_equal(_last_head(replay_dir), _last_head(copy))
