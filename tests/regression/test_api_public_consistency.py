"""CI lint: ``__all__`` is the lazy names and the direct names, and each one resolves.

Any direct (non-lazy) export defined in ``hydromodpy/__init__.py`` must be listed in
``_DIRECT_EXPORTS`` below so additions are explicitly registered. A package opened by
``hmp.<name>`` stays out of ``__all__``.

Also pins that ``hmp.calibrate`` takes one route per source of the configuration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy import _LAZY_IMPORTS, _MODULE_EXPORTS

pytestmark = [pytest.mark.regression, pytest.mark.fast]


# Symbols defined inline in ``hydromodpy/__init__.py`` (not via lazy import or
# module re-export). Adding or removing one here is a deliberate API change.
_DIRECT_EXPORTS = frozenset(
    {
        "open",
        "index",
        "read",
        "example_add",
        "example_list",
        "example_show",
        "export",
        "figure",
        "run",
        "calibrate",
        "calibration_phases",
        "compare",
        "spinup",
        "compare_pair",
        "report",
        "doctor",
        "__version__",
    }
)


@pytest.mark.parametrize("name", sorted(_LAZY_IMPORTS))
def test_lazy_import_listed_in_all(name: str) -> None:
    assert name in hmp.__all__, f"_LAZY_IMPORTS[{name!r}] missing from __all__"


@pytest.mark.parametrize("name", sorted(_MODULE_EXPORTS))
def test_a_package_stays_out_of_all_and_opens(name: str) -> None:
    assert name not in hmp.__all__
    assert getattr(hmp, name).__name__ == f"hydromodpy.{name}"


@pytest.mark.parametrize("name", sorted(_LAZY_IMPORTS))
def test_lazy_name_resolves(name: str) -> None:
    assert getattr(hmp, name) is not None


def test_all_set_equals_lazy_union_module_union_direct() -> None:
    expected = set(_LAZY_IMPORTS) | set(_DIRECT_EXPORTS)
    actual = set(hmp.__all__)
    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        f"__all__ drift detected. missing={sorted(missing)} extra={sorted(extra)}"
    )


def test_all_has_no_duplicates() -> None:
    assert len(hmp.__all__) == len(set(hmp.__all__))


def test_lazy_and_module_keys_disjoint() -> None:
    overlap = set(_LAZY_IMPORTS) & set(_MODULE_EXPORTS)
    assert not overlap, f"keys present in both _LAZY_IMPORTS and _MODULE_EXPORTS: {sorted(overlap)}"


class _FakeProject:
    """Test double matching the :class:`hydromodpy.project.Project` surface."""

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
    monkeypatch.setattr("hydromodpy.project.Project", _SentinelProject)

    result = hmp.calibrate(config)
    assert result == {"branch": "path"}
    assert captured["called"] is True


def test_calibrate_object_branch_keeps_project(monkeypatch) -> None:
    """The config-object branch still routes through a ``Project`` context."""
    _FakeProject.calibrate_result = {"branch": "object"}
    monkeypatch.setattr("hydromodpy.project.Project", _FakeProject)

    result = hmp.calibrate(object(), max_trials=5)
    assert result == {"branch": "object"}
    assert _FakeProject.last_calibrate_kwargs == {"max_trials": 5}
    assert _FakeProject.last_environment is None
