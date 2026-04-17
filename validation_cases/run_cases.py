"""Batch runner for analytical validation-case ``run_case.py`` scripts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from validation_cases.shared.loaders import load_case_metadata


PACKAGE_ROOT = Path(__file__).resolve().parent
ANALYTICAL_ROOT = PACKAGE_ROOT / "analytical"
REPO_ROOT = PACKAGE_ROOT.parent


@dataclass(frozen=True)
class ValidationCaseRun:
    """One runnable analytical validation case."""

    module_name: str
    run_case_path: Path
    regime: str
    supported_solvers: tuple[str, ...]


@dataclass(frozen=True)
class ValidationCaseExecution:
    """Outcome recorded for one executed validation case."""

    case: ValidationCaseRun
    command: tuple[str, ...]
    returncode: int
    duration_seconds: float


def _normalize_solver_names(metadata: dict) -> tuple[str, ...]:
    """Extract supported solver names from one case metadata mapping."""
    config_files = metadata.get("config_files")
    if isinstance(config_files, dict) and config_files:
        solvers = sorted(
            {
                str(key).strip().lower()
                for key in config_files
                if str(key).strip()
            }
        )
        if solvers:
            return tuple(solvers)

    default_solver = str(metadata.get("default_solver", "modflownwt")).strip().lower()
    return (default_solver,) if default_solver else ("modflownwt",)


def discover_validation_cases(package_root: Path = PACKAGE_ROOT) -> list[ValidationCaseRun]:
    """Discover launcher-backed analytical validation cases."""
    analytical_root = package_root / "analytical"
    repo_root = package_root.parent
    discovered: list[ValidationCaseRun] = []

    for run_case_path in sorted(analytical_root.rglob("run_case.py")):
        case_dir = run_case_path.parent
        metadata = load_case_metadata(case_dir)
        regime = str(metadata.get("regime", "")).strip().lower()
        if regime not in {"steady", "transient"}:
            continue

        module_name = ".".join(run_case_path.relative_to(repo_root).with_suffix("").parts)
        discovered.append(
            ValidationCaseRun(
                module_name=module_name,
                run_case_path=run_case_path,
                regime=regime,
                supported_solvers=_normalize_solver_names(metadata),
            )
        )

    return discovered


def filter_validation_cases(
    cases: list[ValidationCaseRun],
    *,
    solver: str,
    regime: str,
) -> list[ValidationCaseRun]:
    """Filter discovered cases by solver support and regime."""
    normalized_solver = str(solver).strip().lower()
    normalized_regime = str(regime).strip().lower()

    if normalized_regime not in {"steady", "transient", "both"}:
        raise ValueError(f"Unsupported regime: {regime}")

    filtered = [
        case
        for case in cases
        if normalized_solver in case.supported_solvers
        and (normalized_regime == "both" or case.regime == normalized_regime)
    ]
    return sorted(filtered, key=lambda case: case.module_name)


def build_run_command(
    case: ValidationCaseRun,
    *,
    python_executable: Path,
    solver: str,
    timeout: int,
    show_plot: bool,
) -> list[str]:
    """Build the subprocess command for one validation case."""
    return [
        str(python_executable),
        str(case.run_case_path),
        "--solver",
        str(solver),
        "--timeout",
        str(int(timeout)),
        "--show" if show_plot else "--no-show",
    ]


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the validation batch runner."""
    parser = argparse.ArgumentParser(
        description="Run analytical validation cases sequentially through their run_case.py scripts."
    )
    parser.add_argument(
        "--solver",
        choices=("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq"),
        required=True,
        help="Solver variant to pass to each compatible validation case.",
    )
    parser.add_argument(
        "--regime",
        choices=("steady", "transient", "both"),
        default="both",
        help="Subset of validation cases to run.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable used to launch each case.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Per-case launcher timeout forwarded to run_case.py.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the selected cases without executing them.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="Optional JSON report path written after execution.",
    )
    parser.set_defaults(show_plot=True, continue_on_error=True)
    parser.add_argument(
        "--show",
        dest="show_plot",
        action="store_true",
        help="Open the matplotlib window for each case.",
    )
    parser.add_argument(
        "--no-show",
        dest="show_plot",
        action="store_false",
        help="Disable interactive figure display.",
    )
    parser.add_argument(
        "--stop-on-error",
        dest="continue_on_error",
        action="store_false",
        help="Stop the batch as soon as one case fails.",
    )
    return parser


def _print_case_list(cases: list[ValidationCaseRun]) -> None:
    """Print one concise case inventory."""
    for case in cases:
        solvers = ",".join(case.supported_solvers)
        print(f"{case.regime:<9} {solvers:<20} {case.module_name}")


def build_execution_report(
    *,
    solver: str,
    regime: str,
    show_plot: bool,
    selected_cases: list[ValidationCaseRun],
    executions: list[ValidationCaseExecution],
) -> dict[str, object]:
    """Build one JSON-serializable summary for one batch execution."""
    failures = [item for item in executions if int(item.returncode) != 0]
    total_duration_seconds = float(sum(float(item.duration_seconds) for item in executions))
    return {
        "schema_version": "validation_batch_report_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "solver": str(solver),
        "regime": str(regime),
        "show_plot": bool(show_plot),
        "selected_case_count": len(selected_cases),
        "executed_case_count": len(executions),
        "completed_case_count": len(executions) - len(failures),
        "failed_case_count": len(failures),
        "all_passed": len(failures) == 0 and len(executions) == len(selected_cases),
        "total_duration_seconds": total_duration_seconds,
        "cases": [
            {
                "module_name": item.case.module_name,
                "run_case_path": str(item.case.run_case_path),
                "regime": item.case.regime,
                "supported_solvers": list(item.case.supported_solvers),
                "returncode": int(item.returncode),
                "duration_seconds": round(float(item.duration_seconds), 6),
                "command": list(item.command),
            }
            for item in executions
        ],
    }


def write_execution_report(path: Path, report: dict[str, object]) -> None:
    """Serialize one batch execution report to disk."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for sequential validation-case execution."""
    parser = build_parser()
    args = parser.parse_args(argv)

    selected_cases = filter_validation_cases(
        discover_validation_cases(),
        solver=str(args.solver),
        regime=str(args.regime),
    )
    if not selected_cases:
        parser.error("No validation cases matched the selected solver/regime.")

    print(
        f"Selected {len(selected_cases)} case(s) for solver={args.solver} "
        f"regime={args.regime} show={bool(args.show_plot)}"
    )
    if args.list:
        _print_case_list(selected_cases)
        return 0

    executions: list[ValidationCaseExecution] = []
    for index, case in enumerate(selected_cases, start=1):
        print("")
        print(f"[{index}/{len(selected_cases)}] {case.module_name}")
        command = build_run_command(
            case,
            python_executable=Path(args.python),
            solver=str(args.solver),
            timeout=int(args.timeout),
            show_plot=bool(args.show_plot),
        )
        start_time = time.perf_counter()
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        duration_seconds = float(time.perf_counter() - start_time)
        executions.append(
            ValidationCaseExecution(
                case=case,
                command=tuple(command),
                returncode=int(completed.returncode),
                duration_seconds=duration_seconds,
            )
        )
        if completed.returncode != 0:
            print(
                f"Case failed with exit code {completed.returncode}: {case.module_name}"
            )
            if args.report_json is not None:
                report = build_execution_report(
                    solver=str(args.solver),
                    regime=str(args.regime),
                    show_plot=bool(args.show_plot),
                    selected_cases=selected_cases,
                    executions=executions,
                )
                write_execution_report(Path(args.report_json), report)
            if not bool(args.continue_on_error):
                break

    report = build_execution_report(
        solver=str(args.solver),
        regime=str(args.regime),
        show_plot=bool(args.show_plot),
        selected_cases=selected_cases,
        executions=executions,
    )
    failures = [item for item in executions if int(item.returncode) != 0]
    if args.report_json is not None:
        write_execution_report(Path(args.report_json), report)

    print("")
    print(
        f"Completed {len(executions) - len(failures)}/{len(selected_cases)} case(s) "
        f"for solver={args.solver}"
    )
    if failures:
        print("Failed cases:")
        for execution in failures:
            print(execution.case.module_name)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
