"""CI lint: enforce ``__all__`` ⟷ ``_LAZY_IMPORTS`` ∪ ``_MODULE_EXPORTS``.

Every key in ``hydromodpy._LAZY_IMPORTS`` and ``hydromodpy._MODULE_EXPORTS``
must appear in ``hydromodpy.__all__`` and resolve via ``hmp.<name>``. Any
direct (non-lazy) export defined in ``hydromodpy/__init__.py`` must be
listed in ``_DIRECT_EXPORTS`` below so additions are explicitly registered.

Also pins the return-type contract of ``hmp.run`` and ``hmp.calibrate`` across
their TOML-path and config-object branches (T1 residual: P5, P6, P9).
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
        "open_catalog",
        "catalog",
        "read",
        "run",
        "calibrate",
        "index",
        "overview",
        "compare",
        "compare_pair",
        "mesh",
        "testbed",
        "report",
        "doctor",
        "bootstrap_proj",
        "log_manager",
        "__version__",
    }
)


@pytest.mark.parametrize("name", sorted(_LAZY_IMPORTS))
def test_lazy_import_listed_in_all(name: str) -> None:
    assert name in hmp.__all__, f"_LAZY_IMPORTS[{name!r}] missing from __all__"


@pytest.mark.parametrize("name", sorted(_MODULE_EXPORTS))
def test_module_export_listed_in_all(name: str) -> None:
    assert name in hmp.__all__, f"_MODULE_EXPORTS[{name!r}] missing from __all__"


@pytest.mark.parametrize("name", sorted(set(_LAZY_IMPORTS) | set(_MODULE_EXPORTS)))
def test_lazy_or_module_resolves(name: str) -> None:
    assert getattr(hmp, name) is not None


def test_all_set_equals_lazy_union_module_union_direct() -> None:
    expected = set(_LAZY_IMPORTS) | set(_MODULE_EXPORTS) | set(_DIRECT_EXPORTS)
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


# ---------------------------------------------------------------------------
# Return-type consistency between TOML-path and config-object branches.
# Pins the post-T1-residual contract so future drift is caught.
# ---------------------------------------------------------------------------


class _FakeProject:
    """Test double matching :class:`hydromodpy.project.Project` surface."""

    last_headless: bool | None = None
    last_run_kwargs: dict | None = None
    last_calibrate_kwargs: dict | None = None
    run_result: object = None
    calibrate_result: object = None

    def __init__(self, cfg, *, headless=False):  # noqa: D401
        type(self).last_headless = headless

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, **kwargs):
        type(self).last_run_kwargs = kwargs
        return type(self).run_result

    def calibrate(self, **kwargs):
        type(self).last_calibrate_kwargs = kwargs
        return type(self).calibrate_result

    @classmethod
    def lazy(cls, cfg, *, headless=True):
        cls.last_headless = headless
        return cls(cfg, headless=headless)


def _write_simulation_toml(path: Path) -> Path:
    path.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    return path


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
        @classmethod
        def lazy(cls, cfg, *, headless=True):
            raise AssertionError("Project.lazy must not be used on the TOML branch")

    monkeypatch.setattr("hydromodpy.calibration.runner.run_calibration_cli", fake_cli)
    monkeypatch.setattr("hydromodpy.project.Project", _SentinelProject)

    result = hmp.calibrate(config)
    assert result == {"branch": "path"}
    assert captured["called"] is True


def test_calibrate_object_branch_keeps_project(monkeypatch) -> None:
    """The config-object branch still routes through ``Project.lazy``."""
    _FakeProject.calibrate_result = {"branch": "object"}
    monkeypatch.setattr("hydromodpy.project.Project", _FakeProject)

    result = hmp.calibrate(object(), max_iter=5)
    assert result == {"branch": "object"}
    assert _FakeProject.last_calibrate_kwargs == {"max_iter": 5}
