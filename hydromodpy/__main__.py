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
    hmp test regression --list
    hmp test regression example_09
    hmp test regression example12
    hmp test regression example_09 --short
    hmp test regression --update-goldens
"""

from __future__ import annotations

import re
import subprocess
import sys
import argparse
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

_ALLOWED_REGRESSION_BASES = {"example12", "launcher_simulation"}


def _discover_regression_tests(
    regression_dir: Path,
) -> dict[str, dict[str, list[Path]]]:
    """Return ``{base_name: {"full": [...], "short": [...]}}``.

    Scans all ``test_*regression*.py`` files and groups them by base name.
    """
    tests: dict[str, dict[str, list[Path]]] = {}
    for p in sorted(regression_dir.glob("test_*regression*.py")):
        m = _RE_REGRESSION.match(p.name)
        if not m:
            continue
        base = m.group("base")
        if base not in _ALLOWED_REGRESSION_BASES:
            continue
        is_short = "s_short" in p.name
        variant = "short" if is_short else "full"
        tests.setdefault(base, {"full": [], "short": []})
        tests[base][variant].append(p)
    return tests


def _list_regression_tests(regression_dir: Path) -> None:
    """Print available regression test names."""
    tests = _discover_regression_tests(regression_dir)
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

    if args.suite == "unit":
        pytest_args.append(str(root / "tests" / "unit"))

    elif args.suite == "regression":
        regression_dir = root / "tests" / "regression"

        if args.list:
            _list_regression_tests(regression_dir)
            return

        if args.name is not None:
            all_tests = _discover_regression_tests(regression_dir)
            name = args.name

            if name not in all_tests:
                print(
                    f"Unknown regression test '{name}'.\n"
                    f"Available tests:",
                    file=sys.stderr,
                )
                _list_regression_tests(regression_dir)
                sys.exit(1)

            variant = "short" if args.short else "full"
            matches = all_tests[name][variant]

            if not matches:
                print(
                    f"No {variant} variant for '{name}'.",
                    file=sys.stderr,
                )
                sys.exit(1)

            for m in matches:
                pytest_args.append(str(m))
        else:
            pytest_args.append(str(regression_dir))
            if args.fast:
                pytest_args.extend(["-m", "fast"])
            elif args.slow:
                pytest_args.extend(["-m", "slow"])

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
        help="Regression test name (e.g. example_09, example12). Use --list to see available.",
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
