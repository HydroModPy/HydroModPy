"""Unit tests for the XDG-compliant path helpers in ``hydromodpy.core.state.paths``."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import platformdirs
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    CONFIGS_DIRNAME,
    PROJECT_MARKER_FILENAME,
    PROJECTS_DIRNAME,
    RUN_SCRATCH_ENV,
    RUNS_DIRNAME,
    WORKSPACE_TOML_FILENAME,
    active_run_scratch,
    cache_dir,
    catalog_path_for,
    is_project_root,
    is_workspace_root,
    kept_preprocessing_dir,
    preprocessing_dir,
    project_roots_under,
    refuse_a_sealed_run_as_project,
    resolve_project_root,
    resolve_workspace,
    run_scratch,
    run_scratch_of,
    scratch_dir_for,
    scratch_root_for,
    state_dir,
    sweep_dead_run_scratch,
)


@pytest.mark.parametrize(
    ("dir_fn", "home_env", "platformdirs_fn"),
    [
        (cache_dir, "HMP_CACHE_HOME", platformdirs.user_cache_dir),
        (state_dir, "HMP_STATE_HOME", platformdirs.user_state_dir),
    ],
    ids=["cache", "state"],
)
def test_dir_defaults_to_platformdirs(
    dir_fn, home_env: str, platformdirs_fn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without override, cache_dir/state_dir resolve to their platformdirs default."""
    monkeypatch.delenv(home_env, raising=False)
    assert dir_fn() == Path(platformdirs_fn("hydromodpy"))


@pytest.mark.parametrize(
    ("dir_fn", "home_env"),
    [
        (cache_dir, "HMP_CACHE_HOME"),
        (state_dir, "HMP_STATE_HOME"),
    ],
    ids=["cache", "state"],
)
def test_dir_respects_env_override(
    dir_fn, home_env: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HMP_CACHE_HOME/HMP_STATE_HOME redirect their dir helper to a custom path."""
    custom = tmp_path / "custom"
    monkeypatch.setenv(home_env, str(custom))
    assert dir_fn() == custom.resolve()


def test_paths_expand_user_in_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override env vars expand ``~`` to the user's home directory."""
    monkeypatch.setenv("HMP_CACHE_HOME", "~/foo_cache_override")
    monkeypatch.setenv("HMP_STATE_HOME", "~/foo_state_override")
    expected_cache = (Path.home() / "foo_cache_override").resolve()
    expected_state = (Path.home() / "foo_state_override").resolve()
    assert cache_dir() == expected_cache
    assert state_dir() == expected_state


def test_paths_have_no_side_effects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Helpers never create directories on import or at call time."""
    custom_cache = tmp_path / "no_mkdir_cache"
    custom_state = tmp_path / "no_mkdir_state"
    monkeypatch.setenv("HMP_CACHE_HOME", str(custom_cache))
    monkeypatch.setenv("HMP_STATE_HOME", str(custom_state))
    cache_dir()
    state_dir()
    assert not custom_cache.exists()
    assert not custom_state.exists()


def test_resolve_workspace_file_uri_returns_local_path() -> None:
    """A ``file://`` URI resolves to the matching local :class:`Path`."""
    result = resolve_workspace("file:///tmp/foo")
    assert isinstance(result, Path)
    assert result == Path("/tmp/foo")


@pytest.mark.parametrize(
    ("scheme", "uri"),
    [
        ("s3", "s3://bucket/foo"),
        ("gs", "gs://bucket/foo"),
    ],
    ids=["s3", "gs"],
)
def test_resolve_workspace_raises_not_implemented_for_unsupported_scheme(
    scheme: str, uri: str
) -> None:
    """Cloud URIs are accepted at the type level but rejected at runtime."""
    with pytest.raises(NotImplementedError, match=scheme):
        resolve_workspace(uri)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "cheze"
    (root / RUNS_DIRNAME).mkdir(parents=True)
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def test_resolve_project_root_walks_up_to_the_marker(tmp_path: Path) -> None:
    """Any directory under the project resolves to the marker directory."""
    root = _project(tmp_path)
    assert resolve_project_root(root) == root
    assert resolve_project_root(root / RUNS_DIRNAME) == root


def test_resolve_project_root_ignores_a_missing_catalog(tmp_path: Path) -> None:
    """Deleting the DuckDB index leaves the root resolution untouched."""
    root = _project(tmp_path)
    catalog = root / CATALOG_FILENAME
    catalog.write_bytes(b"")
    assert resolve_project_root(root / RUNS_DIRNAME) == root
    catalog.unlink()
    assert resolve_project_root(root / RUNS_DIRNAME) == root


def test_resolve_project_root_is_not_anchored_by_a_catalog(tmp_path: Path) -> None:
    """A catalog without a marker never anchors a root above the start."""
    root = tmp_path / "legacy"
    (root / RUNS_DIRNAME).mkdir(parents=True)
    (root / CATALOG_FILENAME).write_bytes(b"")
    assert resolve_project_root(root / RUNS_DIRNAME) == root / RUNS_DIRNAME


def test_resolve_project_root_defaults_to_the_start_directory(tmp_path: Path) -> None:
    """A flat directory without a marker is its own root."""
    assert resolve_project_root(tmp_path) == tmp_path


@pytest.mark.parametrize(
    ("relative", "held", "answer"),
    [
        pytest.param("runs/first", "outcome.json", ".", id="a-run-of-a-flat-project"),
        pytest.param("runs/first.v2", "manifest.json", ".", id="a-sealed-run"),
        pytest.param("sessions/case", "outcome.json", ".", id="a-session"),
        pytest.param("sessions/case/trials/0003", "outcome.json", ".", id="a-kept-trial"),
        pytest.param("runs/first", "notes.txt", "runs/first", id="a-folder-of-the-user"),
        pytest.param("elsewhere/base", "manifest.json", "elsewhere/base", id="a-copy-of-a-run"),
    ],
)
def test_a_result_directory_answers_for_its_flat_project(
    tmp_path: Path, relative: str, held: str, answer: str
) -> None:
    folder = tmp_path / relative
    folder.mkdir(parents=True)
    (folder / held).write_text("{}", encoding="utf-8")
    assert resolve_project_root(folder) == (tmp_path / answer).resolve()


def test_a_sealed_run_is_refused_as_a_project(tmp_path: Path) -> None:
    refuse_a_sealed_run_as_project(tmp_path)
    for name in ("manifest.json", "config.toml"):
        (tmp_path / name).write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="-w <project>"):
        refuse_a_sealed_run_as_project(tmp_path)


def test_resolve_project_root_rejects_an_unanchored_configs_dir(tmp_path: Path) -> None:
    """A config variant under ``configs/`` must not anchor the root there."""
    configs = tmp_path / "orphan" / CONFIGS_DIRNAME
    configs.mkdir(parents=True)
    with pytest.raises(ConfigError, match=PROJECT_MARKER_FILENAME):
        resolve_project_root(configs)


def test_resolve_project_root_accepts_a_configs_dir_under_a_marker(tmp_path: Path) -> None:
    """``configs/`` inside a real project resolves to the project root."""
    root = _project(tmp_path)
    configs = root / CONFIGS_DIRNAME
    configs.mkdir()
    assert resolve_project_root(configs) == root


def _make_project(parent: Path, name: str) -> Path:
    """Create a project root carrying ``project.toml``."""
    root = parent / name
    root.mkdir(parents=True)
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def _make_workspace(parent: Path, name: str = "ws") -> Path:
    """Create a workspace root carrying ``workspace.toml`` and ``projects/``."""
    root = parent / name
    (root / PROJECTS_DIRNAME).mkdir(parents=True)
    (root / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def _symlink_dir(link: Path, target: Path) -> None:
    """Symlink ``link`` to ``target``, skipping where the OS forbids it."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable here: {exc}")


def test_is_project_root_accepts_the_marker(tmp_path: Path) -> None:
    """``project.toml`` alone makes a project root, before any run exists."""
    root = _make_project(tmp_path, "naizin")
    assert is_project_root(root)
    assert not is_workspace_root(root)


def test_is_project_root_accepts_a_bare_index_database(tmp_path: Path) -> None:
    """A root whose marker is gone still counts while its index database is there."""
    root = tmp_path / "naizin"
    catalog = catalog_path_for(root)
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(b"")
    assert is_project_root(root)


def test_is_workspace_root_accepts_either_marker(tmp_path: Path) -> None:
    """``workspace.toml`` or a ``projects/`` directory each make a workspace root."""
    with_toml = tmp_path / "by_toml"
    with_toml.mkdir()
    (with_toml / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    with_dir = tmp_path / "by_dir"
    (with_dir / PROJECTS_DIRNAME).mkdir(parents=True)
    assert is_workspace_root(with_toml)
    assert is_workspace_root(with_dir)
    assert not is_project_root(with_toml)
    assert not is_project_root(with_dir)


def test_a_plain_directory_is_neither_root(tmp_path: Path) -> None:
    """A directory without any marker carries no granularity of its own."""
    plain = tmp_path / "downloads"
    plain.mkdir()
    assert not is_project_root(plain)
    assert not is_workspace_root(plain)


def test_project_roots_under_keeps_a_plain_directory_as_one_root(tmp_path: Path) -> None:
    """Anything that is not a workspace root stands for itself, resolved."""
    plain = tmp_path / "downloads"
    plain.mkdir()
    assert project_roots_under(plain) == [plain.resolve()]


def test_project_roots_under_expands_a_workspace_root(tmp_path: Path) -> None:
    """A workspace root contributes the project roots it holds, sorted, not itself."""
    workspace = _make_workspace(tmp_path)
    projects = workspace / PROJECTS_DIRNAME
    beta = _make_project(projects, "beta")
    alpha = _make_project(projects, "alpha")
    (projects / "notes").mkdir()
    assert project_roots_under(workspace) == [alpha.resolve(), beta.resolve()]


def test_project_roots_under_includes_a_workspace_that_is_also_a_project(tmp_path: Path) -> None:
    """A root carrying both markers is listed first, then the projects it holds."""
    workspace = _make_workspace(tmp_path)
    (workspace / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    alpha = _make_project(workspace / PROJECTS_DIRNAME, "alpha")
    assert project_roots_under(workspace) == [workspace.resolve(), alpha.resolve()]


def test_project_roots_under_expands_an_empty_workspace_to_nothing(tmp_path: Path) -> None:
    """A workspace with no project yet registers no row."""
    assert project_roots_under(_make_workspace(tmp_path)) == []


def test_project_roots_under_resolves_a_symlinked_project(tmp_path: Path) -> None:
    """An expanded entry resolves, so a symlinked project is one root, not two.

    Registering the workspace and registering the project directly must yield
    the same string, otherwise the global index holds the same project twice.
    """
    target = _make_project(tmp_path, "elsewhere")
    workspace = _make_workspace(tmp_path)
    _symlink_dir(workspace / PROJECTS_DIRNAME / "linked", target)
    assert project_roots_under(workspace) == [target.resolve()]
    assert project_roots_under(workspace / PROJECTS_DIRNAME / "linked") == [target.resolve()]


def test_project_roots_under_drops_duplicate_symlinks(tmp_path: Path) -> None:
    """Two links onto the same project collapse into a single root."""
    target = _make_project(tmp_path, "elsewhere")
    workspace = _make_workspace(tmp_path)
    _symlink_dir(workspace / PROJECTS_DIRNAME / "one", target)
    _symlink_dir(workspace / PROJECTS_DIRNAME / "two", target)
    assert project_roots_under(workspace) == [target.resolve()]


# Each run of a project works in its own scratch folder, so runs of one project can run at once.
#
# Run concurrently on example 04, the runs of one project corrupted each other in
# the shared ``.hmp/scratch/``: one run's trials read the network another run
# wrote, two calibrations shared one ``_shared_recharge`` for different recharges,
# and a run that ended swept the solver folders of the others.


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


def test_a_resume_finds_the_folder_its_run_journalled() -> None:
    uris = [
        "runs/killed/config.toml",
        ".hmp/scratch/killed.p4242/_preprocessing/geographic/dem.tif",
        ".hmp/scratch/other.p1/_preprocessing/geographic/dem.tif",
    ]

    assert run_scratch_of(uris) == "killed.p4242"
    assert run_scratch_of([".hmp/scratch/_preprocessing/geographic/dem.tif"]) is None
    assert run_scratch_of([]) is None


@pytest.mark.allow_subprocess
def test_a_resume_works_in_the_folder_of_the_killed_run(tmp_path: Path) -> None:
    """The sweep must not delete what the killed run left for its resume."""
    root = scratch_root_for(tmp_path)
    killed = f"killed.p{_dead_pid()}"
    tree = root / killed / "_preprocessing" / "geographic"
    tree.mkdir(parents=True)
    (tree / "dem.tif").write_bytes(b"dem")
    sweep = textwrap.dedent(
        f"""
        from pathlib import Path
        from hydromodpy.core.state.paths import sweep_dead_run_scratch
        print([path.name for path in sweep_dead_run_scratch(Path({str(tmp_path)!r}))])
        """
    )
    env = {k: v for k, v in os.environ.items() if k != RUN_SCRATCH_ENV}

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
def test_a_resume_does_not_take_over_a_folder_in_use(tmp_path: Path) -> None:
    root = scratch_root_for(tmp_path)
    alive = f"running.p{os.getppid()}"
    (root / alive).mkdir(parents=True)
    gone = f"gone.p{_dead_pid()}"

    with run_scratch(tmp_path, "resume", resumes=alive) as key:
        assert key == f"resume.p{os.getpid()}"
    with run_scratch(tmp_path, "resume", resumes=gone) as key:
        assert key == f"resume.p{os.getpid()}"
    assert (root / alive).is_dir()


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
    from hydromodpy.spatial.geographic.preprocessing_cleanup import cleanup_stable_folder

    root = scratch_root_for(tmp_path)
    tree = root / "nancon_intermittence_mf6.p1" / "_preprocessing"
    (tree / "geographic").mkdir(parents=True)
    (tree / "geographic" / "outlet.shp").write_bytes(b"x")
    (root / "other.p2" / "nancon").mkdir(parents=True)

    cleanup_stable_folder(SimpleNamespace(stable_folder=tree))

    assert not (root / "nancon_intermittence_mf6.p1").exists()
    assert (root / "other.p2" / "nancon").is_dir()
