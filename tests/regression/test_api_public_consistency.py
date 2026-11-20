"""CI lint: ``__all__`` is the lazy names and ``__version__``, and each one resolves.

Every verb, object and category of ``hydromodpy`` is reached through
``LAZY_IMPORTS``, so an addition is an explicit edit of ``hydromodpy/_lazy.py``. A
package of the tree is never opened by ``hmp.<name>``.

Also pins that ``hmp.calibrate`` takes one route per source of the configuration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy._lazy import LAZY_IMPORTS

pytestmark = [pytest.mark.regression, pytest.mark.fast]

PACKAGES = ("calibration", "config", "core", "data", "results", "solver", "workflow")


@pytest.mark.parametrize("name", sorted(LAZY_IMPORTS))
def test_lazy_import_listed_in_all(name: str) -> None:
    assert name in hmp.__all__, f"LAZY_IMPORTS[{name!r}] missing from __all__"


@pytest.mark.parametrize("name", PACKAGES)
def test_a_package_stays_out_of_all_and_out_of_the_lazy_table(name: str) -> None:
    assert name not in hmp.__all__
    assert name not in LAZY_IMPORTS


@pytest.mark.parametrize("name", sorted(LAZY_IMPORTS))
def test_lazy_name_resolves(name: str) -> None:
    assert getattr(hmp, name) is not None


def test_all_set_equals_the_lazy_names_and_the_version() -> None:
    expected = set(LAZY_IMPORTS) | {"__version__"}
    actual = set(hmp.__all__)
    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        f"__all__ drift detected. missing={sorted(missing)} extra={sorted(extra)}"
    )


def test_all_has_no_duplicates() -> None:
    assert len(hmp.__all__) == len(set(hmp.__all__))


def test_every_lazy_value_names_core_or_project() -> None:
    homes = {target.split(":", 1)[0] for target in LAZY_IMPORTS.values()}
    assert homes == {
        "hydromodpy.project.api",
        "hydromodpy.project.kept_readers",
        "hydromodpy.core.exceptions",
    }


class _FakeProject:
    """Test double matching the :class:`hydromodpy.project.facade.Project` surface."""

    last_headless: bool | None = None
    last_environment: object = None
    last_calibrate_kwargs: dict | None = None
    calibrate_result: object = None

    def __init__(self, cfg, *, headless=False, environment=None):  # noqa: D401
        type(self).last_headless = headless
        type(self).last_environment = environment

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def calibrate(self, **kwargs):
        type(self).last_calibrate_kwargs = kwargs
        return type(self).calibrate_result


def test_calibrate_path_skips_project_detour(monkeypatch, tmp_path: Path) -> None:
    """The path branch calls ``run_calibration_cli`` directly (P6)."""
    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    captured: dict = {}

    def fake_cli(config_path, **kwargs):
        captured["called"] = True
        captured["kwargs"] = kwargs
        return {"branch": "path"}

    class _SentinelProject(_FakeProject):
        def __init__(self, *a, **k):
            raise AssertionError("Project must not be constructed on the TOML branch")

    monkeypatch.setattr("hydromodpy.calibration.runners.cli_runner.run_calibration_cli", fake_cli)
    monkeypatch.setattr("hydromodpy.project.api.Project", _SentinelProject)

    result = hmp.calibrate(config)
    assert result == {"branch": "path"}
    assert captured["called"] is True


def test_calibrate_object_branch_keeps_project(monkeypatch) -> None:
    """The config-object branch still routes through a ``Project`` context."""
    _FakeProject.calibrate_result = {"branch": "object"}
    monkeypatch.setattr("hydromodpy.project.api.Project", _FakeProject)

    result = hmp.calibrate(object(), max_trials=5)
    assert result == {"branch": "object"}
    assert _FakeProject.last_calibrate_kwargs == {"max_trials": 5}
    assert _FakeProject.last_environment is None
