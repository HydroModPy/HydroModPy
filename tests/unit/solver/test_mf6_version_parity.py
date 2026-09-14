"""The libmf6/exe version-parity warning (finding 6).

The api runner solves with libmf6 while the subprocess runner and the per-trial
steady-state init use the exe, so a version skew is surfaced once, loudly.
"""

from __future__ import annotations

import pytest

import hydromodpy.solver.modflow_common.binaries as binaries


@pytest.fixture
def warnings(monkeypatch):
    """Reset the once-guard and capture logger.warning calls (routing-agnostic)."""
    monkeypatch.setattr(binaries, "_MF6_VERSION_PARITY_CHECKED", False, raising=False)
    monkeypatch.delenv(binaries._MISMATCH_ENV_VAR, raising=False)
    calls: list[tuple] = []
    monkeypatch.setattr(binaries.logger, "warning", lambda *a, **k: calls.append(a))
    return calls


def _patch_versions(monkeypatch, exe: str | None, lib: str | None) -> None:
    monkeypatch.setattr(binaries, "mf6_executable_version", lambda _p: exe)
    monkeypatch.setattr(binaries, "libmf6_version", lambda _p: lib)


def test_mismatch_warns_once(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, "6.6.3", "6.7.0")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")  # once-only guard
    assert len(warnings) == 1
    assert "6.6.3" in warnings[0] and "6.7.0" in warnings[0]


def test_matching_major_minor_is_silent(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, "6.6.3", "6.6.1")  # same major.minor
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    assert warnings == []


def test_env_var_silences_the_mismatch(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, "6.6.3", "6.7.0")
    monkeypatch.setenv(binaries._MISMATCH_ENV_VAR, "1")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    assert warnings == []


def test_unknown_version_does_not_warn(monkeypatch, warnings) -> None:
    _patch_versions(monkeypatch, None, "6.7.0")
    binaries.warn_on_mf6_version_mismatch("mf6", "libmf6.so")
    assert warnings == []


def test_solver_python_stack_reports_both_wrappers() -> None:
    stack = binaries.solver_python_stack()
    assert "modflowapi" in stack and "xmipy" in stack


def test_solver_python_stack_flags_dev_editable(monkeypatch) -> None:
    monkeypatch.setattr(
        binaries,
        "_package_version_and_editable",
        lambda name: ("0.3.0.dev0", True) if name == "modflowapi" else ("1.5.0", False),
    )
    stack = binaries.solver_python_stack()
    assert "modflowapi 0.3.0.dev0 (editable)" in stack
    assert "xmipy 1.5.0" in stack and "xmipy 1.5.0 (editable)" not in stack


def test_solver_python_stack_marks_absent(monkeypatch) -> None:
    monkeypatch.setattr(binaries, "_package_version_and_editable", lambda _name: (None, False))
    assert binaries.solver_python_stack() == "modflowapi (absent), xmipy (absent)"
