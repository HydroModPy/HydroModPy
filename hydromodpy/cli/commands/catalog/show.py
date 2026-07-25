"""``hmp catalog show`` - inspect a simulation.

Thin wrapper around :func:`hydromodpy.show_simulation`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy.cli._conventions import add_sim_ref, format_parser, workspace_parser
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

NAME: str = "show"
HELP: str = "Show simulation metadata, metrics, parameters, and storage layout"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser()],
        epilog="Example:\n  hmp catalog show ab12cd34 --detail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Include Zarr store layout (groups, paths) alongside metadata",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import show_simulation
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        Catalog,
        SimulationNotFoundError,
    )

    workspace_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (catalog_path_for(workspace_root)).exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        payload = show_simulation(args.sim_ref, workspace=workspace_root, detail=args.detail)
    except (AmbiguousReferenceError, SimulationNotFoundError, FileNotFoundError) as exc:
        # Route through exit_code_for so an ambiguous ref exits 20 like the
        # mutating verbs (tag/delete/...), not 10 as if it were simply absent.
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
        return

    name = payload.get("name") or payload["sim_id"][:8]
    print(f"Simulation {name}")
    print(f"  sim_id    : {payload['sim_id']}")
    print(f"  project   : {payload['project']}")
    print(f"  solver    : {payload['solver']}")
    print(f"  status    : {payload['status']}")
    if payload.get("duration_s") is not None:
        print(f"  duration  : {payload['duration_s']:.1f} s")
    if payload.get("n_cells") is not None:
        print(f"  n_cells   : {payload['n_cells']}")
    if payload.get("n_timesteps") is not None:
        print(f"  n_timesteps: {payload['n_timesteps']}")
    if args.detail:
        zarr_path = payload.get("zarr_path", "")
        zarr_ok = "OK" if payload.get("zarr_exists") else "MISSING"
        print(f"  zarr       : {zarr_path} ({zarr_ok})")
        groups = payload.get("zarr_groups", [])
        if groups:
            print("  groups     :")
            for group in groups:
                print(f"    - {group}")

    exports = payload.get("exports") or []
    if exports:
        print(f"Exports ({len(exports)}):")
        for art in exports:
            size = art.get("bytes")
            size_str = f" ({size} B)" if size is not None else ""
            print(f"  - {art['kind']}: {art['rel_path']}{size_str}")

    # Tags, notes, metrics and parameters require a direct catalog read.
    with Catalog(workspace_root, read_only=True) as catalog:
        sim = catalog[payload["sim_id"]]
        ident = catalog.backend.fetch_one(
            "SELECT version_int, config_hash FROM simulations WHERE sim_id = ?",
            [payload["sim_id"]],
        )
        if ident is not None:
            if ident[0] is not None:
                print(f"  version   : v{ident[0]}")
            if ident[1]:
                print(f"  config    : {ident[1][:12]}")
        tags = sim.tags or []
        if tags:
            print(f"  tags      : {', '.join(tags)}")
        note_rows = catalog.backend.fetch_all(
            "SELECT note FROM sim_notes WHERE sim_id = ? ORDER BY added_at",
            [payload["sim_id"]],
        )
        if note_rows:
            print("Notes:")
            for (note,) in note_rows:
                print(f"  - {note}")
        metrics = sim.metrics
        if not metrics.empty:
            print("Metrics:")
            print(metrics.to_string(index=False))
        params = sim.parameters
        if not params.empty:
            print("Parameters:")
            # parameters is indexed by param_name; keep the index so the
            # parameter names are not dropped (audit P14).
            print(params.to_string())

    ref = payload.get("name") or payload["sim_id"][:8]
    print(
        f"next: hmp catalog tag {ref} +pinned | "
        f"hmp catalog diff {ref} <other> | hmp catalog rename {ref} <new>"
    )
