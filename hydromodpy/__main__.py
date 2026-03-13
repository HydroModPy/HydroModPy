"""
HydroModPy command-line interface.

Usage (hmp and hydromodpy are interchangeable):
    hmp init                              # creates ~/hydromodpy/
    hmp init --path /mnt/shared/hydrodata # creates at custom location

    hmp config my_config.toml
    hmp config --profile user --modules geographic
    hmp config --list-modules

    hmp simulation config.toml            # run a simulation from a TOML file
    hmp simulation config.toml --out /tmp/results

    hmp test unit
    hmp test regression
    hmp test regression --fast
    hmp test regression --extensive
    hmp test regression --slow
    hmp test regression --nwt
    hmp test regression --mf6
    hmp test regression --normal
    hmp test regression --list
    hmp test regression launcher_simulation_fast_nwt --fast --nwt
    hmp test regression launcher_simulation_fast_mf6 --fast --mf6
    hmp test regression launcher_simulation_extensive_nwt --extensive --nwt
    hmp test regression launcher_simulation_extensive_mf6 --extensive --mf6
    hmp test regression --update-goldens
"""

from __future__ import annotations

import argparse
import os
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

_REGRESSION_TIERS = ("fast", "extensive")


def _selected_tiers(normal: bool, extensive: bool, fast: bool) -> list[str]:
    """Return regression tiers requested from CLI flags."""
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
) -> None:
    """Append pytest marker filters from CLI flags."""
    if (normal or fast) and slow:
        print("Cannot use --fast and --slow together.", file=sys.stderr)
        sys.exit(2)
    if nwt and mf6:
        print("Cannot use --nwt and --mf6 together.", file=sys.stderr)
        sys.exit(2)

    markers: list[str] = []
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
    fast: bool = False,
) -> None:
    """Print available regression test names."""
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
    fast: bool,
) -> None:
    """Append one or more regression tier directories to pytest selection."""
    tiers = _selected_tiers(normal, extensive, fast)
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

def _cmd_init(args: argparse.Namespace) -> None:
    """Create HydroModPy workspace with shared data and example project."""
    from hydromodpy.data_managers.scaffold import scaffold

    result = scaffold(args.path)

    print(f"Workspace: {result}")
    print()
    print("Structure:")
    for p in sorted(result.rglob("*")):
        rel = p.relative_to(result)
        indent = "  " * len(rel.parts)
        if p.is_dir():
            print(f"  {indent}{rel.name}/")
        else:
            print(f"  {indent}{rel.name}")
    print()
    print("Next steps:")
    print(f"  1. Fill data/*_LOC.csv with your station coordinates (id,x,y,crs)")
    print(f"  2. Add chronicle CSVs per station in data/<variable>/")
    print(f"  3. Copy bv_example/ to create your own watershed project")
    print(f"  4. Edit <your_bv>/data_managers.toml to configure sources")


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


def _cmd_simulation(args: argparse.Namespace) -> None:
    """Run a simulation from a TOML configuration file."""
    from launchers import HydroModPyLauncher

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        os.environ["HYDROMODPY_OUT_PATH"] = str(Path(args.out).expanduser().resolve())

    launcher = HydroModPyLauncher(config_path)
    run_state = launcher.run()

    print(f"Simulation complete: {config_path.name}", file=sys.stderr)
    model_ids = list(run_state.execution.models_by_run_id.keys())
    if model_ids:
        print(f"Produced models: {', '.join(model_ids)}", file=sys.stderr)


def _cmd_test(args: argparse.Namespace) -> None:
    """Run tests via pytest."""
    root = _find_project_root()
    pytest_args = ["pytest", "-v"]
    tiers = _selected_tiers(args.normal, args.extensive, args.fast)

    if args.suite == "unit":
        pytest_args.append(str(root / "tests" / "unit"))

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

    # --- init subcommand ---
    init_parser = subparsers.add_parser(
        "init",
        help="Create HydroModPy workspace (data + cache + example BV). Default: ~/hydromodpy/",
    )
    init_parser.add_argument(
        "--path",
        default=None,
        help="Workspace path (default: ~/hydromodpy/)",
    )

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

    # --- simulation subcommand ---
    sim_parser = subparsers.add_parser(
        "simulation",
        help="Run a simulation from a TOML configuration file",
    )
    sim_parser.add_argument(
        "config",
        type=Path,
        help="Path to the simulation TOML file",
    )
    sim_parser.add_argument(
        "--out",
        default=None,
         help="Override output directory (sets HYDROMODPY_OUT_PATH)",
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
            "(e.g. launcher_simulation_fast_nwt, launcher_simulation_extensive_mf6). "
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
        help="Only run fast-tier regression tests",
    )
    test_parser.add_argument(
        "--slow",
        action="store_true",
        help="Only run slow regression tests",
    )
    test_parser.add_argument(
        "--normal",
        action="store_true",
        help="Deprecated alias for --fast",
    )
    test_parser.add_argument(
        "--extensive",
        action="store_true",
        help="Only run extensive regression tests",
    )
    test_parser.add_argument(
        "--nwt",
        action="store_true",
        help="Only run MODFLOW-NWT / MODPATH / MT3DMS regression tests",
    )
    test_parser.add_argument(
        "--mf6",
        action="store_true",
        help="Only run MODFLOW 6 / GWT regression tests",
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

    if args.command == "init":
        _cmd_init(args)
    elif args.command == "config":
        _cmd_config(args)
    elif args.command == "simulation":
        _cmd_simulation(args)
    elif args.command == "test":
        _cmd_test(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
