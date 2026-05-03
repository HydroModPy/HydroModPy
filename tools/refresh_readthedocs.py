"""Refresh the versioned inputs that feed the Read the Docs site.

This script is the "full refresh" companion to the targeted gallery helpers.
It recomputes the generated validation reports and capability-gallery artifacts
that are committed in the repository, then verifies that the Sphinx project
still builds cleanly.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs" / "readthedocs"
DEFAULT_BUILD_DIR = "build/html"
DEFAULT_VALIDATION_SOLVERS = ("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq")
DEFAULT_SOLVER_BINARIES = ("mf6", "mfnwt")


@dataclass(frozen=True, slots=True)
class RefreshStep:
    """One command executed by the refresh pipeline."""

    title: str
    working_directory: Path
    command: tuple[str, ...]


def _stringify_path(path: Path) -> str:
    return str(Path(path).expanduser().resolve())


def _quote_command(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def build_refresh_steps(
    *,
    python_executable: Path,
    install_solver_binaries: bool = False,
    solver_binaries_subset: tuple[str, ...] = DEFAULT_SOLVER_BINARIES,
    include_validation_reports: bool = True,
    validation_solvers: tuple[str, ...] = DEFAULT_VALIDATION_SOLVERS,
    validation_regime: str = "both",
    validation_timeout: int = 1800,
    include_xt3d_diagnostics: bool = True,
    include_gallery_refresh: bool = True,
    include_gallery_check: bool = True,
    include_sphinx_build: bool = True,
    build_dir: str = DEFAULT_BUILD_DIR,
) -> tuple[RefreshStep, ...]:
    """Return the ordered commands that refresh the docs-facing artifacts."""

    python_command = _stringify_path(python_executable)
    steps: list[RefreshStep] = []

    if install_solver_binaries:
        subset = ",".join(str(name) for name in solver_binaries_subset if str(name).strip())
        command = [python_command, "-m", "hydromodpy", "install-binaries"]
        if subset:
            command.extend(["--subset", subset])
        command.append("--quiet")
        steps.append(
            RefreshStep(
                title="Install solver binaries",
                working_directory=REPO_ROOT,
                command=tuple(command),
            )
        )

    if include_validation_reports:
        command = [
            python_command,
            "-m",
            "validation_cases.update_reports",
            "--no-show",
            "--stop-on-error",
            "--regime",
            str(validation_regime),
            "--timeout",
            str(int(validation_timeout)),
        ]
        if validation_solvers:
            command.append("--solvers")
            command.extend(str(solver) for solver in validation_solvers)
        steps.append(
            RefreshStep(
                title="Refresh validation reports",
                working_directory=REPO_ROOT,
                command=tuple(command),
            )
        )

    if include_xt3d_diagnostics:
        steps.append(
            RefreshStep(
                title="Refresh XT3D irregular-triangle diagnostics",
                working_directory=REPO_ROOT,
                command=(
                    python_command,
                    "-m",
                    "tools.doc_gallery.xt3d_irregular_tri_diagnostics",
                ),
            )
        )

    if include_gallery_refresh:
        steps.append(
            RefreshStep(
                title="Refresh capability gallery artifacts",
                working_directory=REPO_ROOT,
                command=(python_command, "-m", "tools.doc_gallery"),
            )
        )

    if include_gallery_check:
        steps.append(
            RefreshStep(
                title="Check capability gallery drift",
                working_directory=REPO_ROOT,
                command=(python_command, "-m", "tools.doc_gallery", "--check"),
            )
        )

    if include_sphinx_build:
        steps.append(
            RefreshStep(
                title="Build Sphinx HTML",
                working_directory=DOCS_ROOT,
                command=(
                    python_command,
                    "-m",
                    "sphinx",
                    "-E",
                    "-a",
                    "-W",
                    "-b",
                    "html",
                    "source",
                    str(build_dir),
                ),
            )
        )

    return tuple(steps)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the docs refresh orchestration."""

    parser = argparse.ArgumentParser(
        description=(
            "Refresh the versioned reports and capability-gallery artifacts that feed "
            "the Read the Docs project, then verify the Sphinx build."
        )
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable used for every refresh step.",
    )
    parser.add_argument(
        "--install-solver-binaries",
        action="store_true",
        help="Pre-download solver binaries before running the computational refresh steps.",
    )
    parser.add_argument(
        "--solver-binaries-subset",
        nargs="+",
        default=list(DEFAULT_SOLVER_BINARIES),
        help=(
            "Subset forwarded to `python -m hydromodpy install-binaries --subset ...`. "
            "Defaults to the binaries needed by the validation gallery."
        ),
    )
    parser.add_argument(
        "--skip-validation-reports",
        action="store_true",
        help="Skip regeneration of validation_cases/reports/latest/*.json.",
    )
    parser.add_argument(
        "--validation-solvers",
        nargs="+",
        choices=DEFAULT_VALIDATION_SOLVERS,
        default=list(DEFAULT_VALIDATION_SOLVERS),
        help="Solver families refreshed in validation_cases/reports/latest.",
    )
    parser.add_argument(
        "--validation-regime",
        choices=("steady", "transient", "both"),
        default="both",
        help="Subset of the analytical validation inventory to refresh.",
    )
    parser.add_argument(
        "--validation-timeout",
        type=int,
        default=1800,
        help="Per-case timeout forwarded to validation_cases.run_cases.",
    )
    parser.add_argument(
        "--skip-xt3d-diagnostics",
        action="store_true",
        help="Skip the dedicated XT3D irregular-triangle diagnostic report.",
    )
    parser.add_argument(
        "--skip-gallery-refresh",
        action="store_true",
        help="Skip `python -m tools.doc_gallery`.",
    )
    parser.add_argument(
        "--skip-gallery-check",
        action="store_true",
        help="Skip `python -m tools.doc_gallery --check`.",
    )
    parser.add_argument(
        "--skip-sphinx-build",
        action="store_true",
        help="Skip the final local Sphinx HTML build.",
    )
    parser.add_argument(
        "--build-dir",
        default=DEFAULT_BUILD_DIR,
        help="HTML output directory forwarded to `python -m sphinx -b html source ...`.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the planned commands without executing them.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the full docs-refresh orchestration."""

    args = build_parser().parse_args(argv)
    steps = build_refresh_steps(
        python_executable=Path(args.python),
        install_solver_binaries=bool(args.install_solver_binaries),
        solver_binaries_subset=tuple(str(name) for name in args.solver_binaries_subset),
        include_validation_reports=not bool(args.skip_validation_reports),
        validation_solvers=tuple(str(solver) for solver in args.validation_solvers),
        validation_regime=str(args.validation_regime),
        validation_timeout=int(args.validation_timeout),
        include_xt3d_diagnostics=not bool(args.skip_xt3d_diagnostics),
        include_gallery_refresh=not bool(args.skip_gallery_refresh),
        include_gallery_check=not bool(args.skip_gallery_check),
        include_sphinx_build=not bool(args.skip_sphinx_build),
        build_dir=str(args.build_dir),
    )

    if not steps:
        raise SystemExit("No refresh step selected.")

    for step in steps:
        print("")
        print(f"==> {step.title}")
        print(f"    cwd: {step.working_directory}")
        print(f"    cmd: {_quote_command(step.command)}")
        if args.list:
            continue

        completed = subprocess.run(step.command, cwd=step.working_directory, check=False)
        if int(completed.returncode) != 0:
            return int(completed.returncode)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
