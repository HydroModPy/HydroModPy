"""
HydroModPy command-line interface.

Usage (hmp and hydromodpy are interchangeable):
    hmp config my_config.toml
    hmp config --profile user --modules geographic
    hmp config --list-modules

    hmp test unit
    hmp test regression
    hmp test regression --fast
    hmp test regression --slow
    hmp test regression --normal
    hmp test regression --extensive
    hmp test regression --list
    hmp test regression launcher_simulation_normal --normal
    hmp test regression launcher_simulation --extensive
    hmp test regression --update-goldens
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _find_project_root() -> Path:
    """Walk up from this file to find the directory containing tests/."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "tests").is_dir():
            return parent
    return Path.cwd()


# ---------------------------------------------------------------------------
# Regression test discovery
# ---------------------------------------------------------------------------

_RE_REGRESSION = re.compile(
    r"^test_"
    r"(?P<base>.+?)"
    r"(?:s_short(?:_new)?)?_"
    r"(?:npy_)?regression"
    r"(?:_\w+)?"
    r"\.py$"
)

_REGRESSION_TIERS = ("normal", "extensive")


def _selected_tiers(normal: bool, extensive: bool) -> list[str]:
    """Return regression tiers requested from CLI flags."""
    if normal and extensive:
        return ["normal", "extensive"]
    if normal:
        return ["normal"]
    if extensive:
        return ["extensive"]
    return ["normal", "extensive"]


def _append_marker_filter(
    pytest_args: list[str],
    normal: bool,
    extensive: bool,
    fast: bool,
    slow: bool,
) -> None:
    """Append pytest marker filters from CLI flags."""
    if fast and slow:
        print("Cannot use --fast and --slow together.", file=sys.stderr)
        sys.exit(2)

    markers: list[str] = []
    if normal and not extensive:
        markers.append("normal")
    elif extensive and not normal:
        markers.append("extensive")
    if fast:
        markers.append("fast")
    if slow:
        markers.append("slow")

    if markers:
        pytest_args.extend(["-m", " and ".join(markers)])

def _discover_regression_tests(
    regression_dir: Path,
    selected_tiers: list[str] | None = None,
) -> dict[str, dict[str, list[Path]]]:
    """Return ``{base_name: {"full": [...], "short": [...]}}`` grouped by file base.

    Scans all ``test_*regression*.py`` files (including nested directories),
    optionally restricted to selected tier directories.
    """
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
) -> None:
    """Print available regression test names."""
    tests = _discover_regression_tests(
        regression_dir,
        selected_tiers=_selected_tiers(normal, extensive),
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
    """Append selected regression files for a specific test name.

    Name can be provided as the exact base name or with a unique prefix.
    """
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
) -> None:
    """Append one or more regression tier directories to pytest selection."""
    tiers = _selected_tiers(normal, extensive)
    selected = False

    for tier in tiers:
        tier_dir = regression_dir / tier
        if not tier_dir.exists():
            continue
        has_tests = any(
            _RE_REGRESSION.match(p.name)
            for p in tier_dir.rglob("test_*regression*.py")
        )
        if not has_tests:
            continue
        pytest_args.append(str(tier_dir))
        selected = True

    if not selected:
        print("No regression tests found for selected tier(s).", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_config(args: argparse.Namespace) -> None:
    """Generate a TOML configuration template."""
    from hydromodpy.config.generate_toml import generate_toml, available_modules

    if args.list_modules:
        for name in available_modules():
            print(name)
        return

    if args.output and Path(args.output).is_dir():
        args.output = str(Path(args.output) / "config.toml")

    content = generate_toml(
        output_path=args.output,
        modules=args.modules,
        profile=args.profile,
    )

    if args.output:
        print(f"Written to: {Path(args.output).resolve()}", file=sys.stderr)
    else:
        print(content)


def _cmd_test(args: argparse.Namespace) -> None:
    """Run tests via pytest."""
    root = _find_project_root()
    pytest_args = ["pytest", "-v"]
    tiers = _selected_tiers(args.normal, args.extensive)

    if args.suite == "unit":
        pytest_args.append(str(root / "tests" / "unit"))

    elif args.suite == "regression":
        regression_dir = root / "tests" / "regression"

        if args.list:
            _list_regression_tests(
                regression_dir,
                normal=args.normal,
                extensive=args.extensive,
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
            )

        _append_marker_filter(
            pytest_args=pytest_args,
            normal=args.normal,
            extensive=args.extensive,
            fast=args.fast,
            slow=args.slow,
        )

        if args.update_goldens:
            pytest_args.append("--update-goldens")

    if args.jobs is not None:
        pytest_args.extend(["-n", args.jobs])

    print(f"Running: {' '.join(pytest_args)}", file=sys.stderr)
    sys.exit(subprocess.call(pytest_args))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    prog = Path(sys.argv[0]).stem if sys.argv[0] else "hmp"
    parser = argparse.ArgumentParser(
        prog=prog,
        description="HydroModPy command-line interface",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- config subcommand ---
    from hydromodpy.config.generate_toml import PROFILES

    config_parser = subparsers.add_parser(
        "config",
        help="Generate a TOML configuration template",
    )
    config_parser.add_argument(
        "output",
        nargs="?",
        help="Output file path (prints to stdout if not provided)",
    )
    config_parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default="expert",
        help="Parameter visibility level (default: expert)",
    )
    config_parser.add_argument(
        "--modules",
        nargs="+",
        help="Module sections to include (default: all). Use --list-modules to see available.",
    )
    config_parser.add_argument(
        "--list-modules",
        action="store_true",
        help="List available module names and exit",
    )

    # --- test subcommand ---
    test_parser = subparsers.add_parser(
        "test",
        help="Run unit or regression tests",
    )
    test_parser.add_argument(
        "suite",
        choices=["unit", "regression"],
        help="Test suite to run",
    )
    test_parser.add_argument(
        "name",
        nargs="?",
        help=(
            "Regression test name "
            "(e.g. launcher_simulation_normal, launcher_simulation). "
            "Use --list to see available."
        ),
    )
    test_parser.add_argument(
        "--list",
        action="store_true",
        help="List available regression test names and exit",
    )
    test_parser.add_argument(
        "--fast",
        action="store_true",
        help="Only run fast regression tests",
    )
    test_parser.add_argument(
        "--slow",
        action="store_true",
        help="Only run slow regression tests",
    )
    test_parser.add_argument(
        "--normal",
        action="store_true",
        help="Only run normal regression tests",
    )
    test_parser.add_argument(
        "--extensive",
        action="store_true",
        help="Only run extensive regression tests",
    )
    test_parser.add_argument(
        "--short",
        action="store_true",
        help="Run the short variant of a specific test",
    )
    test_parser.add_argument(
        "--update-goldens",
        action="store_true",
        help="Update golden reference files instead of asserting",
    )
    test_parser.add_argument(
        "-j", "--jobs",
        default=None,
        help="Number of parallel workers (requires pytest-xdist). e.g. -j4, -j auto",
    )

    args = parser.parse_args()

    if args.command == "config":
        _cmd_config(args)
    elif args.command == "test":
        _cmd_test(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
