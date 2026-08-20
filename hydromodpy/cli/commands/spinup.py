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

from hydromodpy.cli._conventions import profile_parser
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    profile_arg_from_toml,
    profile_run,
    resolve_profile_output,
)

NAME: str = "spinup"
HELP: str = "Cyclic spin-up: restart each cycle until heads and lake stage converge"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[profile_parser()])
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

    target = Path(args.config).expanduser().resolve()
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    if target.suffix != ".toml":
        print(f"Expected a .toml file, got: {target.suffix}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    profile_arg = getattr(args, "profile", None)
    if profile_arg is None:
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config

        try:
            profile_arg = profile_arg_from_toml(load_toml_with_base_config(target))
        except Exception:
            profile_arg = None
    profile_output = resolve_profile_output(profile_arg, target)
    try:
        with profile_run(profile_output, description=f"hmp spinup {target.name}"):
            result = hmp.spinup(target, then_run=args.then_run)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)
    except ValidationError as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    status = "converged" if result.converged else "did NOT converge"
    print(f"Spin-up {status} in {result.n_cycles} cycle(s).", file=sys.stderr)
    for cycle in result.cycles:
        if cycle.d_head is None:
            print(f"  cycle {cycle.index}: initial state", file=sys.stderr)
        else:
            print(
                f"  cycle {cycle.index}: d_head={cycle.d_head:.4g} m, "
                f"d_stage={cycle.d_stage:.4g} m",
                file=sys.stderr,
            )
    if result.restart_from:
        print(f"Converged state: {result.restart_from}", file=sys.stderr)
        if result.production_sim_id:
            print(
                f"Production run from converged state: {result.production_sim_id}", file=sys.stderr
            )
        else:
            print(
                "Set [flow] restart_from to this path in the production run "
                "(enable [mesh_catchment] cache for a gmsh grid so it reproduces this mesh).",
                file=sys.stderr,
            )
