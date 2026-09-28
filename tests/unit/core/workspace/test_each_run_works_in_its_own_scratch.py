"""Each run of a project works in its own scratch folder, so runs of one project can run at once.

Run concurrently on example 04, the runs of one project corrupted each other in
the shared ``.hmp/scratch/``: one run's trials read the network another run
wrote, two calibrations shared one ``_shared_recharge`` for different recharges,
and a run that ended swept the solver folders of the others.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.paths import (
    RUN_SCRATCH_ENV,
    active_run_scratch,
    kept_preprocessing_dir,
    preprocessing_dir,
    run_scratch,
    scratch_dir_for,
    scratch_root_for,
    sweep_dead_run_scratch,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_inherited_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(RUN_SCRATCH_ENV, raising=False)


def test_a_run_works_in_its_own_folder(tmp_path: Path) -> None:
    assert scratch_dir_for(tmp_path) == tmp_path / ".hmp" / "scratch"

    with run_scratch(tmp_path, "step1_minimal") as key:
        assert key == f"step1_minimal.p{os.getpid()}"
        assert scratch_dir_for(tmp_path) == tmp_path / ".hmp" / "scratch" / key
        assert preprocessing_dir(tmp_path) == scratch_dir_for(tmp_path) / "_preprocessing"
        assert os.environ[RUN_SCRATCH_ENV] == key

    assert active_run_scratch() is None
    assert scratch_dir_for(tmp_path) == scratch_root_for(tmp_path)


def test_the_trials_of_a_session_share_its_folder(tmp_path: Path) -> None:
    with run_scratch(tmp_path, "run_calibration") as session:
        with run_scratch(tmp_path, "trial") as trial:
            assert trial == session
        assert active_run_scratch() == session
    assert active_run_scratch() is None


def test_a_child_process_works_in_its_parent_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RUN_SCRATCH_ENV, "parent.p1")
    with run_scratch(tmp_path, "child") as key:
        assert key == "parent.p1"
    assert os.environ[RUN_SCRATCH_ENV] == "parent.p1"


def test_an_empty_run_folder_is_removed_at_the_end(tmp_path: Path) -> None:
    with run_scratch(tmp_path, "project") as key:
        scratch_dir_for(tmp_path).mkdir(parents=True)
    assert not (scratch_root_for(tmp_path) / key).exists()


@pytest.mark.allow_subprocess
def test_two_processes_of_one_project_get_two_folders(tmp_path: Path) -> None:
    script = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from hydromodpy.core.state.paths import run_scratch, scratch_dir_for
        with run_scratch(Path({str(tmp_path)!r}), "project") as key:
            print(scratch_dir_for(Path({str(tmp_path)!r})), flush=True)
            time.sleep(1.0)
        """
    )
    env = {k: v for k, v in os.environ.items() if k != RUN_SCRATCH_ENV}
    procs = [
        subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, env=env)
        for _ in range(2)
    ]
    folders = [proc.communicate(timeout=60)[0].strip() for proc in procs]

    assert folders[0] != folders[1]
    assert all(Path(folder).parent == scratch_root_for(tmp_path) for folder in folders)


@pytest.mark.allow_subprocess
def test_the_folder_of_a_killed_run_is_swept(tmp_path: Path) -> None:
    dead = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True
    )
    dead_pid = int(dead.stdout.strip())
    root = scratch_root_for(tmp_path)
    (root / f"step5_export.p{dead_pid}" / "nancon").mkdir(parents=True)
    (root / f"project.p{os.getpid()}").mkdir()
    (root / "nancon_intermittence_mf6").mkdir()

    removed = sweep_dead_run_scratch(tmp_path)

    assert [path.name for path in removed] == [f"step5_export.p{dead_pid}"]
    assert (root / f"project.p{os.getpid()}").is_dir()
    assert (root / "nancon_intermittence_mf6").is_dir()


def test_a_kept_tree_is_found_after_the_run(tmp_path: Path) -> None:
    assert kept_preprocessing_dir(tmp_path) is None
    kept = scratch_root_for(tmp_path) / "project.p1" / "_preprocessing"
    kept.mkdir(parents=True)

    assert kept_preprocessing_dir(tmp_path) == kept


def test_the_cleanup_of_a_run_leaves_the_other_runs_alone(tmp_path: Path) -> None:
    from hydromodpy.workflow.steps.export import step_cleanup_scratch

    root = scratch_root_for(tmp_path)
    other = root / f"project.p{os.getppid()}" / "nancon_intermittence_mf6"
    other.mkdir(parents=True)
    with run_scratch(tmp_path, "step1_minimal"):
        own = scratch_dir_for(tmp_path)
        (own / "nancon_step1_minimal").mkdir(parents=True)
        (own / "_preprocessing").mkdir()
        ctx = SimpleNamespace(
            setup=SimpleNamespace(workspace=SimpleNamespace(solver_scratch_folder=own)),
            model=None,
        )
        step_cleanup_scratch(ctx)

        assert not (own / "nancon_step1_minimal").exists()
        assert (own / "_preprocessing").is_dir()
    assert other.is_dir()


def test_closing_a_project_leaves_no_empty_run_folder(tmp_path: Path) -> None:
    from hydromodpy.spatial.geographic.store_ingestion import cleanup_stable_folder

    root = scratch_root_for(tmp_path)
    tree = root / "nancon_intermittence_mf6.p1" / "_preprocessing"
    (tree / "geographic").mkdir(parents=True)
    (tree / "geographic" / "outlet.shp").write_bytes(b"x")
    (root / "other.p2" / "nancon").mkdir(parents=True)

    cleanup_stable_folder(SimpleNamespace(stable_folder=tree))

    assert not (root / "nancon_intermittence_mf6.p1").exists()
    assert (root / "other.p2" / "nancon").is_dir()
