"""
HydroModPy command-line interface.

Usage (hmp and hydromodpy are interchangeable):
    hmp init                              # creates ~/hydromodpy/
    hmp init --path /mnt/shared/hydrodata # creates at custom location

    hmp new my_project                    # create project in workspace
    hmp new my_project --workspace /path  # specify workspace root

    hmp config my_config.toml
    hmp config --profile user --modules geographic
    hmp config --list-modules

    hmp run config.toml                   # run a simulation from a TOML file
    hmp compare config_method_comparison.toml # compare solver/mesh methods

    hmp display config.toml               # generate figures from existing outputs
    hmp display config.toml --save        # force saving figures to disk
    hmp display config.toml --no-show     # headless mode (no interactive display)

    hmp list                              # list projects in workspace
    hmp list my_project                   # list runs in a project

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
    hmp test validation
    hmp test validation --fast
    hmp test validation --steady --nwt
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
    *,
    validation: bool = False,
    steady: bool = False,
    transient: bool = False,
    analytical: bool = False,
) -> None:
    """Append pytest marker filters from CLI flags."""
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
    """Create HydroModPy workspace with shared data and projects directory."""
    from hydromodpy.data.scaffold import scaffold

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
    print(f"  3. Run: hmp new <project_name>")
    print(f"  4. Edit projects/<project>/project.toml with your settings")


def _cmd_new(args: argparse.Namespace) -> None:
    """Create a new project inside a workspace."""
    from hydromodpy.data.scaffold import create_project, DEFAULT_ROOT

    workspace_root = Path(args.workspace or DEFAULT_ROOT).expanduser().resolve()
    if not (workspace_root / "data").is_dir() and not (workspace_root / "projects").is_dir():
        print(
            f"'{workspace_root}' does not look like a HydroModPy workspace. "
            "Run 'hmp init' first or use --workspace.",
            file=sys.stderr,
        )
        sys.exit(1)

    project_dir = create_project(workspace_root, args.project)
    print(f"Project created: {project_dir}")
    print()
    print("Files:")
    print(f"  {project_dir / 'project.toml'}   <- shared settings")
    print(f"  {project_dir / 'run_demo.toml'}   <- executable run")
    print()
    print("Next steps:")
    print(f"  1. Edit project.toml with your geographic/domain/flow settings")
    print(f"  2. Run: hmp run {project_dir / 'run_demo.toml'}")


def _cmd_config(args: argparse.Namespace) -> None:
    """Generate a TOML configuration template."""
    from hydromodpy.core.config.generate_toml import generate_toml, available_modules

    if args.list_modules:
        for name in available_modules():
            print(name)
        return

    if getattr(args, "ui", False):
        import subprocess
        ui_module = Path(__file__).resolve().parent / "core" / "config" / "streamlit_config.py"
        cmd = [sys.executable, "-m", "streamlit", "run", str(ui_module), "--server.headless", "true"]
        if args.output:
            cmd.extend(["--", "--load", str(args.output)])
        print("Launching interactive config editor...")
        subprocess.run(cmd)
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


def _derive_run_id_from_filename(toml_path: Path) -> str:
    """Derive run_id from TOML filename: run_steady_nwt.toml -> steady_nwt."""
    stem = toml_path.stem
    return re.sub(r"^run_", "", stem)


def _cmd_run(args: argparse.Namespace) -> None:
    """Run a simulation from a TOML configuration file."""
    from hydromodpy.core.tools.toolbox import print_hydromodpy
    from launchers import HydroModPyLauncher

    print_hydromodpy()
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    launcher = HydroModPyLauncher(config_path)
    run_state = launcher.run()

    print(f"Simulation complete: {config_path.name}", file=sys.stderr)
    model_ids = list(run_state.execution.models_by_run_id.keys())
    if model_ids:
        print(f"Produced models: {', '.join(model_ids)}", file=sys.stderr)


def _cmd_compare(args: argparse.Namespace) -> None:
    """Run a method-comparison launcher from a TOML configuration file."""
    from hydromodpy.core.tools.toolbox import print_hydromodpy
    from launchers import MethodComparisonLauncher

    print_hydromodpy()
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    summary = MethodComparisonLauncher(config_path).run()
    print(
        f"Method comparison complete: {summary['comparison_id']}",
        file=sys.stderr,
    )
    print(f"Manifest: {summary['manifest_path']}", file=sys.stderr)
    print(f"Observables: {summary['observables_csv']}", file=sys.stderr)


def _cmd_list(args: argparse.Namespace) -> None:
    """List projects or runs inside a workspace."""
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    workspace_root = Path(args.workspace or DEFAULT_ROOT).expanduser().resolve()
    projects_dir = workspace_root / "projects"

    if not projects_dir.is_dir():
        print(f"No projects/ directory found in {workspace_root}", file=sys.stderr)
        sys.exit(1)

    if args.project:
        # List runs for a specific project
        project_dir = projects_dir / args.project
        if not project_dir.is_dir():
            print(f"Project not found: {args.project}", file=sys.stderr)
            sys.exit(1)
        sims_dir = project_dir / "results_simulations"
        if not sims_dir.is_dir():
            print(f"No results_simulations/ in {args.project}")
            return
        for run_dir in sorted(sims_dir.iterdir()):
            if run_dir.is_dir() and not run_dir.name.startswith("_"):
                metrics_file = run_dir / "_metrics.json"
                status = " (has metrics)" if metrics_file.exists() else ""
                print(f"  {run_dir.name}{status}")
    else:
        # List all projects
        for project_dir in sorted(projects_dir.iterdir()):
            if project_dir.is_dir():
                has_project_toml = (project_dir / "project.toml").exists()
                run_tomls = list(project_dir.glob("run_*.toml"))
                details = []
                if has_project_toml:
                    details.append("project.toml")
                if run_tomls:
                    details.append(f"{len(run_tomls)} run(s)")
                suffix = f"  [{', '.join(details)}]" if details else ""
                print(f"  {project_dir.name}{suffix}")


def _cmd_test(args: argparse.Namespace) -> None:
    """Run tests via pytest."""
    root = _find_project_root()
    pytest_args = [sys.executable, "-m", "pytest", "-v"]
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
    sys.exit(subprocess.call(pytest_args))


def _cmd_overview(args: argparse.Namespace) -> None:
    """Generate a watershed identity card from a TOML configuration file."""
    from launchers import DataOverviewLauncher

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    summary = DataOverviewLauncher(config_path).run()
    report_paths = summary.get("report_paths", [])
    if report_paths:
        print(f"\nOverview complete - {len(report_paths)} panel(s) generated.", file=sys.stderr)
    else:
        print("Overview complete - no panels generated.", file=sys.stderr)


def _cmd_display(args: argparse.Namespace) -> None:
    """Generate display figures from existing simulation outputs."""
    import tomllib

    from hydromodpy.analysis.display.options import display_options_from_raw_toml
    from hydromodpy.analysis.display.posthoc import PosthocContext
    from hydromodpy.analysis.display.posthoc_orchestration import plot_posthoc_all

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        raw_toml = tomllib.load(f)

    # Override show/save from CLI flags
    display_section = dict(raw_toml.get("display", {}))
    if args.save:
        display_section["save"] = True
    if args.no_show:
        display_section["show"] = False
    raw_toml_patched = dict(raw_toml)
    raw_toml_patched["display"] = display_section
    options = display_options_from_raw_toml(raw_toml_patched)

    ctx = PosthocContext.from_toml(config_path)
    if not ctx.runs:
        print("No simulation runs found. Run a simulation first.", file=sys.stderr)
        sys.exit(1)

    print(
        f"Generating figures for {len(ctx.runs)} run(s): "
        f"{', '.join(r.run_id for r in ctx.runs)}",
        file=sys.stderr,
    )

    figure_dirs = plot_posthoc_all(ctx, options)
    for d in figure_dirs:
        n_figs = len(list(d.glob("*.png")))
        print(f"  {d.relative_to(config_path.parent)}: {n_figs} figure(s)", file=sys.stderr)

    if not figure_dirs:
        print("No figures generated. Check display options.", file=sys.stderr)


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
        help="Create HydroModPy workspace (data + projects). Default: ~/hydromodpy/",
    )
    init_parser.add_argument(
        "--path",
        default=None,
        help="Workspace path (default: ~/hydromodpy/)",
    )

    # --- new subcommand ---
    new_parser = subparsers.add_parser(
        "new",
        help="Create a new project inside the workspace",
    )
    new_parser.add_argument(
        "project",
        help="Project name (will be created under projects/)",
    )
    new_parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: ~/hydromodpy/)",
    )

    # --- config subcommand ---
    from hydromodpy.core.config.generate_toml import PROFILES

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
    config_parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch interactive Streamlit configuration editor",
    )

    # --- run subcommand (replaces 'simulation') ---
    run_parser = subparsers.add_parser(
        "run",
        help="Run a simulation from a TOML configuration file",
    )
    run_parser.add_argument(
        "config",
        type=Path,
        help="Path to the run TOML file",
    )

    # --- compare subcommand ---
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare solver/mesh methods from a TOML configuration file",
    )
    compare_parser.add_argument(
        "config",
        type=Path,
        help="Path to the method-comparison TOML file",
    )

    # --- display subcommand ---
    display_parser = subparsers.add_parser(
        "display",
        help="Generate figures from existing simulation outputs",
    )
    display_parser.add_argument(
        "config",
        type=Path,
        help="Path to the project TOML file",
    )
    display_parser.add_argument(
        "--save",
        action="store_true",
        help="Force saving figures to disk (overrides TOML display.save)",
    )
    display_parser.add_argument(
        "--no-show",
        action="store_true",
        help="Disable interactive display (overrides TOML display.show)",
    )

    # --- overview subcommand ---
    overview_parser = subparsers.add_parser(
        "overview",
        help="Generate a watershed identity card from a TOML file",
    )
    overview_parser.add_argument(
        "config",
        type=Path,
        help="Path to the overview TOML file",
    )

    # Keep 'simulation' as hidden alias for backwards compatibility
    sim_parser = subparsers.add_parser(
        "simulation",
        help=argparse.SUPPRESS,
    )
    sim_parser.add_argument(
        "config",
        type=Path,
        help="Path to the simulation TOML file",
    )
    sim_parser.add_argument(
        "--out",
        default=None,
        help=argparse.SUPPRESS,
    )

    # --- list subcommand ---
    list_parser = subparsers.add_parser(
        "list",
        help="List projects or runs in a workspace",
    )
    list_parser.add_argument(
        "project",
        nargs="?",
        help="Project name to list runs for (omit for project listing)",
    )
    list_parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (default: ~/hydromodpy/)",
    )

    # --- test subcommand ---
    test_parser = subparsers.add_parser(
        "test",
        help="Run unit, regression, or validation tests",
    )
    test_parser.add_argument(
        "suite",
        choices=["unit", "regression", "validation"],
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
        "--steady",
        action="store_true",
        help="Filter to steady-state tests when the marker is available",
    )
    test_parser.add_argument(
        "--transient",
        action="store_true",
        help="Filter to transient tests when the marker is available",
    )
    test_parser.add_argument(
        "--analytical",
        action="store_true",
        help="Filter to analytical validation tests",
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
    elif args.command == "new":
        _cmd_new(args)
    elif args.command == "config":
        _cmd_config(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "compare":
        _cmd_compare(args)
    elif args.command == "simulation":
        _cmd_run(args)
    elif args.command == "display":
        _cmd_display(args)
    elif args.command == "overview":
        _cmd_overview(args)
    elif args.command == "list":
        _cmd_list(args)
    elif args.command == "test":
        _cmd_test(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
