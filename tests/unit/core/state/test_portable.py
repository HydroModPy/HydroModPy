"""Where the cache and the state of the user live, and how a workspace URI becomes a path.

``HMP_CACHE_HOME`` and ``HMP_STATE_HOME`` redirect the two folders. Neither
helper creates a folder.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs
import pytest

from hydromodpy.core.state.portable import cache_dir, resolve_workspace, state_dir


@pytest.mark.parametrize(
    ("dir_fn", "home_env", "platformdirs_fn"),
    [
        (cache_dir, "HMP_CACHE_HOME", platformdirs.user_cache_dir),
        (state_dir, "HMP_STATE_HOME", platformdirs.user_state_dir),
    ],
    ids=["cache", "state"],
)
def test_default_dir(
    dir_fn, home_env: str, platformdirs_fn, monkeypatch: pytest.MonkeyPatch
) -> None:
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
def test_env_override(
    dir_fn, home_env: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom = tmp_path / "custom"
    monkeypatch.setenv(home_env, str(custom))
    assert dir_fn() == custom.resolve()


def test_override_expands_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", "~/foo_cache_override")
    monkeypatch.setenv("HMP_STATE_HOME", "~/foo_state_override")
    expected_cache = (Path.home() / "foo_cache_override").resolve()
    expected_state = (Path.home() / "foo_state_override").resolve()
    assert cache_dir() == expected_cache
    assert state_dir() == expected_state


def test_no_folder_is_created(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom_cache = tmp_path / "no_mkdir_cache"
    custom_state = tmp_path / "no_mkdir_state"
    monkeypatch.setenv("HMP_CACHE_HOME", str(custom_cache))
    monkeypatch.setenv("HMP_STATE_HOME", str(custom_state))
    cache_dir()
    state_dir()
    assert not custom_cache.exists()
    assert not custom_state.exists()


def test_file_uri() -> None:
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
def test_cloud_uri_is_not_implemented(scheme: str, uri: str) -> None:
    with pytest.raises(NotImplementedError, match=scheme):
        resolve_workspace(uri)
