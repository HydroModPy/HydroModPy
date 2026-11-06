"""``hmp catalog show`` - the README of one run, or its facts from the index.

By default the verb prints the ``README.md`` the run carries (site, period,
version, checks, label, score, lineage, where is what), read from its
directory without the index, then its tags and notes. ``--detail`` and
``--format json|csv`` print the facts the index holds instead, and so does a
run without a README.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from hydromodpy.cli.conventions import (
    add_sim_ref,
    format_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_NOT_FOUND,
    exit_code_for,
    project_root_of,
    refuse,
)
from hydromodpy.cli.output import emit
from hydromodpy.core.state.layout import catalog_path_for

NAME: str = "show"
HELP: str = "Print the README of a run, or its facts, metrics and parameters from the index"


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
        help="Print the facts from the index, with the Zarr store layout, not the README",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.catalog import show_simulation

    project_root = project_root_of(args)
    named = bool(args.workspace)
    if (
        args.format == "table"
        and not args.detail
        and _print_readme(project_root, args.sim_ref, named)
    ):
        return
    if not catalog_path_for(project_root).is_file():
        refuse(f"No index at {project_root}; run `hmp catalog reindex` first", EXIT_NOT_FOUND)

    payload = show_simulation(args.sim_ref, workspace=project_root, detail=args.detail)

    emit(args, "catalog show", payload, table=lambda: _print_facts(project_root, payload, args))


def _print_facts(project_root: Path, payload: dict[str, Any], args: argparse.Namespace) -> None:
    """Print what the index holds about one run, for people."""
    from hydromodpy.results.catalog import Catalog

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


def _print_readme(project_root: Path, ref: str, named: bool) -> bool:
    """Print the README of the run ``ref`` names; ``False`` when it carries none.

    ``named`` tells that ``-w`` was given. Without it the folder is the cwd, and a
    refusal says how to name another one.
    """
    from hydromodpy.results.annotations import read_annotations
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.storage.contract import README_FILENAME

    try:
        rel_dir = resolve_rel_dir(project_root, ref)
    except Exception as exc:  # noqa: BLE001 - map resolver errors to typed exit codes
        hint = "" if named else " Name the workspace or the project with -w."
        refuse(f"{exc}{hint}", exit_code_for(exc), cause=exc)
    run_dir = project_root / rel_dir
    readme = run_dir / README_FILENAME
    if not readme.is_file():
        return False
    print(readme.read_text(encoding="utf-8").rstrip())
    annotations = read_annotations(run_dir)
    if annotations.tags:
        print(f"\ntags: {', '.join(annotations.tags)}")
    if annotations.notes:
        print("notes:")
        for note in annotations.notes:
            print(f"  - {note.at:%Y-%m-%d %H:%M} {note.text}")
    print(f"\nnext: hmp catalog show {rel_dir} --detail | hmp catalog diff {rel_dir} <other>")
    return True
