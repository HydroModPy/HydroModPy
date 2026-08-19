"""Unit tests for the XDG-compliant path helpers in ``hydromodpy.core.state.paths``."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    CONFIGS_DIRNAME,
    PROJECT_MARKER_FILENAME,
    PROJECTS_DIRNAME,
    RUNS_DIRNAME,
    WORKSPACE_TOML_FILENAME,
    cache_dir,
    catalog_path_for,
    is_project_root,
    is_workspace_root,
    project_roots_under,
    resolve_project_root,
    resolve_workspace,
    state_dir,
)


def test_cache_dir_defaults_to_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without override, cache_dir resolves to platformdirs user_cache_dir."""
    monkeypatch.delenv("HMP_CACHE_HOME", raising=False)
    assert cache_dir() == Path(platformdirs.user_cache_dir("hydromodpy"))


def test_state_dir_defaults_to_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without override, state_dir resolves to platformdirs user_state_dir."""
    monkeypatch.delenv("HMP_STATE_HOME", raising=False)
    assert state_dir() == Path(platformdirs.user_state_dir("hydromodpy"))


def test_cache_dir_respects_hmp_cache_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """HMP_CACHE_HOME redirects cache_dir to a custom path."""
    custom = tmp_path / "custom_cache"
    monkeypatch.setenv("HMP_CACHE_HOME", str(custom))
    assert cache_dir() == custom.resolve()


def test_state_dir_respects_hmp_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """HMP_STATE_HOME redirects state_dir to a custom path."""
    custom = tmp_path / "custom_state"
    monkeypatch.setenv("HMP_STATE_HOME", str(custom))
    assert state_dir() == custom.resolve()


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


def test_resolve_workspace_s3_raises_not_implemented() -> None:
    """``s3://`` URIs are accepted at the type level but rejected at runtime."""
    with pytest.raises(NotImplementedError, match="s3"):
        resolve_workspace("s3://bucket/foo")


def test_resolve_workspace_gs_raises_not_implemented() -> None:
    """``gs://`` URIs are accepted at the type level but rejected at runtime."""
    with pytest.raises(NotImplementedError, match="gs"):
        resolve_workspace("gs://bucket/foo")


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
