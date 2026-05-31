"""Preflight validation for catchment report pipeline inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs


@dataclass(frozen=True)
class MissingCatchmentReportInput:
    label: str
    path: Path
    kind: str


class CatchmentReportPreflightError(FileNotFoundError):
    """Raised when the selected catchment report steps cannot start safely."""

    def __init__(self, missing: tuple[MissingCatchmentReportInput, ...]) -> None:
        self.missing = missing
        details = "\n".join(f"- {item.label}: {item.path}" for item in missing)
        super().__init__(
            f"Catchment report preflight failed. Required inputs were not found:\n{details}"
        )


def validate_catchment_report_preflight(
    inputs: CatchmentReportInputs,
    *,
    run_overview: bool,
    run_simulation: bool,
    build_context_artifacts: bool,
    build_report_html: bool,
) -> None:
    """Validate required existing inputs for the selected pipeline steps."""
    missing: list[MissingCatchmentReportInput] = []

    if run_overview:
        _require_file(missing, "overview config", inputs.overview_config)
    if run_simulation or build_context_artifacts or build_report_html:
        _require_file(missing, "simulation config", inputs.transient_config)

    if build_context_artifacts:
        if not run_simulation:
            _require_file(missing, "simulation export", inputs.simulation_export)

    if build_report_html:
        if not build_context_artifacts:
            _require_file(missing, "context summary", inputs.context_summary)

    if missing:
        raise CatchmentReportPreflightError(_dedupe(missing))


def _require_file(
    missing: list[MissingCatchmentReportInput],
    label: str,
    path: Path,
) -> None:
    if not path.is_file():
        missing.append(MissingCatchmentReportInput(label, path, "file"))


def _dedupe(
    missing: list[MissingCatchmentReportInput],
) -> tuple[MissingCatchmentReportInput, ...]:
    seen: set[tuple[str, Path, str]] = set()
    deduped: list[MissingCatchmentReportInput] = []
    for item in missing:
        key = (item.label, item.path, item.kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return tuple(deduped)


__all__ = [
    "CatchmentReportPreflightError",
    "MissingCatchmentReportInput",
    "validate_catchment_report_preflight",
]
