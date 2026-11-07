"""``python -m tools.dev test``: run the unit, regression or validation pytest suites."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_USAGE, refuse

NAME: str = "test"
HELP: str = "Run unit, regression, or validation tests"


def find_project_root() -> Path:
    """Walk up from this file to find the directory containing ``tests/``."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "tests").is_dir():
            return parent
    return Path.cwd()


def pytest_addopts_declares_basetemp(pytest_addopts: str) -> bool:
    """Return ``True`` when ``PYTEST_ADDOPTS`` already declares ``--basetemp``."""
    return re.search(r"(^|\s)--basetemp(?:=|\s|$)", str(pytest_addopts)) is not None


def build_pytest_runtime_env() -> tuple[Path, dict[str, str]]:
    """Prepare one scratch root outside the repository for pytest and its subprocesses.

    ``HMP_TEST_SCRATCH_ROOT`` and ``HMP_TEST_SESSION_SCRATCH_ROOT`` override the
    defaults, a folder of the system temp directory and one session under it.
    """
    override = os.environ.get("HMP_TEST_SCRATCH_ROOT")
    scratch_root = (
        Path(override).expanduser().resolve()
        if override
        else (Path(tempfile.gettempdir()) / "hydromodpy_tests").resolve()
    )
    override = os.environ.get("HMP_TEST_SESSION_SCRATCH_ROOT")
    session_root = (
        Path(override).expanduser().resolve()
        if override
        else (scratch_root / "sessions" / f"cli_{os.getpid()}_{uuid.uuid4().hex[:12]}").resolve()
    )
    tmp_root = session_root / "tmp"
    pytest_root = session_root / "pytest"
    basetemp_root = pytest_root / f"cli_{os.getpid()}"
    for path in (scratch_root, session_root, tmp_root, pytest_root, basetemp_root):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HMP_TEST_SCRATCH_ROOT"] = str(scratch_root)
    env["HMP_TEST_SESSION_SCRATCH_ROOT"] = str(session_root)
    env["PYTEST_DEBUG_TEMPROOT"] = str(pytest_root)
    env["TMPDIR"] = str(tmp_root)
    env["TMP"] = str(tmp_root)
    env["TEMP"] = str(tmp_root)
    return basetemp_root, env


def _refuse_regression_options(args: argparse.Namespace, suite: str) -> None:
    """Stop on an option only the regression suite reads."""
    if args.list:
        refuse("--list is only available for regression tests.", EXIT_USAGE)
    if args.name is not None:
        refuse(f"{suite} tests do not accept a named regression target.", EXIT_USAGE)
    for flag, given in (
        ("--short", args.short),
        ("--update-goldens", args.update_goldens),
    ):
        if given:
            refuse(f"{flag} is only available for regression tests.", EXIT_USAGE)


_RE_REGRESSION = re.compile(
    r"^test_"
    r"(?P<base>.+)"
    r"_"
    r"(?:npy_)?regression"
    r"(?:_\w+)?"
    r"\.py$"
)
_REGRESSION_TIERS = ("fast", "extensive")


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        epilog=(
            "Examples:\n  python -m tools.dev test unit --fast\n"
            "  python -m tools.dev test validation --fast -j 4"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    parser.add_argument(
        "--intercomparison",
        action="store_true",
        help="Only run solver intercomparison regression tests",
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
    tiers = _selected_tiers(args.extensive, args.fast)

    if args.suite == "unit":
        _refuse_regression_options(args, "Unit")
        if args.extensive:
            refuse("--extensive is only available for regression tests.", EXIT_USAGE)
        if (
            args.nwt
            or args.mf6
            or args.intercomparison
            or args.steady
            or args.transient
            or args.analytical
        ):
            refuse(
                "--nwt/--mf6/--steady/--transient/--analytical are only available "
                "for regression or validation tests; --intercomparison is only "
                "available for regression tests.",
                EXIT_USAGE,
            )

        pytest_args.append(str(root / "tests" / "unit"))
        _append_unit_marker_filter(
            pytest_args,
            fast=bool(args.fast),
            slow=bool(args.slow),
        )

    elif args.suite == "regression":
        regression_dir = root / "tests" / "regression"

        if args.list:
            _list_regression_tests(
                regression_dir,
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
                extensive=args.extensive,
                fast=args.fast,
            )

        _append_marker_filter(
            pytest_args=pytest_args,
            extensive=args.extensive,
            fast=args.fast,
            slow=args.slow,
            nwt=args.nwt,
            mf6=args.mf6,
            intercomparison=args.intercomparison,
            steady=args.steady,
            transient=args.transient,
            analytical=args.analytical,
        )

        if args.update_goldens:
            pytest_args.append("--update-goldens")

    elif args.suite == "validation":
        _refuse_regression_options(args, "Validation")
        if args.intercomparison:
            refuse("--intercomparison is only available for regression tests.", EXIT_USAGE)

        pytest_args.append(str(root / "tests" / "validation"))
        _append_marker_filter(
            pytest_args=pytest_args,
            extensive=args.extensive,
            fast=args.fast,
            slow=args.slow,
            nwt=args.nwt,
            mf6=args.mf6,
            intercomparison=False,
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
# Selection of the tests
# ---------------------------------------------------------------------------


def _selected_tiers(extensive: bool, fast: bool) -> list[str]:
    tiers: list[str] = []
    if fast:
        tiers.append("fast")
    if extensive:
        tiers.append("extensive")
    return tiers or ["fast", "extensive"]


def _append_marker_filter(
    pytest_args: list[str],
    extensive: bool,
    fast: bool,
    slow: bool,
    nwt: bool,
    mf6: bool,
    intercomparison: bool,
    *,
    validation: bool = False,
    steady: bool = False,
    transient: bool = False,
    analytical: bool = False,
) -> None:
    if fast and slow:
        refuse("Cannot use --fast and --slow together.", EXIT_USAGE)
    if nwt and mf6:
        refuse("Cannot use --nwt and --mf6 together.", EXIT_USAGE)
    if steady and transient:
        refuse("Cannot use --steady and --transient together.", EXIT_USAGE)
    if validation and extensive:
        refuse("Cannot use --extensive with validation tests.", EXIT_USAGE)

    markers: list[str] = []
    if validation:
        markers.append("validation")
        if fast:
            markers.append("fast")
        if slow:
            markers.append("slow")
    else:
        selected_tiers = _selected_tiers(extensive, fast)
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
    if intercomparison:
        markers.append("intercomparison")
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
        refuse("Cannot use --fast and --slow together.", EXIT_USAGE)
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
        if base.endswith("_s_short_new"):
            base = base[: -len("_s_short_new")]
        elif base.endswith("_s_short"):
            base = base[: -len("_s_short")]
        variant = "short" if is_short else "full"
        tests.setdefault(base, {"full": [], "short": []})
        tests[base][variant].append(p)
    return tests


def _list_regression_tests(
    regression_dir: Path,
    *,
    extensive: bool = False,
    fast: bool = False,
) -> None:
    tests = _discover_regression_tests(
        regression_dir,
        selected_tiers=_selected_tiers(extensive, fast),
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
            refuse(
                f"Ambiguous regression name '{name}'. Candidates: {', '.join(sorted(candidates))}",
                EXIT_USAGE,
            )

    if not available:
        refuse(f"No regression test named '{name}' for selected tier(s).", EXIT_USAGE)

    matched_base = available[0]
    variants = tests[matched_base]
    variant = "short" if short else "full"
    selected_files = variants[variant]

    if short and not selected_files and variants["full"]:
        print(
            f"[tools.dev] No short regression found for '{matched_base}'. "
            "Falling back to full regression.",
            file=sys.stderr,
        )
        selected_files = variants["full"]

    if not selected_files:
        refuse(
            f"No regression files found for '{matched_base}' and selected tier(s).",
            EXIT_USAGE,
        )

    for path in sorted(selected_files):
        pytest_args.append(str(path))


def _append_regression_directory_selection(
    *,
    pytest_args: list[str],
    regression_dir: Path,
    extensive: bool,
    fast: bool,
) -> None:
    tiers = _selected_tiers(extensive, fast)
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
        refuse("No regression tests found for selected tier(s).", EXIT_USAGE)
