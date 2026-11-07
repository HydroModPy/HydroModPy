"""``hmp spinup`` - run a cyclic spin-up from a TOML file.

Thin wrapper around :func:`hydromodpy.spinup`. Repeats a representative window,
restarting each cycle from the previous state, until the aquifer heads and the
lake stage converge. Prints the converged Zarr path to seed a production run's
``[flow] restart_from``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from hydromodpy.cli.conventions import (
    dry_run_parser,
    format_parser,
    profile_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.effective_toml import profile_output_of, toml_target
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    apply_verbosity,
    profile_run,
    project_named_by_w,
    refuse,
)
from hydromodpy.cli.output import emit

NAME: str = "spinup"
HELP: str = "Cyclic spin-up: restart each cycle until heads and lake stage converge"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[
            workspace_parser(),
            dry_run_parser(),
            format_parser(),
            profile_parser(),
            verbosity_parser(),
        ],
        epilog="Examples:\n  hmp spinup run.toml\n  hmp spinup run.toml --then-run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config", type=Path, help="Path to a simulation TOML file")
    parser.add_argument(
        "--then-run",
        action="store_true",
        help="After convergence, run the full production chronicle from the converged state",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    target = toml_target(args.config)

    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    try:
        raw_toml = load_toml_with_base_config(target)
    except Exception:
        raw_toml = {}
    apply_verbosity(args, raw_toml)

    if args.dry_run:
        _dry_run(args, target)
        return

    profile_output = profile_output_of(args, raw_toml, target)
    try:
        with profile_run(profile_output, description=f"hmp spinup {target.name}"):
            with project_named_by_w(args.workspace):
                result = hmp.spinup(target, then_run=args.then_run)
    except ValidationError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    except FileNotFoundError as exc:
        refuse(f"Missing file: {exc}", EXIT_NOT_FOUND, cause=exc)

    warning = result.antecedent_warning() if result.restart_from else None

    def table() -> None:
        status = "converged" if result.converged else "did NOT converge"
        print(f"Spin-up {status} in {result.n_cycles} cycle(s).", file=sys.stderr)
        for cycle in result.cycles:
            if cycle.d_head is None:
                print(f"  cycle {cycle.index}: initial state", file=sys.stderr)
            else:
                stage = "not compared" if cycle.d_stage is None else f"{cycle.d_stage:.4g} m"
                print(
                    f"  cycle {cycle.index}: d_head={cycle.d_head:.4g} m, d_stage={stage}",
                    file=sys.stderr,
                )
        if not result.restart_from:
            return
        label = "Converged state" if result.converged else "Last state reached"
        print(f"{label}: {result.restart_from}", file=sys.stderr)
        if warning is not None:
            print(f"Warning: {warning}", file=sys.stderr)
        if result.production_sim_id:
            print(
                f"Production run from converged state: {result.production_sim_id}", file=sys.stderr
            )
        else:
            print(
                "Set [flow] restart_from to this path in the production run "
                "(a generated mesh is read back from the project mesh cache).",
                file=sys.stderr,
            )

    emit(
        args,
        "spinup",
        {
            "applied": True,
            "converged": result.converged,
            "n_cycles": result.n_cycles,
            "cycles": [
                {"index": cycle.index, "d_head": cycle.d_head, "d_stage": cycle.d_stage}
                for cycle in result.cycles
            ],
            "restart_from": result.restart_from,
            "warning": warning,
            "production_sim_id": result.production_sim_id,
        },
        table=table,
    )


def _dry_run(args: argparse.Namespace, target: Path) -> None:
    """Check the TOML as the spin-up reads it, say what the loop would do, run nothing."""
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.model.initial.spinup_config import SpinupConfig

    try:
        config = HydroModPyConfig.from_toml(target)
    except ValidationError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    settings = config.spinup or SpinupConfig()
    plan = {
        "applied": False,
        "converged": None,
        "n_cycles": None,
        "cycles": [],
        "restart_from": None,
        "warning": None,
        "production_sim_id": None,
    }

    def table() -> None:
        window = (
            f"{settings.window_start} to {settings.window_end}"
            if settings.window_start and settings.window_end
            else "[simulation.time]"
        )
        print(f"would spin up {target} for at most {settings.max_cycles} cycle(s) over {window}")
        print(f"  tolerances: head {settings.tol_head} m, stage {settings.tol_stage} m")
        if args.then_run:
            print("  then run the production chronicle from the converged state")

    emit(args, "spinup", plan, table=table)
