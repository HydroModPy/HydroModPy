"""
HydroModPy command-line interface.

Usage (hmp and hydromodpy are interchangeable):
    hmp init [--path PATH]                # create workspace
    hmp new <project> [--workspace PATH]  # create project

    hmp config [output.toml]              # generate TOML template
    hmp run <config.toml | script.py>     # execute (auto-detect workflow)
    hmp display <config.toml>             # generate figures post-hoc

    hmp list [project] [--workspace PATH] # list projects or runs
    hmp export <project> [--sim NAME]     # export results
    hmp test <suite>                      # run tests

``hmp run`` auto-detects the workflow from the TOML sections present:
    [simulation] or [flow]   -> simulation (via Simulation)
    [overview]               -> watershed identity card
    [mesh_catchment]         -> mesh-only pipeline
    [calibration]            -> calibration loop (Phase 4)
    [batch]                  -> regional batch  (Phase 4)
    hmp compare config_method_comparison.toml # compare solver/mesh methods

    hmp test unit
    hmp test regression [--fast|--extensive|--nwt|--mf6|--list|--update-goldens]
    hmp test validation [--fast|--steady|--nwt]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_project_root() -> Path:
    """Walk up from this file to find the directory containing tests/."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "tests").is_dir():
            return parent
    return Path.cwd()


def _find_workspace_root(project_dir: Path) -> Path:
    """Walk up from *project_dir* to find the directory containing hydromodpy.duckdb."""
    for parent in [project_dir] + list(project_dir.parents):
        if (parent / "hydromodpy.duckdb").exists():
            return parent
    return project_dir


def _resolve_test_scratch_root() -> Path:
    """Return the shared repository-external scratch root for test runs."""
    override = os.environ.get("HYDROMODPY_TEST_SCRATCH_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "hydromodpy_tests").resolve()


def _pytest_addopts_declares_basetemp(pytest_addopts: str) -> bool:
    """Return True when ``PYTEST_ADDOPTS`` already declares ``--basetemp``."""
    return re.search(r"(^|\\s)--basetemp(?:=|\\s|$)", str(pytest_addopts)) is not None


def _build_pytest_runtime_env() -> tuple[Path, dict[str, str]]:
    """Prepare one external scratch root for pytest internals and subprocesses."""
    scratch_root = _resolve_test_scratch_root()
    tmp_root = scratch_root / "tmp"
    pytest_root = scratch_root / "pytest"
    basetemp_root = pytest_root / f"cli_{os.getpid()}"
    for path in (scratch_root, tmp_root, pytest_root, basetemp_root):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HYDROMODPY_TEST_SCRATCH_ROOT"] = str(scratch_root)
    env["PYTEST_DEBUG_TEMPROOT"] = str(pytest_root)
    env["TMPDIR"] = str(tmp_root)
    env["TMP"] = str(tmp_root)
    env["TEMP"] = str(tmp_root)
    return basetemp_root, env


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


def _append_unit_marker_filter(
    pytest_args: list[str],
    *,
    fast: bool,
    slow: bool,
) -> None:
    """Append unit-test marker filters for daily/nightly style runs."""
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

    if args.output == "schema":
        _cmd_config_schema(args)
        return

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


def _cmd_config_schema(args: argparse.Namespace) -> None:
    """Export the JSON Schema for the HydroModPy configuration.

    Usage::

        hmp config schema                        # full root schema to stdout
        hmp config schema --section flow         # single section
        hmp config schema --out schema.json      # write to file
    """
    from hydromodpy.core.config.schema_export import (
        ROOT_SECTIONS,
        export_schema,
        write_schema,
        _ensure_root_sections,
    )

    if getattr(args, "list_sections", False):
        for name in sorted(_ensure_root_sections()):
            print(name)
        return

    section = getattr(args, "section", None)
    out_path = getattr(args, "out", None)

    if out_path:
        written = write_schema(out_path, section=section)
        print(f"Written to: {written}", file=sys.stderr)
        return

    schema = export_schema(section=section)
    print(json.dumps(schema, indent=2, ensure_ascii=False))


def _derive_run_id_from_filename(toml_path: Path) -> str:
    """Derive run_id from TOML filename: run_steady_nwt.toml -> steady_nwt."""
    stem = toml_path.stem
    return re.sub(r"^run_", "", stem)


def _cmd_run(args: argparse.Namespace) -> None:
    """Run a simulation (.toml) or a prototype script (.py)."""
    target = Path(args.config).expanduser().resolve()
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(1)

    if target.suffix == ".py":
        _cmd_run_script(target, getattr(args, "script_args", []))
    elif target.suffix == ".toml":
        _cmd_run_toml(target)
    else:
        print(
            f"Unsupported file type: {target.suffix} (expected .toml or .py)",
            file=sys.stderr,
        )
        sys.exit(1)


def _cmd_run_toml(config_path: Path) -> None:
    """Run a workflow from a TOML file (auto-detected from sections)."""
    import importlib
    import tomllib

    from hydromodpy.core.tools.display import print_hydromodpy
    from hydromodpy.runners import detect_workflow

    print_hydromodpy()

    with open(config_path, "rb") as f:
        raw_toml = tomllib.load(f)

    workflow = detect_workflow(raw_toml)

    dispatch = {
        "simulation": "hydromodpy.runners.simulation",
        "overview": "hydromodpy.runners.overview",
        "mesh": "hydromodpy.runners.mesh",
        "calibration": "hydromodpy.runners.calibration",
        "batch": "hydromodpy.runners.batch",
    }

    module = importlib.import_module(dispatch[workflow])
    summary = module.run(config_path)

    print(f"Workflow '{workflow}' complete: {config_path.name}", file=sys.stderr)
    if summary:
        for key, value in summary.items():
            print(f"  {key}: {value}", file=sys.stderr)


def _cmd_run_script(script_path: Path, extra_args: list[str]) -> None:
    """Run a Python prototype script as a subprocess."""
    from hydromodpy.core.tools.display import print_hydromodpy

    print_hydromodpy()
    cmd = [sys.executable, str(script_path), *extra_args]
    result = subprocess.run(cmd, cwd=str(script_path.parent))
    sys.exit(result.returncode)


def _cmd_list(args: argparse.Namespace) -> None:
    """List projects or runs inside a workspace."""
    from hydromodpy.data.scaffold import DEFAULT_ROOT

    workspace_root = Path(args.workspace or DEFAULT_ROOT).expanduser().resolve()
    projects_dir = workspace_root / "projects"

    if not projects_dir.is_dir():
        print(f"No projects/ directory found in {workspace_root}", file=sys.stderr)
        sys.exit(1)

    if args.project:
        project_dir = projects_dir / args.project
        if not project_dir.is_dir():
            print(f"Project not found: {args.project}", file=sys.stderr)
            sys.exit(1)
        workspace_root = _find_workspace_root(project_dir)
        db_path = workspace_root / "hydromodpy.duckdb"
        if not db_path.exists():
            print(f"No hydromodpy.duckdb in {workspace_root}")
            return
        try:
            from hydromodpy.results.catalog import SimulationCatalog
            catalog = SimulationCatalog(workspace_root)
            sims = catalog.list_simulations(project=args.project)
            if sims.empty:
                print(f"  No simulations recorded in {args.project}")
            else:
                for _, row in sims.iterrows():
                    sim_id = str(row["sim_id"])
                    name = row.get("name", "")
                    solver = row.get("solver", "")
                    status = row.get("status", "")
                    dur = row.get("duration_s")
                    label = name or sim_id[:8]
                    dur_str = f" {dur:.1f}s" if dur else ""
                    print(f"  {label}  solver={solver}  status={status}{dur_str}")
            catalog.close()
        except Exception as exc:
            print(f"  Error reading hydromodpy.duckdb: {exc}", file=sys.stderr)
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
    basetemp_root, pytest_env = _build_pytest_runtime_env()
    if not _pytest_addopts_declares_basetemp(pytest_env.get("PYTEST_ADDOPTS", "")):
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


def _cmd_display(args: argparse.Namespace) -> None:
    """Generate display figures from existing simulation outputs."""
    subcommand = getattr(args, "config_or_subcommand", None)

    if subcommand == "compare":
        _cmd_display_compare(args)
        return

    if subcommand is None:
        print("Usage: hmp display <config.toml>  or  hmp display compare --sim A --sim B", file=sys.stderr)
        sys.exit(1)

    import tomllib

    from hydromodpy.analysis.display.display_config import display_options_from_raw_toml
    from hydromodpy.analysis.display.posthoc import PosthocContext
    from hydromodpy.analysis.display.posthoc_orchestration import plot_posthoc_all

    config_path = Path(subcommand).expanduser().resolve()
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "rb") as f:
        raw_toml = tomllib.load(f)

    # hmp display always saves; override show/save from CLI flags.
    display_section = dict(raw_toml.get("display", {}))
    display_section["save"] = True  # posthoc always saves
    if args.no_show:
        display_section["show"] = False
    raw_toml_patched = dict(raw_toml)
    raw_toml_patched["display"] = display_section
    options = display_options_from_raw_toml(raw_toml_patched)

    project_dir = config_path.parent.resolve()
    project_name = project_dir.name
    workspace_root = _find_workspace_root(project_dir)
    catalog = None
    db_path = workspace_root / "hydromodpy.duckdb"
    if db_path.exists():
        from hydromodpy.results.catalog import SimulationCatalog
        catalog = SimulationCatalog(workspace_root)

    if catalog is not None:
        # Resolve the latest sim_id for this project.
        _sims = catalog.list_simulations(project=project_name)
        _latest_sim_id = str(_sims.iloc[-1]["sim_id"]) if not _sims.empty else ""
        ctx = PosthocContext.from_catalog(
            project_dir, catalog,
            sim_id=_latest_sim_id,
            project=project_name,
        )
    else:
        ctx = PosthocContext.from_toml(config_path)

    if not ctx.runs and catalog is not None:
        sims = catalog.list_simulations(project=project_name)
        if not sims.empty:
            from hydromodpy.analysis.display.posthoc import RunArtifacts
            for _, row in sims.iterrows():
                sim_name = row.get("name") or str(row["sim_id"])
                ctx = PosthocContext(
                    project_dir=project_dir,
                    geographic=ctx.geographic,
                    runs=[
                        RunArtifacts(run_id=sim_name, run_dir=project_dir)
                        for _, row in sims.iterrows()
                    ],
                )
                break

    if not ctx.runs:
        print("No simulation runs found. Run a simulation first.", file=sys.stderr)
        if catalog is not None:
            catalog.close()
        sys.exit(1)

    print(
        f"Generating figures for {len(ctx.runs)} run(s): "
        f"{', '.join(r.run_id for r in ctx.runs)}",
        file=sys.stderr,
    )

    figure_dirs = plot_posthoc_all(ctx, options, store=catalog)
    if catalog is not None:
        catalog.close()

    if figure_dirs:
        for d in figure_dirs:
            n_figs = len(list(d.glob("*.png")))
            print(f"  {d.relative_to(config_path.parent)}: {n_figs} figure(s)", file=sys.stderr)
    elif not options.save:
        print("Figures displayed interactively (use --save to write to disk).", file=sys.stderr)


def _cmd_display_compare(args: argparse.Namespace) -> None:
    """Compare simulation results post-hoc."""
    from hydromodpy.analysis.display.compare import run_display_compare

    sim_names = getattr(args, "sim_names", None) or []
    if len(sim_names) < 2:
        print(
            "Usage: hmp display compare --sim <name1> --sim <name2>\n"
            "At least two --sim arguments are required.",
            file=sys.stderr,
        )
        sys.exit(1)

    run_display_compare(sim_names=sim_names)


def _cmd_export(args: argparse.Namespace) -> None:
    """Export geographic data or simulation results from the project store."""
    from hydromodpy.results.catalog import SimulationCatalog

    project_dir = Path(args.project).expanduser().resolve()
    project_name = project_dir.name
    workspace_root = _find_workspace_root(project_dir)
    db_path = workspace_root / "hydromodpy.duckdb"
    if not db_path.exists():
        print(f"No catalog found at {workspace_root}", file=sys.stderr)
        sys.exit(1)

    catalog = SimulationCatalog(workspace_root)

    if args.list:
        # Geographic data
        sims = catalog.list_simulations(project=project_name)
        rasters: list[str] = []
        if not sims.empty:
            latest_sid = str(sims.iloc[-1]["sim_id"])
            geo_grp = catalog.open_zarr_group(latest_sid).get("geographic")
            rasters = list(geo_grp.keys()) if geo_grp is not None else []
        features = catalog.list_geographic_features(latest_sid) if not sims.empty else []
        print("Geographic rasters:", file=sys.stderr)
        for name in sorted(rasters):
            print(f"  {name}", file=sys.stderr)
        print(f"\nGeographic features:", file=sys.stderr)
        for name in sorted(features):
            print(f"  {name}", file=sys.stderr)

        # Simulations
        if not sims.empty:
            print(f"\nSimulations:", file=sys.stderr)
            for _, row in sims.iterrows():
                sid = str(row["sim_id"])[:8]
                name = row.get("name", "")
                solver = row.get("solver", "")
                status = row.get("status", "")
                created = row.get("created_at", "")
                date_str = str(created)[:16] if created else ""
                print(f"  {name or sid}  solver={solver}  {date_str}  {status}", file=sys.stderr)
        catalog.close()
        return

    output_dir = Path(args.output) if args.output else None
    exported: list[Path] = []

    # --- Geographic exports ---
    if args.raster or args.feature:
        geo_dir = output_dir or (project_dir / "exports" / "geographic")
        geo_dir.mkdir(parents=True, exist_ok=True)

        if args.raster:
            sims = catalog.list_simulations(project=project_name)
            if sims.empty:
                print("  No simulations found; cannot export rasters", file=sys.stderr)
            else:
                latest_sid = str(sims.iloc[-1]["sim_id"])
                sz = catalog.open_zarr(latest_sid)
                geo_grp = sz.root.get("geographic")
                for name in args.raster:
                    try:
                        if geo_grp is None or name not in geo_grp:
                            raise KeyError(name)
                        import numpy as np
                        import rasterio
                        from rasterio.transform import Affine
                        data = np.array(geo_grp[name][:])
                        attrs = dict(geo_grp[name].attrs)
                        transform = Affine(*attrs["transform"][:6])
                        crs = attrs.get("crs", "")
                        nodata = attrs.get("nodata", -99999.0)
                        out_path = geo_dir / f"{name}.tif"
                        with rasterio.open(
                            out_path, "w", driver="GTiff",
                            height=data.shape[-2], width=data.shape[-1],
                            count=1, dtype=data.dtype,
                            crs=crs, transform=transform, nodata=nodata,
                        ) as dst:
                            dst.write(data if data.ndim == 3 else data[np.newaxis])
                        exported.append(out_path)
                        print(f"  {out_path}", file=sys.stderr)
                    except KeyError:
                        print(f"  Raster '{name}' not found in store", file=sys.stderr)

        if args.feature:
            for name in args.feature:
                try:
                    gdf = catalog.read_geographic_feature(latest_sid, name)
                    out_path = geo_dir / f"{name}.shp"
                    gdf.to_file(out_path)
                    exported.append(out_path)
                    print(f"  {out_path}", file=sys.stderr)
                except KeyError:
                    print(f"  Feature '{name}' not found in store", file=sys.stderr)

    # --- Simulation exports ---
    if args.sim:
        sim_name = args.sim
        sims = catalog.list_simulations(project=project_name)
        match = sims[sims["name"] == sim_name]
        if match.empty:
            match = sims[sims["sim_id"].str.startswith(sim_name)]
        if match.empty:
            print(f"Simulation '{sim_name}' not found (use --list)", file=sys.stderr)
            catalog.close()
            sys.exit(1)
        sim_id = match.iloc[-1]["sim_id"]
        label = sim_name

        sim_dir = output_dir or (project_dir / "exports" / label)
        sim_dir.mkdir(parents=True, exist_ok=True)

        any_format = args.csv or args.netcdf or args.geotiff or args.vtu
        if not any_format:
            args.csv = True

        if args.csv:
            out = sim_dir / "timeseries.csv"
            catalog.export(sim_id, "*", "csv", out)
            exported.append(out)
            print(f"  {out}", file=sys.stderr)

        if args.netcdf:
            out = sim_dir / "fields.nc"
            try:
                catalog.export(sim_id, "head", "netcdf", out)
                exported.append(out)
                print(f"  {out}", file=sys.stderr)
            except Exception as exc:
                print(f"  NetCDF export failed: {exc}", file=sys.stderr)

        if args.geotiff:
            grp = catalog.open_zarr_group(sim_id, mode="r")
            for var in list(grp.keys()) + list((grp.get("derived") or {}).keys()):
                if var in ("mesh", "budget", "derived", "pathlines"):
                    continue
                try:
                    out = sim_dir / f"{var}_t0.tif"
                    catalog.export(sim_id, var, "geotiff", out, timestep=0)
                    exported.append(out)
                    print(f"  {out}", file=sys.stderr)
                except Exception:
                    pass

        if args.vtu:
            out = sim_dir / "head_t0.vtu"
            try:
                catalog.export(sim_id, "head", "vtu", out, timestep=0)
                exported.append(out)
                print(f"  {out}", file=sys.stderr)
            except Exception as exc:
                print(f"  VTU export failed: {exc}", file=sys.stderr)

    catalog.close()

    if not any([args.raster, args.feature, args.sim]):
        print("Usage: hmp export <project> --list | --sim NAME [--csv --netcdf] | --raster NAME", file=sys.stderr)
        sys.exit(1)

    if exported:
        print(f"Exported {len(exported)} file(s)", file=sys.stderr)


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
        help="Generate a TOML configuration template, or export the JSON Schema",
    )
    config_parser.add_argument(
        "output",
        nargs="?",
        help=(
            "Output file path for the TOML template (prints to stdout if not "
            "provided). Use the literal word 'schema' to export the JSON "
            "Schema instead: 'hmp config schema [--section NAME] [--out FILE]'."
        ),
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
    # Schema-export flags (only active with 'hmp config schema ...').
    config_parser.add_argument(
        "--section",
        default=None,
        help=(
            "When used with 'hmp config schema', export the JSON Schema of a "
            "single root TOML section (e.g. 'flow', 'workspace')."
        ),
    )
    config_parser.add_argument(
        "--out",
        default=None,
        help="When used with 'hmp config schema', write the JSON Schema to this file.",
    )
    config_parser.add_argument(
        "--list-sections",
        action="store_true",
        help="When used with 'hmp config schema', list available section names.",
    )

    # --- run subcommand (replaces 'simulation') ---
    run_parser = subparsers.add_parser(
        "run",
        help="Run a simulation (.toml) or a prototype script (.py)",
    )
    run_parser.add_argument(
        "config",
        type=Path,
        help="Path to a TOML config or Python script",
    )
    run_parser.add_argument(
        "script_args",
        nargs="*",
        help="Extra arguments forwarded to .py scripts",
    )

    # --- display subcommand ---
    display_parser = subparsers.add_parser(
        "display",
        help="Generate figures from existing simulation outputs",
    )
    display_parser.add_argument(
        "config_or_subcommand",
        nargs="?",
        help="Path to the project TOML file, or 'compare' for post-hoc comparison",
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
    display_parser.add_argument(
        "--sim",
        action="append",
        dest="sim_names",
        help="Simulation name to compare (use twice: --sim A --sim B)",
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

    # --- export subcommand ---
    export_parser = subparsers.add_parser(
        "export",
        help="Export geographic data or simulation results from the project store",
    )
    export_parser.add_argument(
        "project",
        type=str,
        help="Path to the project directory",
    )
    export_parser.add_argument(
        "--list",
        action="store_true",
        help="List available rasters, features, and simulations",
    )
    export_parser.add_argument(
        "--sim",
        default=None,
        help="Simulation name to export (use --list to see available)",
    )
    export_parser.add_argument(
        "--csv",
        action="store_true",
        help="Export timeseries as CSV (default when --sim is used alone)",
    )
    export_parser.add_argument(
        "--netcdf",
        action="store_true",
        help="Export spatial fields as NetCDF",
    )
    export_parser.add_argument(
        "--geotiff",
        action="store_true",
        help="Export spatial fields as GeoTIFF (one per variable)",
    )
    export_parser.add_argument(
        "--vtu",
        action="store_true",
        help="Export mesh + fields as VTU (ParaView)",
    )
    export_parser.add_argument(
        "--raster",
        nargs="+",
        help="Geographic raster name(s) to export as GeoTIFF",
    )
    export_parser.add_argument(
        "--feature",
        nargs="+",
        help="Geographic feature name(s) to export as shapefile",
    )
    export_parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: exports/<name>/ in the project)",
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
        help="Run the fast subset for the selected suite",
    )
    test_parser.add_argument(
        "--slow",
        action="store_true",
        help="Run the slow subset for the selected suite",
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

    handlers = {
        "init": _cmd_init,
        "new": _cmd_new,
        "config": _cmd_config,
        "run": _cmd_run,
        "display": _cmd_display,
        "list": _cmd_list,
        "export": _cmd_export,
        "test": _cmd_test,
    }
    handler = handlers.get(args.command)
    if handler is not None:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
