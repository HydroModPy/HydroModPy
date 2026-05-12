"""Unit tests for the XDG-compliant path helpers in ``hydromodpy.core.state.paths``."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import pytest

from hydromodpy.core.state.paths import bin_dir, cache_dir, state_dir


def test_cache_dir_defaults_to_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without override, cache_dir resolves to platformdirs user_cache_dir."""
    monkeypatch.delenv("HMP_CACHE_HOME", raising=False)
    assert cache_dir() == Path(platformdirs.user_cache_dir("hydromodpy"))


def test_state_dir_defaults_to_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without override, state_dir resolves to platformdirs user_state_dir."""
    monkeypatch.delenv("HMP_STATE_HOME", raising=False)
    assert state_dir() == Path(platformdirs.user_state_dir("hydromodpy"))


def test_bin_dir_includes_solver_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """bin_dir(solver, version) nests under cache_dir / bin / solver / version."""
    monkeypatch.delenv("HMP_CACHE_HOME", raising=False)
    monkeypatch.delenv("HMP_BIN", raising=False)
    expected = Path(platformdirs.user_cache_dir("hydromodpy")) / "bin" / "mf6" / "6.4.1"
    assert bin_dir("mf6", "6.4.1") == expected


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


def test_bin_dir_respects_hmp_bin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """HMP_BIN sets the parent of <solver>/<version>."""
    custom = tmp_path / "custom_bin"
    monkeypatch.setenv("HMP_BIN", str(custom))
    expected = custom.resolve() / "mf6" / "6.4.1"
    assert bin_dir("mf6", "6.4.1") == expected


def test_paths_expand_user_in_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override env vars expand ``~`` to the user's home directory."""
    monkeypatch.setenv("HMP_CACHE_HOME", "~/foo_cache_override")
    monkeypatch.setenv("HMP_STATE_HOME", "~/foo_state_override")
    monkeypatch.setenv("HMP_BIN", "~/foo_bin_override")
    expected_cache = (Path.home() / "foo_cache_override").resolve()
    expected_state = (Path.home() / "foo_state_override").resolve()
    expected_bin = (Path.home() / "foo_bin_override").resolve() / "mf6" / "6.4.1"
    assert cache_dir() == expected_cache
    assert state_dir() == expected_state
    assert bin_dir("mf6", "6.4.1") == expected_bin


def test_paths_have_no_side_effects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Helpers never create directories on import or at call time."""
    custom_cache = tmp_path / "no_mkdir_cache"
    custom_state = tmp_path / "no_mkdir_state"
    custom_bin = tmp_path / "no_mkdir_bin"
    monkeypatch.setenv("HMP_CACHE_HOME", str(custom_cache))
    monkeypatch.setenv("HMP_STATE_HOME", str(custom_state))
    monkeypatch.setenv("HMP_BIN", str(custom_bin))
    cache_dir()
    state_dir()
    bin_dir("mf6", "6.4.1")
    assert not custom_cache.exists()
    assert not custom_state.exists()
    assert not custom_bin.exists()
