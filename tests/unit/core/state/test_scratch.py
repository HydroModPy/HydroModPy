"""Each run of a project works in its own scratch folder, so runs of one project can run at once.

Run concurrently on example 04, the runs of one project corrupted each other in
the shared ``.hmp/scratch/``. One run's trials read the network another run
wrote, two calibrations shared one ``_shared_recharge`` for different recharges,
and a run that ended swept the solver folders of the others.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.scratch import (
    RUN_SCRATCH,
    active_run_scratch,
    inherit_run_scratch,
    kept_preprocessing_dir,
    preprocessing_dir,
    run_scratch,
    run_scratch_of,
    scratch_dir_for,
    scratch_root_for,
    sweep_dead_run_scratch,
)


def test_own_folder(tmp_path: Path) -> None:
    assert scratch_dir_for(tmp_path) == tmp_path / ".hmp" / "scratch"

    with run_scratch(tmp_path, "step1_minimal") as key:
        assert key == f"step1_minimal.p{os.getpid()}"
        assert scratch_dir_for(tmp_path) == tmp_path / ".hmp" / "scratch" / key
        assert preprocessing_dir(tmp_path) == scratch_dir_for(tmp_path) / "_preprocessing"
        assert RUN_SCRATCH.get() == key

    assert active_run_scratch() is None
    assert scratch_dir_for(tmp_path) == scratch_root_for(tmp_path)


def test_environment_untouched(tmp_path: Path) -> None:
    before = dict(os.environ)
    with run_scratch(tmp_path, "step1_minimal"):
        with run_scratch(tmp_path, "trial"):
            assert dict(os.environ) == before
    assert dict(os.environ) == before


def test_trials_share_the_session_folder(tmp_path: Path) -> None:
    with run_scratch(tmp_path, "run_calibration") as session:
        with run_scratch(tmp_path, "trial") as trial:
            assert trial == session
        assert active_run_scratch() == session
    assert active_run_scratch() is None


def test_worker_inherits_the_folder(tmp_path: Path) -> None:
    with inherit_run_scratch("parent.p1") as key:
        assert key == "parent.p1"
        assert scratch_dir_for(tmp_path) == scratch_root_for(tmp_path) / "parent.p1"
        with run_scratch(tmp_path, "child") as nested:
            assert nested == "parent.p1"
        assert active_run_scratch() == "parent.p1"
    assert active_run_scratch() is None


def _folder_of_a_run_in_a_thread(
    tmp_path: Path, label: str, *, copy: bool, hold: threading.Barrier
) -> tuple[str | None, str | None]:
    """Return what a pool thread reads of the scratch of the run that submits to it."""
    with run_scratch(tmp_path, label) as key:
        hold.wait(timeout=30)
        with ThreadPoolExecutor(1) as pool:
            if copy:
                future = pool.submit(copy_context().run, active_run_scratch)
            else:
                future = pool.submit(active_run_scratch)
            seen = future.result(timeout=30)
        hold.wait(timeout=30)
        return key, seen


@pytest.mark.parametrize(
    ("copy", "sees_own_run"),
    [
        pytest.param(True, True, id="a task entered through copy_context"),
        pytest.param(False, False, id="a task submitted bare reads nothing"),
    ],
)
def test_two_threads_two_folders(tmp_path: Path, copy: bool, sees_own_run: bool) -> None:
    hold = threading.Barrier(2)
    with ThreadPoolExecutor(2) as runs:
        futures = [
            runs.submit(_folder_of_a_run_in_a_thread, tmp_path, label, copy=copy, hold=hold)
            for label in ("alpha", "beta")
        ]
        answers = [future.result(timeout=60) for future in futures]

    (key_a, seen_a), (key_b, seen_b) = answers
    assert key_a != key_b
    assert {key_a.split(".")[0], key_b.split(".")[0]} == {"alpha", "beta"}
    if sees_own_run:
        assert (seen_a, seen_b) == (key_a, key_b)
    else:
        assert (seen_a, seen_b) == (None, None)


def test_empty_folder_is_removed(tmp_path: Path) -> None:
    with run_scratch(tmp_path, "project") as key:
        scratch_dir_for(tmp_path).mkdir(parents=True)
    assert not (scratch_root_for(tmp_path) / key).exists()


@pytest.mark.allow_subprocess
def test_two_processes_two_folders(tmp_path: Path) -> None:
    script = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from hydromodpy.core.state.scratch import run_scratch, scratch_dir_for
        with run_scratch(Path({str(tmp_path)!r}), "project") as key:
            print(scratch_dir_for(Path({str(tmp_path)!r})), flush=True)
            time.sleep(1.0)
        """
    )
    env = dict(os.environ)
    procs = [
        subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True, env=env)
        for _ in range(2)
    ]
    folders = [proc.communicate(timeout=60)[0].strip() for proc in procs]

    assert folders[0] != folders[1]
    assert all(Path(folder).parent == scratch_root_for(tmp_path) for folder in folders)


@pytest.mark.allow_subprocess
def test_killed_run_is_swept(tmp_path: Path) -> None:
    dead_pid = _dead_pid()
    root = scratch_root_for(tmp_path)
    (root / f"step5_export.p{dead_pid}" / "nancon").mkdir(parents=True)
    (root / f"project.p{os.getpid()}").mkdir()
    (root / "nancon_intermittence_mf6").mkdir()

    removed = sweep_dead_run_scratch(tmp_path)

    assert [path.name for path in removed] == [f"step5_export.p{dead_pid}"]
    assert (root / f"project.p{os.getpid()}").is_dir()
    assert (root / "nancon_intermittence_mf6").is_dir()


def _dead_pid() -> int:
    dead = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True
    )
    return int(dead.stdout.strip())


def test_resume_finds_the_journalled_folder() -> None:
    uris = [
        "runs/killed/config.toml",
        ".hmp/scratch/killed.p4242/_preprocessing/geographic/dem.tif",
        ".hmp/scratch/other.p1/_preprocessing/geographic/dem.tif",
    ]

    assert run_scratch_of(uris) == "killed.p4242"
    assert run_scratch_of([".hmp/scratch/_preprocessing/geographic/dem.tif"]) is None
    assert run_scratch_of([]) is None


@pytest.mark.allow_subprocess
def test_resume_in_the_killed_folder(tmp_path: Path) -> None:
    root = scratch_root_for(tmp_path)
    killed = f"killed.p{_dead_pid()}"
    tree = root / killed / "_preprocessing" / "geographic"
    tree.mkdir(parents=True)
    (tree / "dem.tif").write_bytes(b"dem")
    sweep = textwrap.dedent(
        f"""
        from pathlib import Path
        from hydromodpy.core.state.scratch import sweep_dead_run_scratch
        print([path.name for path in sweep_dead_run_scratch(Path({str(tmp_path)!r}))])
        """
    )
    env = dict(os.environ)

    with run_scratch(tmp_path, "resume", resumes=killed) as key:
        assert key == killed
        assert preprocessing_dir(tmp_path) == root / killed / "_preprocessing"
        assert (tree / "dem.tif").read_bytes() == b"dem"
        other = subprocess.run(
            [sys.executable, "-c", sweep], capture_output=True, text=True, env=env, check=True
        )
        assert other.stdout.strip() == "[]"

    assert (tree / "dem.tif").is_file()
    assert [path.name for path in sweep_dead_run_scratch(tmp_path)] == [killed]
    assert not root.exists() or list(root.iterdir()) == []


@pytest.mark.allow_subprocess
def test_resume_leaves_a_live_folder(tmp_path: Path) -> None:
    root = scratch_root_for(tmp_path)
    alive = f"running.p{os.getppid()}"
    (root / alive).mkdir(parents=True)
    gone = f"gone.p{_dead_pid()}"

    with run_scratch(tmp_path, "resume", resumes=alive) as key:
        assert key == f"resume.p{os.getpid()}"
    with run_scratch(tmp_path, "resume", resumes=gone) as key:
        assert key == f"resume.p{os.getpid()}"
    assert (root / alive).is_dir()


def test_kept_tree(tmp_path: Path) -> None:
    assert kept_preprocessing_dir(tmp_path) is None
    kept = scratch_root_for(tmp_path) / "project.p1" / "_preprocessing"
    kept.mkdir(parents=True)

    assert kept_preprocessing_dir(tmp_path) == kept


def test_cleanup_leaves_other_runs(tmp_path: Path) -> None:
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


def test_closing_leaves_no_empty_folder(tmp_path: Path) -> None:
    from hydromodpy.catchment.preprocess.preprocessing_cleanup import cleanup_stable_folder

    root = scratch_root_for(tmp_path)
    tree = root / "nancon_intermittence_mf6.p1" / "_preprocessing"
    (tree / "geographic").mkdir(parents=True)
    (tree / "geographic" / "outlet.shp").write_bytes(b"x")
    (root / "other.p2" / "nancon").mkdir(parents=True)

    cleanup_stable_folder(SimpleNamespace(stable_folder=tree))

    assert not (root / "nancon_intermittence_mf6.p1").exists()
    assert (root / "other.p2" / "nancon").is_dir()
