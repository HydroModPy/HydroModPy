"""Post-run stability checks for simulation-comparison outputs."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DEFAULT_REQUIRED_FILES = (
    "comparison_manifest.json",
    "comparison_metrics.json",
    "comparison_audit.json",
    "comparison_report.md",
)


@dataclass(frozen=True)
class ComparisonMetricLimit:
    """Numerical limits for one simulation/observable metric row."""

    simulation_id: str
    observable: str
    limits: dict[str, float]
    n_pairs_min: int | None = None


@dataclass(frozen=True)
class ComparisonStabilityTarget:
    """One comparison output folder and the checks expected from it."""

    case_id: str
    comparison_root: Path
    allowed_audit_status: tuple[str, ...] = ("pass",)
    required_files: tuple[str, ...] = _DEFAULT_REQUIRED_FILES
    required_figures: tuple[str, ...] = ()
    required_simulations: tuple[str, ...] = ()
    metric_limits: tuple[ComparisonMetricLimit, ...] = ()


@dataclass(frozen=True)
class ComparisonStabilityFinding:
    """One stability check result."""

    case_id: str
    level: str
    message: str


@dataclass(frozen=True)
class ComparisonStabilityCaseResult:
    """Aggregated stability result for one comparison case."""

    target: ComparisonStabilityTarget
    findings: tuple[ComparisonStabilityFinding, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(finding.level == "error" for finding in self.findings)


@dataclass(frozen=True)
class ComparisonStabilityReport:
    """Aggregated stability result for one target file."""

    targets_path: Path
    cases: tuple[ComparisonStabilityCaseResult, ...] = ()

    @property
    def ok(self) -> bool:
        return all(case.ok for case in self.cases)


def load_stability_targets(
    targets_path: str | Path,
    *,
    case_ids: Iterable[str] | None = None,
) -> tuple[ComparisonStabilityTarget, ...]:
    """Load comparison stability targets from a TOML file."""
    resolved_path = Path(targets_path).expanduser().resolve()
    raw = tomllib.loads(resolved_path.read_text(encoding="utf-8"))
    selected = None if case_ids is None else {str(case_id) for case_id in case_ids}
    case_payloads = raw.get("case", [])
    if not isinstance(case_payloads, list):
        raise ValueError("Stability target file must define [[case]] entries.")

    targets: list[ComparisonStabilityTarget] = []
    for payload in case_payloads:
        if not isinstance(payload, Mapping):
            raise ValueError("Each [[case]] entry must be a TOML table.")
        if payload.get("enabled", True) is False:
            continue
        case_id = str(payload.get("id", "")).strip()
        if not case_id:
            raise ValueError("Each [[case]] entry must define a non-empty id.")
        if selected is not None and case_id not in selected:
            continue
        comparison_root_raw = str(payload.get("comparison_root", "")).strip()
        if not comparison_root_raw:
            raise ValueError(f"Stability case {case_id!r} must define comparison_root.")
        comparison_root = Path(comparison_root_raw).expanduser()
        if not comparison_root.is_absolute():
            comparison_root = (resolved_path.parent / comparison_root).resolve()

        metric_limits = tuple(
            _parse_metric_limit(case_id=case_id, payload=metric_payload)
            for metric_payload in payload.get("metric", [])
        )
        targets.append(
            ComparisonStabilityTarget(
                case_id=case_id,
                comparison_root=comparison_root,
                allowed_audit_status=_as_string_tuple(
                    payload.get("allowed_audit_status", ["pass"])
                ),
                required_files=_as_string_tuple(
                    payload.get("required_files", _DEFAULT_REQUIRED_FILES)
                ),
                required_figures=_as_string_tuple(payload.get("required_figures", [])),
                required_simulations=_as_string_tuple(
                    payload.get("required_simulations", [])
                ),
                metric_limits=metric_limits,
            )
        )
    return tuple(targets)


def validate_stability_targets(
    targets_path: str | Path,
    *,
    case_ids: Iterable[str] | None = None,
) -> ComparisonStabilityReport:
    """Validate one TOML target file against already materialized outputs."""
    resolved_path = Path(targets_path).expanduser().resolve()
    results = tuple(
        validate_stability_target(target)
        for target in load_stability_targets(resolved_path, case_ids=case_ids)
    )
    return ComparisonStabilityReport(targets_path=resolved_path, cases=results)


def validate_stability_target(
    target: ComparisonStabilityTarget,
) -> ComparisonStabilityCaseResult:
    """Validate one materialized comparison output folder."""
    findings: list[ComparisonStabilityFinding] = []

    def add_error(message: str) -> None:
        findings.append(
            ComparisonStabilityFinding(
                case_id=target.case_id,
                level="error",
                message=message,
            )
        )

    if not target.comparison_root.is_dir():
        add_error(f"comparison_root does not exist: {target.comparison_root}")
        return ComparisonStabilityCaseResult(target=target, findings=tuple(findings))

    for filename in target.required_files:
        if not (target.comparison_root / filename).is_file():
            add_error(f"required file is missing: {filename}")

    figure_root = target.comparison_root / "comparison_figures"
    for figure_name in target.required_figures:
        if not (figure_root / figure_name).is_file():
            add_error(f"required figure is missing: comparison_figures/{figure_name}")

    audit = _load_json_if_present(target.comparison_root / "comparison_audit.json")
    audit_status = str(audit.get("status", "")) if isinstance(audit, Mapping) else ""
    if audit_status and audit_status not in set(target.allowed_audit_status):
        add_error(
            "audit status "
            f"{audit_status!r} is not in allowed_audit_status={target.allowed_audit_status!r}"
        )

    manifest = _load_json_if_present(
        target.comparison_root / "comparison_manifest.json"
    )
    if target.required_simulations:
        _check_required_simulations(
            target=target,
            manifest=manifest,
            add_error=add_error,
        )

    metrics = _load_json_if_present(target.comparison_root / "comparison_metrics.json")
    summary_by_key = _summary_metrics_by_key(metrics)
    for metric_limit in target.metric_limits:
        _check_metric_limit(
            target=target,
            metric_limit=metric_limit,
            summary_by_key=summary_by_key,
            add_error=add_error,
        )

    return ComparisonStabilityCaseResult(target=target, findings=tuple(findings))


def format_stability_report(report: ComparisonStabilityReport) -> str:
    """Return a compact human-readable report."""
    lines = [
        f"Stability targets: {report.targets_path}",
        f"Status: {'PASS' if report.ok else 'FAIL'}",
    ]
    for case_result in report.cases:
        status = "PASS" if case_result.ok else "FAIL"
        lines.append(f"- {case_result.target.case_id}: {status}")
        for finding in case_result.findings:
            lines.append(f"  [{finding.level}] {finding.message}")
    return "\n".join(lines)


def _parse_metric_limit(
    *,
    case_id: str,
    payload: Mapping[str, Any],
) -> ComparisonMetricLimit:
    simulation_id = str(payload.get("simulation_id", "")).strip()
    observable = str(payload.get("observable", "")).strip()
    if not simulation_id or not observable:
        raise ValueError(
            f"Metric limit in case {case_id!r} must define simulation_id and observable."
        )
    limits: dict[str, float] = {}
    for key, value in payload.items():
        if not key.endswith("_max") or key == "n_pairs_min":
            continue
        limits[key[: -len("_max")]] = float(value)
    n_pairs_min_raw = payload.get("n_pairs_min")
    return ComparisonMetricLimit(
        simulation_id=simulation_id,
        observable=observable,
        limits=limits,
        n_pairs_min=None if n_pairs_min_raw is None else int(n_pairs_min_raw),
    )


def _as_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Iterable):
        raise TypeError(f"Expected a string or a list of strings; got {type(value)!r}.")
    return tuple(str(item) for item in value)


def _load_json_if_present(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _summary_metrics_by_key(
    metrics: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    rows = metrics.get("summary", [])
    if not isinstance(rows, list):
        return {}
    summary: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        simulation_id = str(row.get("simulation_id") or row.get("variant_id", ""))
        summary[(simulation_id, str(row.get("observable", "")))] = row
    return summary


def _check_required_simulations(
    *,
    target: ComparisonStabilityTarget,
    manifest: Mapping[str, Any],
    add_error: Any,
) -> None:
    simulation_rows = manifest.get("simulations", manifest.get("variants", []))
    if not isinstance(simulation_rows, list):
        add_error("comparison_manifest.json has no simulations or variants list")
        return
    simulations = {
        str(row.get("id", "")): str(row.get("status", ""))
        for row in simulation_rows
        if isinstance(row, Mapping)
    }
    for simulation_id in target.required_simulations:
        status = simulations.get(simulation_id)
        if status is None:
            add_error(f"required simulation is missing from manifest: {simulation_id}")
        elif status not in {"completed", "reused"}:
            add_error(f"simulation {simulation_id!r} status is {status!r}")


def _check_metric_limit(
    *,
    target: ComparisonStabilityTarget,
    metric_limit: ComparisonMetricLimit,
    summary_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    add_error: Any,
) -> None:
    key = (metric_limit.simulation_id, metric_limit.observable)
    row = summary_by_key.get(key)
    if row is None:
        add_error(
            f"required metric row is missing: "
            f"{metric_limit.simulation_id}::{metric_limit.observable}"
        )
        return
    if metric_limit.n_pairs_min is not None:
        n_pairs = int(row.get("n_pairs", 0))
        if n_pairs < metric_limit.n_pairs_min:
            add_error(
                f"{metric_limit.simulation_id}::{metric_limit.observable}.n_pairs="
                f"{n_pairs} is below {metric_limit.n_pairs_min}"
            )
    for field, upper_bound in metric_limit.limits.items():
        value = row.get(field)
        if value is None:
            add_error(
                f"{metric_limit.simulation_id}::{metric_limit.observable}.{field} is missing"
            )
            continue
        if abs(float(value)) > float(upper_bound):
            add_error(
                f"{metric_limit.simulation_id}::{metric_limit.observable}.{field}="
                f"{float(value):.6g} exceeds {float(upper_bound):.6g}"
            )


__all__ = (
    "ComparisonMetricLimit",
    "ComparisonStabilityCaseResult",
    "ComparisonStabilityFinding",
    "ComparisonStabilityReport",
    "ComparisonStabilityTarget",
    "format_stability_report",
    "load_stability_targets",
    "validate_stability_target",
    "validate_stability_targets",
)
