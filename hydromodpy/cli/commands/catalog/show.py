"""``hmp catalog show`` - the facts of one sealed run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy.cli._conventions import (
    add_sim_ref,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, apply_verbosity, exit_code_for
from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root

NAME: str = "show"
HELP: str = "Show the facts, label, metrics and parameters of a sealed run"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), verbosity_parser()],
        epilog="Example:\n  hmp catalog show baseline_monthly.v2 --detail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_sim_ref(parser)
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Include the Zarr store layout (groups, paths) alongside the facts",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    apply_verbosity(args, {})
    from hydromodpy.cli._workers.catalog import show_simulation
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        Catalog,
        SimulationNotFoundError,
    )

    project_root = resolve_project_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not catalog_path_for(project_root).is_file():
        print(f"No index at {project_root}; run `hmp catalog reindex` first", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    try:
        payload = show_simulation(args.sim_ref, workspace=project_root, detail=args.detail)
    except (AmbiguousReferenceError, SimulationNotFoundError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
        return

    name = payload.get("name") or payload["sim_id"][:8]
    print(f"Run {name}")
    print(f"  sim_id    : {payload['sim_id']}")
    print(f"  rel_dir   : {payload['rel_dir']}")
    print(f"  project   : {payload['project']}")
    if payload.get("site"):
        print(f"  site      : {payload['site']}")
    print(f"  case      : {payload['case_id']}")
    print(f"  solver    : {payload['solver']}")
    print(f"  status    : {payload['status']}")
    print(f"  label     : {payload['label']} ({payload['label_date']})")
    if payload.get("nse") is not None:
        print(f"  nse       : {payload['nse']:.3f}")
    if payload.get("version_int") is not None:
        print(f"  version   : v{payload['version_int']}")
    if payload.get("config_hash"):
        print(f"  config    : {payload['config_hash'][:12]}")
    if payload.get("duration_s") is not None:
        print(f"  duration  : {payload['duration_s']:.1f} s")
    if payload.get("n_cells") is not None:
        print(f"  n_cells   : {payload['n_cells']}")
    if payload.get("n_timesteps") is not None:
        print(f"  n_timesteps: {payload['n_timesteps']}")
    if args.detail:
        zarr_ok = "OK" if payload.get("zarr_exists") else "MISSING"
        print(f"  zarr       : {payload.get('zarr_path', '')} ({zarr_ok})")
        groups = payload.get("zarr_groups", [])
        if groups:
            print("  groups     :")
            for group in groups:
                print(f"    - {group}")

    for kind in ("exports", "figures"):
        entries = payload.get(kind) or []
        if entries:
            print(f"{kind.capitalize()} ({len(entries)}):")
            for entry in entries:
                print(f"  - {entry['file']}  ({entry['producer']})")

    with Catalog(project_root) as catalog:
        sim = catalog[payload["sim_id"]]
        tags = sim.tags or []
        if tags:
            print(f"  tags      : {', '.join(tags)}")
        notes = catalog.backend.fetch_all(
            "SELECT note FROM sim_notes WHERE sim_id = ? ORDER BY added_at",
            [payload["sim_id"]],
        )
        if notes:
            print("Notes:")
            for (note,) in notes:
                print(f"  - {note}")
        metrics = sim.metrics
        if not metrics.empty:
            print("Metrics:")
            print(metrics.to_string(index=False))
        params = sim.parameters
        if not params.empty:
            print("Parameters:")
            print(params.to_string())

    ref = payload.get("rel_dir") or payload["sim_id"][:8]
    print(f"next: hmp catalog tag {ref} +pinned | hmp catalog diff {ref} <other>")
