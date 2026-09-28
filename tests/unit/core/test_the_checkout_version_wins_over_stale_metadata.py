"""An editable install reports the version of the checkout, not the one it was installed at."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest

from hydromodpy.core import version as version_module

pytestmark = pytest.mark.unit


def _write_pyproject(path: Path, *, name: str, version: str) -> Path:
    path.write_text(f'[project]\nname = "{name}"\nversion = "{version}"\n', encoding="utf-8")
    return path


def test_the_checkout_pyproject_wins_over_the_installed_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(version_module.metadata, "version", lambda _name: "2.0.0a1")
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", name="hydromodpy", version="2.0.0a2")

    assert version_module._read_version(pyproject) == "2.0.0a2"


def test_a_wheel_without_pyproject_reads_the_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(version_module.metadata, "version", lambda _name: "2.0.0a1")

    assert version_module._read_version(tmp_path / "pyproject.toml") == "2.0.0a1"


def test_a_foreign_pyproject_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_module.metadata, "version", lambda _name: "2.0.0a1")
    pyproject = _write_pyproject(tmp_path / "pyproject.toml", name="site", version="9.9.9")

    assert version_module._read_version(pyproject) == "2.0.0a1"


def test_nothing_installed_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing(_name: str) -> str:
        raise metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(version_module.metadata, "version", _missing)

    assert version_module._read_version(tmp_path / "pyproject.toml") == (
        version_module._FALLBACK_VERSION
    )


def test_this_checkout_reports_its_pyproject_version() -> None:
    assert version_module.__version__ == version_module._checkout_version(
        version_module._CHECKOUT_PYPROJECT
    )
