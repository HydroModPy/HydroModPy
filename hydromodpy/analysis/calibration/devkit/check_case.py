"""
Validate a calibration case package before running larger experiments.

This module focuses on fast feedback for case authors. It checks:
- folder/file structure,
- `CASE_IMPLEMENTATION` availability and interface compliance,
- TOML configuration loadability,
- optional end-to-end smoke run.

Who should call this helper
---------------------------
- Developers right after `scaffold_case(...)` and first edits,
- reviewers before merging case refactors,
- CI/unit tests for quick structural assurance.

When to call it
---------------
- before expensive calibration runs,
- after renaming/moving case files,
- after changing the case interface contract in `core/`.

Practical output contract
-------------------------
`check_case(...)` always returns a report dictionary, even on failure, so
tooling/tests can inspect:
- global status (`ok`),
- blocking issues (`errors`),
- non-blocking inconsistencies (`warnings`),
- detailed step diagnostics (`checks`).
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from hydromodpy.analysis.calibration.core.case_interface import validate_case_implementation
from hydromodpy.analysis.calibration.core.case_orchestrator import run_calibration_case_from_toml
from hydromodpy.analysis.calibration.core.engine_config import load_calibration_toml


_REQUIRED_CASE_FILES = (
    "__init__.py",
    "README.md",
    "case_config.py",
    "workflow.py",
    "case_implementation.py",
    "run_calibration.py",
)
# Minimal files expected for a runnable, documented case package.

_PREFERRED_CONFIG_FILENAMES = (
    "config_calibration.toml",
    "config_calibration_two_reservoir.toml",
    "config_calibration_one_reservoir.toml",
)


def _calibration_root() -> Path:
    """Return absolute path to `hydromodpy/analysis/calibration/`."""
    return Path(__file__).resolve().parents[1]


def _default_cases_root() -> Path:
    """Return default root where calibration cases are stored."""
    return _calibration_root() / "cases"


def _as_case_name(case_name: str) -> str:
    """Normalize and validate a case key used in paths/imports."""
    name = str(case_name).strip().lower()
    if not name:
        raise ValueError("case_name cannot be empty")
    return name


def _case_path(case_name: str, *, cases_root: Path) -> Path:
    """Resolve filesystem path for a case under `cases_root`."""
    return Path(cases_root) / case_name


def _check_required_files(case_dir: Path) -> dict[str, Any]:
    """Check that a case directory contains the expected minimal file set."""
    missing = [name for name in _REQUIRED_CASE_FILES if not (case_dir / name).exists()]
    return {
        "ok": len(missing) == 0,
        "missing": tuple(missing),
    }


def _check_case_implementation(case_name: str) -> dict[str, Any]:
    """Import `case_implementation` module and validate `CASE_IMPLEMENTATION`."""
    module_path = f"hydromodpy.analysis.calibration.cases.{case_name}.case_implementation"
    module = import_module(module_path)
    if not hasattr(module, "CASE_IMPLEMENTATION"):
        raise AttributeError(
            f"Module '{module_path}' does not define CASE_IMPLEMENTATION"
        )
    case_implementation = getattr(module, "CASE_IMPLEMENTATION")
    canonical = validate_case_implementation(case_implementation)
    return {
        "ok": True,
        "module_path": module_path,
        "canonical_case_name": canonical,
        "class_name": case_implementation.__class__.__name__,
    }


def _discover_default_config(case_dir: Path) -> Path | None:
    """
    Resolve one calibration TOML path for checks/smoke execution.

    Preference order:
    1) known canonical names,
    2) first `config_calibration*.toml` match.
    """
    for filename in _PREFERRED_CONFIG_FILENAMES:
        candidate = case_dir / filename
        if candidate.exists():
            return candidate

    candidates = sorted(case_dir.glob("config_calibration*.toml"))
    if len(candidates) > 0:
        return candidates[0]
    return None


def _check_config_loadable(config_path: Path) -> dict[str, Any]:
    """Validate that the case TOML can be parsed by core schema validators."""
    config_data = load_calibration_toml(config_path)
    return {
        "ok": True,
        "keys": tuple(sorted(config_data.keys())),
    }


def check_case(
    case_name: str,
    *,
    cases_root: str | Path | None = None,
    run_smoke: bool = False,
    smoke_method_override: str | None = None,
) -> dict[str, Any]:
    """
    Run structural checks for one case and return a machine-readable report.

    Report format
    -------------
    - `ok`: global pass/fail flag.
    - `errors`: hard failures preventing execution.
    - `warnings`: non-blocking inconsistencies.
    - `checks`: detailed per-step diagnostics.

    Parameters
    ----------
    case_name : str
        Case folder / module key.
    cases_root : str | Path | None
        Custom root containing case directories. Defaults to calibration cases.
    run_smoke : bool
        When ``True``, execute one calibration run from the case TOML.
    smoke_method_override : str | None
        Optional method override used for smoke execution.
    """
    # Build deterministic target paths first; all checks operate from there.
    normalized_name = _as_case_name(case_name)
    root = _default_cases_root() if cases_root is None else Path(cases_root)
    case_dir = _case_path(normalized_name, cases_root=root)

    report: dict[str, Any] = {
        "case_name": normalized_name,
        "case_dir": str(case_dir),
        "ok": True,
        "errors": [],
        "warnings": [],
        "checks": {},
    }

    if not case_dir.exists():
        report["ok"] = False
        report["errors"].append(f"Case directory does not exist: {case_dir}")
        return report

    # 1) Fast static check: required files in place.
    required = _check_required_files(case_dir)
    report["checks"]["required_files"] = required
    if not required["ok"]:
        report["ok"] = False
        report["errors"].append(
            "Missing required files: " + ", ".join(required["missing"])
        )

    # 2) Import/runtime contract check for `CASE_IMPLEMENTATION`.
    try:
        implementation = _check_case_implementation(normalized_name)
    except Exception as exc:  # pragma: no cover - covered by direct behavior tests
        report["ok"] = False
        report["checks"]["implementation"] = {"ok": False}
        report["errors"].append(f"Implementation check failed: {exc}")
        implementation = None
    else:
        report["checks"]["implementation"] = implementation
        if implementation["canonical_case_name"] != normalized_name:
            report["warnings"].append(
                "CASE_NAME differs from folder name: "
                f"{implementation['canonical_case_name']} != {normalized_name}"
            )

    # 3) Parse and validate default TOML.
    config_path = _discover_default_config(case_dir)
    if config_path is not None and config_path.exists():
        try:
            config_report = _check_config_loadable(config_path)
        except Exception as exc:
            report["ok"] = False
            report["checks"]["config"] = {"ok": False}
            report["errors"].append(f"Config load failed: {exc}")
        else:
            config_report["config_path"] = str(config_path)
            report["checks"]["config"] = config_report
    else:
        report["warnings"].append("No config_calibration*.toml file found")

    # 4) Optional smoke execution: verifies end-to-end wiring using the same
    # orchestrator used by production scripts.
    if run_smoke and report["ok"] and implementation is not None:
        if config_path is None:
            report["ok"] = False
            report["checks"]["smoke"] = {"ok": False}
            report["errors"].append("Smoke execution failed: no calibration TOML found")
            return report
        try:
            # Re-import the concrete implementation from module path to ensure
            # smoke execution validates the same import path used in scripts.
            payload = run_calibration_case_from_toml(
                config_path=config_path,
                case_implementation=import_module(
                    f"hydromodpy.analysis.calibration.cases.{normalized_name}.case_implementation"
                ).CASE_IMPLEMENTATION,
                method_override=smoke_method_override,
            )
            report["checks"]["smoke"] = {
                "ok": True,
                "method": str(payload.get("method")),
                "objective_metric": str(payload.get("objective_metric")),
                "n_evaluations": int(payload["result"].n_evaluations),
            }
        except Exception as exc:
            report["ok"] = False
            report["checks"]["smoke"] = {"ok": False}
            report["errors"].append(f"Smoke execution failed: {exc}")

    return report


__all__ = (
    "check_case",
)

