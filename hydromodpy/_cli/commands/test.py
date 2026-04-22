"""``hmp test`` — run the unit/regression/validation pytest suites."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from hydromodpy._cli.helpers import (
    build_pytest_runtime_env,
    find_project_root,
    pytest_addopts_declares_basetemp,
)

NAME = "test"
HELP = "Run unit, regression, or validation tests"


_RE_REGRESSION = re.compile(
    r"^test_"
    r"(?P<base>.+?)"
    r"(?:s_short(?:_new)?)?_"
    r"(?:npy_)?regression"
    r"(?:_\w+)?"
    r"\.py$"
)
_REGRESSION_TIERS = ("fast", "extensive")


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "suite",
        choices=["unit", "regression", "validation"],
        help="Test suite to run",
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="Regression test name (use --list to see available)",
    )
    parser.add_argument(
        "--list", action="store_true", help="List available regression test names and exit"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Run the fast subset for the selected suite"
    )
    parser.add_argument(
        "--slow", action="store_true", help="Run the slow subset for the selected suite"
    )
    parser.add_argument("--normal", action="store_true", help="Deprecated alias for --fast")
    parser.add_argument(
        "--extensive", action="store_true", help="Only run extensive regression tests"
    )
    parser.add_argument(
        "--nwt",
        action="store_true",
        help="Only run MODFLOW-NWT / MODPATH / MT3DMS regression tests",
    )
    parser.add_argument(
        "--mf6", action="store_true", help="Only run MODFLOW 6 / GWT regression tests"
    )
    parser.add_argument("--steady", action="store_true", help="Filter to steady-state tests")
    parser.add_argument("--transient", action="store_true", help="Filter to transient tests")
    parser.add_argument(
        "--analytical", action="store_true", help="Filter to analytical validation tests"
    )
    parser.add_argument(
        "--short", action="store_true", help="Run the short variant of a specific test"
    )
    parser.add_argument(
        "--update-goldens",
        action="store_true",
        help="Update golden reference files instead of asserting",
    )
    parser.add_argument(
        "-j", "--jobs", default=None, help="Number of parallel workers (requires pytest-xdist)"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    root = find_project_root()
    pytest_args = [sys.executable, "-m", "pytest", "-v"]
    basetemp_root, pytest_env = build_pytest_runtime_env()
    if not pytest_addopts_declares_basetemp(pytest_env.get("PYTEST_ADDOPTS", "")):
        pytest_args.extend(["--basetemp", str(basetemp_root)])
    tiers = _selected_tiers(args.normal, args.extensive, args.fast)

    if args.suite == "unit":
        if args.list:
            print("--list is only available for regression tests.", file=sys.stderr)
            sys.exit(2)
        if args.name is not None:
            print("Unit tests do not accept a named regression target.", file=sys.stderr)
            sys.exit(2)
        if args.short:
            print("--short is only available for regression tests.", file=sys.stderr)
            sys.exit(2)
        if args.update_goldens:
            print("--update-goldens is only available for regression tests.", file=sys.stderr)
            sys.exit(2)
        if args.extensive:
            print("--extensive is only available for regression tests.", file=sys.stderr)
            sys.exit(2)
        if args.nwt or args.mf6 or args.steady or args.transient or args.analytical:
            print(
                "--nwt/--mf6/--steady/--transient/--analytical are only available "
                "for regression or validation tests.",
                file=sys.stderr,
            )
            sys.exit(2)

        pytest_args.append(str(root / "tests" / "unit"))
        _append_unit_marker_filter(
            pytest_args,
            fast=bool(args.fast or args.normal),
            slow=bool(args.slow),
        )

    elif args.suite == "regression":
        regression_dir = root / "tests" / "regression"

        if args.list:
            _list_regression_tests(
                regression_dir,
                normal=args.normal,
                extensive=args.extensive,
                fast=args.fast,
            )
            return
        if args.name is not None:
            _append_regression_name_selection(
                pytest_args=pytest_args,
                regression_dir=regression_dir,
                name=args.name,
                short=args.short,
                selected_tiers=tiers,
            )
        else:
            _append_regression_directory_selection(
                pytest_args=pytest_args,
                regression_dir=regression_dir,
                normal=args.normal,
                extensive=args.extensive,
                fast=args.fast,
            )

        _append_marker_filter(
            pytest_args=pytest_args,
            normal=args.normal,
            extensive=args.extensive,
            fast=args.fast,
            slow=args.slow,
            nwt=args.nwt,
            mf6=args.mf6,
            steady=args.steady,
            transient=args.transient,
            analytical=args.analytical,
        )

        if args.update_goldens:
            pytest_args.append("--update-goldens")

    elif args.suite == "validation":
        if args.list:
            print("--list is only available for regression tests.", file=sys.stderr)
            sys.exit(2)
        if args.name is not None:
            print("Validation tests do not accept a named regression target.", file=sys.stderr)
            sys.exit(2)
        if args.short:
            print("--short is only available for regression tests.", file=sys.stderr)
            sys.exit(2)
        if args.update_goldens:
            print("--update-goldens is only available for regression tests.", file=sys.stderr)
            sys.exit(2)

        pytest_args.append(str(root / "tests" / "validation"))
        _append_marker_filter(
            pytest_args=pytest_args,
            normal=args.normal,
            extensive=args.extensive,
            fast=args.fast,
            slow=args.slow,
            nwt=args.nwt,
            mf6=args.mf6,
            validation=True,
            steady=args.steady,
            transient=args.transient,
            analytical=args.analytical,
        )

    if args.jobs is not None:
        pytest_args.extend(["-n", args.jobs])

    print(f"Running: {' '.join(pytest_args)}", file=sys.stderr)
    sys.exit(subprocess.call(pytest_args, env=pytest_env))


# ---------------------------------------------------------------------------
# Helpers (ex hydromodpy/__main__.py)
# ---------------------------------------------------------------------------


def _selected_tiers(normal: bool, extensive: bool, fast: bool) -> list[str]:
    tiers: list[str] = []
    if normal or fast:
        tiers.append("fast")
    if extensive:
        tiers.append("extensive")
    return tiers or ["fast", "extensive"]


def _append_marker_filter(
    pytest_args: list[str],
    normal: bool,
    extensive: bool,
    fast: bool,
    slow: bool,
    nwt: bool,
    mf6: bool,
    *,
    validation: bool = False,
    steady: bool = False,
    transient: bool = False,
    analytical: bool = False,
) -> None:
    if fast and slow:
        print("Cannot use --fast and --slow together.", file=sys.stderr)
        sys.exit(2)
    if nwt and mf6:
        print("Cannot use --nwt and --mf6 together.", file=sys.stderr)
        sys.exit(2)
    if steady and transient:
        print("Cannot use --steady and --transient together.", file=sys.stderr)
        sys.exit(2)
    if validation and normal:
        print("Cannot use --normal with validation tests.", file=sys.stderr)
        sys.exit(2)
    if validation and extensive:
        print("Cannot use --extensive with validation tests.", file=sys.stderr)
        sys.exit(2)

    markers: list[str] = []
    if validation:
        markers.append("validation")
        if fast:
            markers.append("fast")
        if slow:
            markers.append("slow")
    else:
        selected_tiers = _selected_tiers(normal, extensive, fast)
        if selected_tiers == ["fast"]:
            markers.append("fast")
        elif selected_tiers == ["extensive"]:
            markers.append("extensive")
        if slow:
            markers.append("slow")
    if nwt:
        markers.append("nwt")
    if mf6:
        markers.append("mf6")
    if analytical:
        markers.append("analytical")
    if steady:
        markers.append("steady")
    if transient:
        markers.append("transient")

    if markers:
        pytest_args.extend(["-m", " and ".join(markers)])


def _append_unit_marker_filter(
    pytest_args: list[str],
    *,
    fast: bool,
    slow: bool,
) -> None:
    if fast and slow:
        print("Cannot use --fast and --slow together.", file=sys.stderr)
        sys.exit(2)
    if fast:
        pytest_args.extend(["-m", "not slow and not integration"])
    elif slow:
        pytest_args.extend(["-m", "slow or integration"])


def _discover_regression_tests(
    regression_dir: Path,
    selected_tiers: list[str] | None = None,
) -> dict[str, dict[str, list[Path]]]:
    selected = set(selected_tiers or _REGRESSION_TIERS)
    tests: dict[str, dict[str, list[Path]]] = {}
    for p in sorted(regression_dir.rglob("test_*regression*.py")):
        if not any(tier in p.parts for tier in selected):
            continue
        m = _RE_REGRESSION.match(p.name)
        if not m:
            continue
        base = m.group("base")
        is_short = "s_short" in p.name
        variant = "short" if is_short else "full"
        tests.setdefault(base, {"full": [], "short": []})
        tests[base][variant].append(p)
    return tests


def _list_regression_tests(
    regression_dir: Path,
    *,
    normal: bool = False,
    extensive: bool = False,
    fast: bool = False,
) -> None:
    tests = _discover_regression_tests(
        regression_dir,
        selected_tiers=_selected_tiers(normal, extensive, fast),
    )
    if not tests:
        print("No regression tests found.", file=sys.stderr)
        return
    for base, variants in tests.items():
        parts = []
        if variants["full"]:
            parts.append("full")
        if variants["short"]:
            parts.append("short")
        print(f"  {base:30s} [{', '.join(parts)}]")


def _append_regression_name_selection(
    *,
    pytest_args: list[str],
    regression_dir: Path,
    name: str,
    short: bool,
    selected_tiers: list[str],
) -> None:
    tests = _discover_regression_tests(
        regression_dir=regression_dir,
        selected_tiers=selected_tiers,
    )

    available = [base for base in tests.keys() if base == name]
    if not available:
        candidates = [base for base in tests.keys() if base.startswith(name)]
        if len(candidates) == 1:
            available = candidates
        elif candidates:
            print(f"Ambiguous regression name '{name}'.", file=sys.stderr)
            print("Candidates:", ", ".join(sorted(candidates)), file=sys.stderr)
            sys.exit(2)

    if not available:
        print(f"No regression test named '{name}' for selected tier(s).", file=sys.stderr)
        sys.exit(2)

    matched_base = available[0]
    variants = tests[matched_base]
    variant = "short" if short else "full"
    selected_files = variants[variant]

    if short and not selected_files and variants["full"]:
        print(
            f"[hmp] No short regression found for '{matched_base}'. "
            "Falling back to full regression.",
            file=sys.stderr,
        )
        selected_files = variants["full"]

    if not selected_files:
        print(
            f"No regression files found for '{matched_base}' and selected tier(s).",
            file=sys.stderr,
        )
        sys.exit(2)

    for path in sorted(selected_files):
        pytest_args.append(str(path))


def _append_regression_directory_selection(
    *,
    pytest_args: list[str],
    regression_dir: Path,
    normal: bool,
    extensive: bool,
    fast: bool,
) -> None:
    tiers = _selected_tiers(normal, extensive, fast)
    selected = False

    for tier in tiers:
        tier_dir = regression_dir / tier
        if not tier_dir.exists():
            continue
        has_tests = any(
            _RE_REGRESSION.match(p.name) for p in tier_dir.rglob("test_*regression*.py")
        )
        if not has_tests:
            continue
        pytest_args.append(str(tier_dir))
        selected = True

    if not selected:
        print("No regression tests found for selected tier(s).", file=sys.stderr)
        sys.exit(2)
