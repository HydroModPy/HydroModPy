"""
Environment and integration diagnostics for calibration2.

What this module does
---------------------
`run_doctor()` builds a compact health report for the current Python runtime:
1) verifies importability of core dependencies (`numpy`, `pydantic`),
2) reports availability of optional dependencies (`scipy`, `sklearn`, `matplotlib`),
3) lists calibration methods currently registered in the dispatcher,
4) discovers case implementations and validates their interface contract.

Who should run it
-----------------
- Developers onboarding on calibration2 for the first time,
- contributors after dependency/environment updates,
- maintainers before running case scripts on a new machine.

When to run it
--------------
- Right after environment creation / package installation,
- before debugging a failing case import or missing-method issue,
- after pulling major refactors touching `core/` or `cases/`.

Is it run automatically?
-----------------------
- Not by calibration runtime scripts (`run_calibration.py` does not call it).
- It *is* exercised in unit tests as a structural smoke check
  (`tests/unit/calibration/test_calibration2_devkit.py`), mainly to ensure
  report shape and discovery logic remain stable.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import platform
import sys
from typing import Any

from hydromodpy.calibration.core.case_interface import validate_case_implementation
from hydromodpy.calibration.core.methods_dispatcher import DEFAULT_CALIBRATION_METHOD


_CORE_MODULES = (
    "numpy",
    "pydantic",
)

_OPTIONAL_MODULES = (
    "scipy",
    "sklearn",
    "matplotlib",
)


def _calibration2_root() -> Path:
    """Return absolute path to `hydromodpy/calibration2/`."""
    return Path(__file__).resolve().parents[1]


def _import_status(module_name: str) -> dict[str, Any]:
    """Return import health + version info for one module name."""
    try:
        module = import_module(module_name)
    except Exception as exc:
        return {
            "ok": False,
            "version": None,
            "error": str(exc),
        }
    version = getattr(module, "__version__", None)
    return {
        "ok": True,
        "version": None if version is None else str(version),
        "error": None,
    }


def _discover_case_names() -> tuple[str, ...]:
    """List case folders that expose `case_implementation.py`."""
    cases_dir = _calibration2_root() / "cases"
    if not cases_dir.exists():
        return ()

    discovered: list[str] = []
    for path in sorted(cases_dir.iterdir()):
        if not path.is_dir():
            continue
        if path.name.startswith("_"):
            continue
        if (path / "case_implementation.py").exists():
            discovered.append(path.name)
    return tuple(discovered)


def _case_status(case_name: str) -> dict[str, Any]:
    """Validate one case implementation import and interface compliance."""
    module_path = f"hydromodpy.calibration.cases.{case_name}.case_implementation"
    try:
        module = import_module(module_path)
        implementation = getattr(module, "CASE_IMPLEMENTATION")
        canonical = validate_case_implementation(implementation)
    except Exception as exc:
        return {
            "ok": False,
            "module_path": module_path,
            "class_name": None,
            "canonical_case_name": None,
            "error": str(exc),
        }
    return {
        "ok": True,
        "module_path": module_path,
        "class_name": implementation.__class__.__name__,
        "canonical_case_name": canonical,
        "error": None,
    }


def run_doctor() -> dict[str, Any]:
    """
    Collect a lightweight health report for calibration2 runtime and cases.

    Returns
    -------
    dict
        Structured report with sections:
        - `python`: interpreter/runtime metadata,
        - `modules`: import status for core/optional dependencies,
        - `methods`: available calibration method names,
        - `cases`: per-case implementation health.
    """
    # Dependency readiness.
    module_status = {
        "core": {name: _import_status(name) for name in _CORE_MODULES},
        "optional": {name: _import_status(name) for name in _OPTIONAL_MODULES},
    }

    # Runtime-discovered capabilities from the active environment.
    methods = DEFAULT_CALIBRATION_METHOD.available_methods()
    case_names = _discover_case_names()
    cases = {name: _case_status(name) for name in case_names}

    ok = all(item["ok"] for item in module_status["core"].values()) and all(
        item["ok"] for item in cases.values()
    )

    return {
        "ok": bool(ok),
        "python": {
            "version": str(sys.version).split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "modules": module_status,
        "methods": methods,
        "cases": cases,
    }


def format_doctor_report(report: dict[str, Any]) -> str:
    """
    Convert `run_doctor()` output to a readable multiline text report.

    This helper is intentionally presentation-only: it does not mutate or
    validate the incoming report payload.
    """
    lines: list[str] = []
    lines.append("Calibration2 doctor report")
    lines.append(f"Overall status: {'OK' if report.get('ok') else 'FAILED'}")

    py = dict(report.get("python", {}))
    lines.append(
        f"Python: {py.get('version', '?')} ({py.get('platform', '?')})"
    )
    lines.append(f"Executable: {py.get('executable', '?')}")

    modules = dict(report.get("modules", {}))
    lines.append("Core modules:")
    for name, status in dict(modules.get("core", {})).items():
        if status.get("ok"):
            version = status.get("version") or "unknown"
            lines.append(f"  - {name}: OK (version={version})")
        else:
            lines.append(f"  - {name}: FAIL ({status.get('error')})")

    lines.append("Optional modules:")
    for name, status in dict(modules.get("optional", {})).items():
        if status.get("ok"):
            version = status.get("version") or "unknown"
            lines.append(f"  - {name}: OK (version={version})")
        else:
            lines.append(f"  - {name}: missing ({status.get('error')})")

    methods = tuple(report.get("methods", ()))
    lines.append("Available methods:")
    lines.append("  - " + ", ".join(methods) if methods else "  - <none>")

    lines.append("Cases:")
    cases = dict(report.get("cases", {}))
    if not cases:
        lines.append("  - <none>")
    else:
        for name, status in sorted(cases.items()):
            if status.get("ok"):
                lines.append(
                    f"  - {name}: OK "
                    f"(class={status.get('class_name')}, canonical={status.get('canonical_case_name')})"
                )
            else:
                lines.append(f"  - {name}: FAIL ({status.get('error')})")

    return "\n".join(lines)


__all__ = (
    "run_doctor",
    "format_doctor_report",
)

