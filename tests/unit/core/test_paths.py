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
    cache_dir,
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
    (root / "simulations").mkdir(parents=True)
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def test_resolve_project_root_walks_up_to_the_marker(tmp_path: Path) -> None:
    """Any directory under the project resolves to the marker directory."""
    root = _project(tmp_path)
    assert resolve_project_root(root) == root
    assert resolve_project_root(root / "simulations") == root


def test_resolve_project_root_ignores_a_missing_catalog(tmp_path: Path) -> None:
    """Deleting the DuckDB index leaves the root resolution untouched."""
    root = _project(tmp_path)
    catalog = root / CATALOG_FILENAME
    catalog.write_bytes(b"")
    assert resolve_project_root(root / "simulations") == root
    catalog.unlink()
    assert resolve_project_root(root / "simulations") == root


def test_resolve_project_root_is_not_anchored_by_a_catalog(tmp_path: Path) -> None:
    """A catalog without a marker never anchors a root above the start."""
    root = tmp_path / "legacy"
    (root / "simulations").mkdir(parents=True)
    (root / CATALOG_FILENAME).write_bytes(b"")
    assert resolve_project_root(root / "simulations") == root / "simulations"


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
