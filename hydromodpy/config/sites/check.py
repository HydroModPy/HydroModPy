"""One check for every file ``hmp run`` or ``hmp calibrate`` would take.

``hmp config check <toml>`` validates a run, a calibration or a whole
``[sites]`` project with the same verb. A run is loaded and the checks of
step 0 of ``hmp run`` are made (a date outside the record, an export name no
run holds). A calibration is loaded and read by the preflight of the
calibration package. A ``[sites]`` project is expanded case by case, and the
issues come back grouped, each at the cell or the file it comes from.
"""

from __future__ import annotations

import tomllib
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hydromodpy.config.sites.expansion import SitesProjectError, expand_plan, find_sites_file
from hydromodpy.config.sites.issues import group_issues
from hydromodpy.core.config_kit.written import written_experimental_keys
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.core.toml_io.loader import merge_toml_chain, read_toml_chain
from hydromodpy.workflow.dispatch import (
    WorkflowError,
    check_workflow_name,
    extract_workflow_field,
)

CheckKind = Literal["simulation", "calibration", "sites"]


@dataclass(frozen=True, slots=True)
class CheckReport:
    """What the check found: the kind of file, its errors, its warnings, its experimental keys."""

    path: Path
    kind: CheckKind
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    n_cases: int | None = None
    experimental_keys: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether nothing stops the file from running."""
        return not self.errors

    def summary(self) -> str:
        """Return the one line that ends the check."""
        if self.kind == "sites":
            head = f"{self.n_cases} case(s)"
            return (
                f"OK: {self.path} ({head})" if self.ok else f"Config invalid: {self.path} ({head})"
            )
        return f"OK: {self.path}" if self.ok else f"Config invalid: {self.path}"

    def lines(self) -> list[str]:
        """Return the findings, errors first, one per line."""
        return [f"  {line}" for line in (*self.errors, *(f"warning: {w}" for w in self.warnings))]


def check_project(path: str | Path) -> CheckReport:
    """Check *path* as the file it is: a run, a calibration or a ``[sites]`` project.

    A check reports, it never crashes the verb: an error no check expected
    comes back as a finding too, so ``hmp config check`` always ends on its
    summary line and its exit code.
    """
    target = Path(path).expanduser().resolve()
    try:
        return _check(target)
    except Exception as exc:  # noqa: BLE001 - every failure of a check is a finding
        return CheckReport(path=target, kind="simulation", errors=(f"Config check failed: {exc}",))


def _check(target: Path) -> CheckReport:
    try:
        # As written: the load below says the old forms, and the report collects them.
        chain = read_toml_chain(target, migrate=False)
    except tomllib.TOMLDecodeError as exc:
        return CheckReport(path=target, kind="simulation", errors=(f"Invalid TOML syntax: {exc}",))
    except (TypeError, ValueError, OSError) as exc:
        return CheckReport(
            path=target, kind="simulation", errors=(f"Invalid base_config chain: {exc}",)
        )
    try:
        sites_file = find_sites_file(chain)
    except SitesProjectError as exc:
        return CheckReport(path=target, kind="sites", errors=(str(exc),))
    if sites_file is not None:
        return _check_sites_project(target)
    document = merge_toml_chain(chain, migrate=False)
    try:
        declared = extract_workflow_field(document)
        if declared is not None:
            check_workflow_name(declared)
    except WorkflowError as exc:
        return CheckReport(path=target, kind="simulation", errors=(str(exc),))
    if "calibration" in document:
        return _check_calibration(target)
    return _check_run(target)


def _check_sites_project(target: Path) -> CheckReport:
    try:
        draft = expand_plan(resolve_project_root(target.parent), target)
    except ConfigError as exc:
        return CheckReport(path=target, kind="sites", errors=(str(exc),))
    return CheckReport(
        path=target,
        kind="sites",
        errors=tuple(group_issues(draft.errors)),
        warnings=tuple(group_issues(draft.warnings)),
        n_cases=len(draft.cases),
        experimental_keys=tuple(
            dict.fromkeys(key for case in draft.cases for key in case.experimental_keys)
        ),
    )


def _load(target: Path) -> tuple[Any, list[str], list[str]]:
    """Load the configuration; return it with the errors and warnings of loading."""
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning, forget_old_forms_told

    errors: list[str] = []
    cfg = None
    forget_old_forms_told()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConfigKeyRenamedWarning)
        warnings.simplefilter("always", UserWarning)
        try:
            cfg = HydroModPyConfig.from_toml(target)
        except (ConfigError, ValueError, KeyError, FileNotFoundError) as exc:
            errors.append(str(exc))
    noted = [str(item.message) for item in caught if item.category is not DeprecationWarning]
    return cfg, errors, noted


def _check_run(target: Path) -> CheckReport:
    from hydromodpy.config.export_checks import check_export_variables, check_time_selectors

    cfg, errors, noted = _load(target)
    if cfg is not None:
        for check in (check_export_variables, check_time_selectors):
            try:
                check(cfg)
            except (ConfigError, ValueError) as exc:
                errors.append(str(exc))
    return CheckReport(
        path=target,
        kind="simulation",
        errors=tuple(errors),
        warnings=tuple(noted),
        experimental_keys=() if cfg is None else written_experimental_keys(cfg),
    )


def _check_calibration(target: Path) -> CheckReport:
    from hydromodpy.calibration.preflight import preflight_calibration

    cfg, errors, noted = _load(target)
    if cfg is not None:
        for finding in preflight_calibration(cfg, source=target):
            text = f"{finding.where}: {finding.detail}"
            if finding.severity == "error":
                errors.append(text)
            else:
                noted.append(text)
    return CheckReport(
        path=target,
        kind="calibration",
        errors=tuple(errors),
        warnings=tuple(noted),
        experimental_keys=() if cfg is None else written_experimental_keys(cfg),
    )


def report_lines(report: CheckReport) -> Sequence[str]:
    """Return the summary and the findings, ready to print."""
    return [report.summary(), *report.lines()]


__all__ = ["CheckKind", "CheckReport", "check_project", "report_lines"]
