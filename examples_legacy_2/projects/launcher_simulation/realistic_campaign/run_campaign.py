"""Batch runner for realistic simulation and comparison campaigns."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping

from hydromodpy.core.config.toml_loader import load_toml_with_base_config


DEFAULT_MANIFEST_PATH = Path(__file__).with_name("campaign.toml")
REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class CampaignCase:
    """One runnable realistic campaign case."""

    case_id: str
    label: str
    launcher: str
    config_path: Path
    tier: str
    scale: str
    family: str
    solver_family: tuple[str, ...]
    region: str | None
    tags: tuple[str, ...]
    description: str | None
    enabled: bool


@dataclass(frozen=True)
class CampaignManifest:
    """Validated campaign manifest plus its cases."""

    manifest_path: Path
    campaign_id: str
    label: str
    description: str | None
    output_root: Path
    continue_on_error: bool
    cases: tuple[CampaignCase, ...]


@dataclass(frozen=True)
class CampaignExecution:
    """Outcome recorded for one executed campaign case."""

    case: CampaignCase
    command: tuple[str, ...]
    returncode: int
    duration_seconds: float


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _require_text(value: object, *, label: str) -> str:
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{label} cannot be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_text_list(value: object, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for raw_item in value:
        item = str(raw_item).strip()
        if item == "":
            raise ValueError(f"{label} cannot contain empty values")
        normalized = item.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(item)
    return tuple(out)


def _resolve_path(base_dir: Path, raw_path: object, *, label: str) -> Path:
    text = _require_text(raw_path, label=label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def load_campaign_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> CampaignManifest:
    """Load and validate one realistic campaign TOML manifest."""
    resolved_manifest = Path(manifest_path).expanduser().resolve()
    payload = load_toml_with_base_config(resolved_manifest)
    campaign_section = _require_mapping(payload.get("campaign"), label="campaign")

    campaign_id = _optional_text(campaign_section.get("campaign_id")) or resolved_manifest.stem
    label = _optional_text(campaign_section.get("label")) or campaign_id
    description = _optional_text(campaign_section.get("description"))
    output_root = _resolve_path(
        resolved_manifest.parent,
        campaign_section.get("output_root", "./outputs"),
        label="campaign.output_root",
    )
    continue_on_error = bool(campaign_section.get("continue_on_error", True))

    raw_cases = campaign_section.get("case", [])
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("campaign.case must contain at least one item")

    cases: list[CampaignCase] = []
    seen_ids: set[str] = set()
    for raw_case in raw_cases:
        case_mapping = _require_mapping(raw_case, label="campaign.case[]")
        case_id = _require_text(case_mapping.get("id"), label="campaign.case.id")
        normalized_id = case_id.lower()
        if normalized_id in seen_ids:
            raise ValueError(f"Duplicate campaign.case id '{case_id}'")
        seen_ids.add(normalized_id)

        launcher = _require_text(
            case_mapping.get("launcher"),
            label=f"campaign.case[{case_id}].launcher",
        ).lower()
        if launcher not in {"simulation", "method-comparison"}:
            raise ValueError(
                f"Unsupported launcher '{launcher}' for case '{case_id}'. "
                "Use 'simulation' or 'method-comparison'."
            )

        cases.append(
            CampaignCase(
                case_id=case_id,
                label=_optional_text(case_mapping.get("label")) or case_id,
                launcher=launcher,
                config_path=_resolve_path(
                    resolved_manifest.parent,
                    case_mapping.get("config"),
                    label=f"campaign.case[{case_id}].config",
                ),
                tier=_require_text(
                    case_mapping.get("tier"),
                    label=f"campaign.case[{case_id}].tier",
                ),
                scale=_require_text(
                    case_mapping.get("scale"),
                    label=f"campaign.case[{case_id}].scale",
                ),
                family=_require_text(
                    case_mapping.get("family"),
                    label=f"campaign.case[{case_id}].family",
                ),
                solver_family=_normalize_text_list(
                    case_mapping.get("solver_family"),
                    label=f"campaign.case[{case_id}].solver_family",
                ),
                region=_optional_text(case_mapping.get("region")),
                tags=_normalize_text_list(
                    case_mapping.get("tags"),
                    label=f"campaign.case[{case_id}].tags",
                ),
                description=_optional_text(case_mapping.get("description")),
                enabled=bool(case_mapping.get("enabled", True)),
            )
        )

    return CampaignManifest(
        manifest_path=resolved_manifest,
        campaign_id=campaign_id,
        label=label,
        description=description,
        output_root=output_root,
        continue_on_error=continue_on_error,
        cases=tuple(cases),
    )


def filter_campaign_cases(
    cases: tuple[CampaignCase, ...] | list[CampaignCase],
    *,
    case_ids: tuple[str, ...] = (),
    tiers: tuple[str, ...] = (),
    launchers: tuple[str, ...] = (),
    scales: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    regions: tuple[str, ...] = (),
    include_disabled: bool = False,
) -> list[CampaignCase]:
    """Filter campaign cases by metadata selectors."""
    wanted_ids = {item.strip().lower() for item in case_ids if item.strip()}
    wanted_tiers = {item.strip().lower() for item in tiers if item.strip()}
    wanted_launchers = {item.strip().lower() for item in launchers if item.strip()}
    wanted_scales = {item.strip().lower() for item in scales if item.strip()}
    wanted_tags = {item.strip().lower() for item in tags if item.strip()}
    wanted_regions = {item.strip().lower() for item in regions if item.strip()}

    filtered: list[CampaignCase] = []
    for case in cases:
        if not include_disabled and not case.enabled:
            continue
        if wanted_ids and case.case_id.lower() not in wanted_ids:
            continue
        if wanted_tiers and case.tier.lower() not in wanted_tiers:
            continue
        if wanted_launchers and case.launcher.lower() not in wanted_launchers:
            continue
        if wanted_scales and case.scale.lower() not in wanted_scales:
            continue
        if wanted_regions:
            region = (case.region or "").strip().lower()
            if region not in wanted_regions:
                continue
        if wanted_tags:
            case_tags = {tag.lower() for tag in case.tags}
            if not wanted_tags.issubset(case_tags):
                continue
        filtered.append(case)
    return filtered


def build_run_command(
    case: CampaignCase,
    *,
    python_executable: Path,
) -> list[str]:
    """Build the subprocess command for one campaign case."""
    base = [str(python_executable), "-m", "launchers"]
    if case.launcher == "simulation":
        return [*base, "simulation", str(case.config_path)]
    if case.launcher == "method-comparison":
        return [*base, "method-comparison", "run", str(case.config_path)]
    raise ValueError(f"Unsupported launcher '{case.launcher}'")


def _print_case_list(cases: list[CampaignCase]) -> None:
    """Print a concise case inventory."""
    for case in cases:
        status = "on " if case.enabled else "off"
        solver_family = ",".join(case.solver_family) if case.solver_family else "-"
        print(
            f"{case.tier:<9} {case.scale:<10} {case.launcher:<18} "
            f"{status:<3} {solver_family:<24} {case.case_id}"
        )


def build_execution_report(
    *,
    manifest: CampaignManifest,
    selected_cases: list[CampaignCase],
    executions: list[CampaignExecution],
    filters: Mapping[str, Any],
    continue_on_error: bool,
) -> dict[str, object]:
    """Build one JSON-serializable campaign execution report."""
    failures = [item for item in executions if int(item.returncode) != 0]
    total_duration_seconds = float(sum(float(item.duration_seconds) for item in executions))
    return {
        "schema_version": "realistic_campaign_report_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest.manifest_path),
        "campaign_id": manifest.campaign_id,
        "campaign_label": manifest.label,
        "campaign_output_root": str(manifest.output_root),
        "continue_on_error": bool(continue_on_error),
        "filters": dict(filters),
        "selected_case_count": len(selected_cases),
        "executed_case_count": len(executions),
        "completed_case_count": len(executions) - len(failures),
        "failed_case_count": len(failures),
        "all_passed": len(failures) == 0 and len(executions) == len(selected_cases),
        "total_duration_seconds": total_duration_seconds,
        "cases": [
            {
                "id": item.case.case_id,
                "label": item.case.label,
                "launcher": item.case.launcher,
                "config_path": str(item.case.config_path),
                "tier": item.case.tier,
                "scale": item.case.scale,
                "family": item.case.family,
                "solver_family": list(item.case.solver_family),
                "region": item.case.region,
                "tags": list(item.case.tags),
                "enabled": bool(item.case.enabled),
                "returncode": int(item.returncode),
                "duration_seconds": round(float(item.duration_seconds), 6),
                "command": list(item.command),
            }
            for item in executions
        ],
    }


def write_execution_report(path: Path, report: Mapping[str, object]) -> None:
    """Serialize one campaign report to disk."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run realistic simulation and method-comparison campaign cases sequentially.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to the campaign TOML manifest.",
    )
    parser.add_argument(
        "--case",
        dest="case_ids",
        action="append",
        default=[],
        help="Select one explicit case id. Repeat to keep several.",
    )
    parser.add_argument(
        "--tier",
        dest="tiers",
        action="append",
        default=[],
        help="Select one tier label. Repeat to keep several.",
    )
    parser.add_argument(
        "--launcher",
        dest="launchers",
        action="append",
        default=[],
        choices=("simulation", "method-comparison"),
        help="Restrict to one launcher family.",
    )
    parser.add_argument(
        "--scale",
        dest="scales",
        action="append",
        default=[],
        help="Select one scale label. Repeat to keep several.",
    )
    parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Require one metadata tag. Repeat to require several tags together.",
    )
    parser.add_argument(
        "--region",
        dest="regions",
        action="append",
        default=[],
        help="Restrict to one region label. Repeat to keep several.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable used to launch each case.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the selected cases without executing them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved commands without executing them.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="Optional JSON report path. Defaults to <campaign.output_root>/campaign_report.json.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Keep disabled cases in selection and listing.",
    )
    parser.set_defaults(continue_on_error=None)
    parser.add_argument(
        "--stop-on-error",
        dest="continue_on_error",
        action="store_const",
        const=False,
        help="Stop the batch as soon as one case fails.",
    )
    parser.add_argument(
        "--continue-on-error",
        dest="continue_on_error",
        action="store_const",
        const=True,
        help="Continue executing the selected cases after failures.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for realistic campaign execution."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    manifest = load_campaign_manifest(Path(args.manifest))
    selected_cases = filter_campaign_cases(
        manifest.cases,
        case_ids=tuple(args.case_ids),
        tiers=tuple(args.tiers),
        launchers=tuple(args.launchers),
        scales=tuple(args.scales),
        tags=tuple(args.tags),
        regions=tuple(args.regions),
        include_disabled=bool(args.include_disabled),
    )
    if not selected_cases:
        parser.error("No campaign cases matched the selected filters.")

    continue_on_error = (
        manifest.continue_on_error
        if args.continue_on_error is None
        else bool(args.continue_on_error)
    )
    filters = {
        "case_ids": list(args.case_ids),
        "tiers": list(args.tiers),
        "launchers": list(args.launchers),
        "scales": list(args.scales),
        "tags": list(args.tags),
        "regions": list(args.regions),
        "include_disabled": bool(args.include_disabled),
    }

    print(
        f"Selected {len(selected_cases)} case(s) for campaign={manifest.campaign_id} "
        f"continue_on_error={bool(continue_on_error)}"
    )
    if args.list:
        _print_case_list(selected_cases)
        return 0

    if args.dry_run:
        for case in selected_cases:
            command = build_run_command(case, python_executable=Path(args.python))
            print(f"{case.case_id}: {' '.join(command)}")
        return 0

    executions: list[CampaignExecution] = []
    report_path = (
        Path(args.report_json).expanduser().resolve()
        if args.report_json is not None
        else (manifest.output_root / "campaign_report.json").resolve()
    )

    for index, case in enumerate(selected_cases, start=1):
        print("")
        print(f"[{index}/{len(selected_cases)}] {case.case_id}")
        command = build_run_command(case, python_executable=Path(args.python))
        start_time = time.perf_counter()
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        duration_seconds = float(time.perf_counter() - start_time)
        execution = CampaignExecution(
            case=case,
            command=tuple(command),
            returncode=int(completed.returncode),
            duration_seconds=duration_seconds,
        )
        executions.append(execution)
        report = build_execution_report(
            manifest=manifest,
            selected_cases=selected_cases,
            executions=executions,
            filters=filters,
            continue_on_error=continue_on_error,
        )
        write_execution_report(report_path, report)
        if completed.returncode != 0:
            print(f"Case failed with exit code {completed.returncode}: {case.case_id}")
            if not continue_on_error:
                break

    report = build_execution_report(
        manifest=manifest,
        selected_cases=selected_cases,
        executions=executions,
        filters=filters,
        continue_on_error=continue_on_error,
    )
    write_execution_report(report_path, report)

    failures = [item for item in executions if int(item.returncode) != 0]
    print("")
    print(
        f"Completed {len(executions) - len(failures)}/{len(selected_cases)} case(s) "
        f"for campaign={manifest.campaign_id}"
    )
    print(f"Report: {report_path}")
    if failures:
        print("Failed cases:")
        for execution in failures:
            print(execution.case.case_id)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
