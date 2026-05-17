"""``hmp privacy`` - privacy-preserving operations on simulations.

Sub-commands:

* ``purge``: hard-delete a simulation (catalog row + Zarr + Parquet + any
  geographic_cache entry no longer referenced) and emit a JSON purge
  certificate under ``<workspace>/.hmp/purge_certificates/<sim_id>.json``.
  The certificate records timestamp UTC, sim_id, sha256 of the simulation
  snapshot before deletion, the reason supplied on the command line, and
  the list of removed paths. The certificate is the only auditable
  evidence that the row ever existed after purge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_OK,
    find_catalog_root,
    resolve_sim_id,
)
from hydromodpy.core.state.paths import CATALOG_FILENAME
from hydromodpy.results.catalog.audit import emit_deletion_tombstone

NAME: str = "privacy"
HELP: str = "Privacy-preserving operations (purge a sim with audit certificate)"

PURGE_CERTIFICATE_DIRNAME = "purge_certificates"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="privacy_command")

    purge = sub.add_parser(
        "purge",
        help="Hard-delete a simulation + emit a JSON purge certificate",
    )
    purge.add_argument(
        "sim_ref",
        help="Full sim_id, unique prefix, or simulation name",
    )
    purge.add_argument(
        "--workspace",
        default=None,
        help="Project root holding catalog.duckdb (default: auto-detect)",
    )
    purge.add_argument(
        "--reason",
        default="unspecified",
        help="Free-form reason recorded in the purge certificate",
    )
    purge.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt",
    )
    purge.add_argument(
        "--archive-pii",
        action="store_true",
        help=(
            "Also write the simulation snapshot (name, project, hashes) to a"
            " sibling 0o600 archive. Off by default to keep certificates PII-free."
        ),
    )

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "privacy_command", None)
    if sub == "purge":
        _cmd_purge(args)
        return
    print("Usage: hmp privacy {purge} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _cmd_purge(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import SimulationCatalog

    workspace_root = find_catalog_root(
        Path(getattr(args, "workspace", None) or Path.cwd()).expanduser().resolve()
    )
    if not (workspace_root / CATALOG_FILENAME).exists():
        print(f"No catalog at {workspace_root}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if not args.yes:
        if not sys.stdin.isatty():
            print(
                "Refusing to purge without -y in non-interactive mode.",
                file=sys.stderr,
            )
            sys.exit(EXIT_CONFIG)
        try:
            resp = input(f"Purge simulation {args.sim_ref!r}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)

    with SimulationCatalog(workspace_root) as catalog:
        sid = resolve_sim_id(catalog, args.sim_ref)
        snapshot = _collect_simulation_snapshot(catalog, sid)
        zarr_path = catalog.zarr_path_for(sid)
        parquet_dir = catalog.parquet_dir_for(sid)
        existing = [str(p) for p in (zarr_path, parquet_dir) if p.exists()]

        sha256_snapshot = _sha256_snapshot(snapshot)
        catalog.delete(
            sid,
            remove_storage=True,
            audit_event_type="sim.purge",
            audit_payload={
                "reason": args.reason,
                "sha256_snapshot": sha256_snapshot,
            },
        )
        emit_deletion_tombstone(
            catalog._db,  # type: ignore[attr-defined]
            sim_id=sid,
            sha256_snapshot=sha256_snapshot,
            reason=args.reason,
            components={"removed_paths": existing},
        )

    workspace_top = _resolve_workspace_top(workspace_root)
    extra_removed = _prune_orphan_geographic_cache(workspace_top)

    cert_path = _write_purge_certificate(
        workspace_root=workspace_top,
        sim_id=sid,
        reason=args.reason,
        sha256_snapshot=sha256_snapshot,
    )
    archive_path: Path | None = None
    if args.archive_pii:
        archive_path = _write_pii_archive(
            workspace_root=workspace_top,
            sim_id=sid,
            snapshot=snapshot,
            reason=args.reason,
            removed_paths=[*existing, *extra_removed],
            sha256_snapshot=sha256_snapshot,
        )

    print(f"Purged simulation {sid}")
    for path in existing:
        print(f"  removed: {path}")
    for path in extra_removed:
        print(f"  removed (orphan cache): {path}")
    print(f"Certificate: {cert_path}")
    if archive_path is not None:
        print(f"PII archive (0o600): {archive_path}")
    sys.exit(EXIT_OK)


def _resolve_workspace_top(project_root: Path) -> Path:
    """Walk up until the parent's name is not ``projects`` (workspace root)."""
    if project_root.parent.name == "projects":
        return project_root.parent.parent
    return project_root


def _collect_simulation_snapshot(catalog, sim_id: str) -> dict[str, object]:
    """Capture a hashable snapshot of the sim row before deletion."""
    row = catalog._db.execute(  # type: ignore[attr-defined]
        """
        SELECT sim_id, name, project, config_hash, config_snapshot,
               geographic_fingerprint, period_start, period_end, created_at
          FROM simulations
         WHERE sim_id = ?
        """,
        [sim_id],
    ).fetchone()
    if row is None:
        return {"sim_id": sim_id}
    cols = (
        "sim_id",
        "name",
        "project",
        "config_hash",
        "config_snapshot",
        "geographic_fingerprint",
        "period_start",
        "period_end",
        "created_at",
    )
    return dict(zip(cols, [_coerce(value) for value in row], strict=False))


def _coerce(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "hex") and not isinstance(value, (bytes, bytearray)):
        return str(value)
    return value


def _prune_orphan_geographic_cache(workspace: Path) -> list[str]:
    """Remove geographic_cache entries no longer referenced by any simulation."""
    cache_dir = workspace / "geographic"
    if not cache_dir.is_dir():
        return []

    referenced = _referenced_fingerprints(workspace)
    removed: list[str] = []
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in referenced:
            continue
        try:
            shutil.rmtree(entry)
            removed.append(str(entry))
        except OSError:
            continue
    return removed


def _referenced_fingerprints(workspace: Path) -> set[str]:
    import duckdb

    seen: set[str] = set()
    candidates: list[Path] = []
    if (workspace / CATALOG_FILENAME).is_file():
        candidates.append(workspace / CATALOG_FILENAME)
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        for entry in projects_dir.iterdir():
            if entry.is_dir():
                cat = entry / CATALOG_FILENAME
                if cat.is_file():
                    candidates.append(cat)

    for catalog_path in candidates:
        try:
            conn = duckdb.connect(str(catalog_path), read_only=True)
        except duckdb.Error:
            continue
        try:
            rows = conn.execute(
                "SELECT DISTINCT geographic_fingerprint FROM simulations "
                "WHERE geographic_fingerprint IS NOT NULL"
            ).fetchall()
        except duckdb.Error:
            rows = []
        finally:
            conn.close()
        seen.update(str(r[0]) for r in rows)
    return seen


def _sha256_snapshot(snapshot: dict[str, object]) -> str:
    """Return the deterministic SHA-256 digest of a simulation snapshot."""
    payload = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_operator() -> str:
    """Return the OS user that performed the purge."""
    import os

    for key in ("HMP_USER", "USER", "USERNAME"):
        value = os.environ.get(key)
        if value:
            return value
    try:
        import getpass

        return getpass.getuser()
    except OSError:
        return "anonymous"


def _write_purge_certificate(
    *,
    workspace_root: Path,
    sim_id: str,
    reason: str,
    sha256_snapshot: str,
) -> Path:
    """Write a PII-free GDPR purge certificate (mode 0o600).

    The certificate only carries the SHA-256 of the snapshot, the
    operator id, a timestamp and a free-form reason. Full snapshot
    details land in the optional sibling archive when ``--archive-pii``
    is set.
    """
    import os

    cert_dir = workspace_root / ".hmp" / PURGE_CERTIFICATE_DIRNAME
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / f"{sim_id}.json"

    certificate = {
        "sim_id": sim_id,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "operator": _resolve_operator(),
        "reason": reason,
        "sha256_snapshot": sha256_snapshot,
    }
    cert_path.write_text(
        json.dumps(certificate, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    try:
        os.chmod(cert_path, 0o600)
    except OSError:
        # POSIX-only; Windows ignores chmod silently.
        pass
    return cert_path


def _write_pii_archive(
    *,
    workspace_root: Path,
    sim_id: str,
    snapshot: dict[str, object],
    reason: str,
    removed_paths: list[str],
    sha256_snapshot: str,
) -> Path:
    """Write the opt-in PII-bearing archive (mode 0o600) next to the cert."""
    import os

    cert_dir = workspace_root / ".hmp" / PURGE_CERTIFICATE_DIRNAME
    cert_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cert_dir / f"{sim_id}.pii.json"

    archive = {
        "sim_id": sim_id,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "operator": _resolve_operator(),
        "reason": reason,
        "sha256_snapshot": sha256_snapshot,
        "removed_paths": removed_paths,
        "snapshot": snapshot,
    }
    archive_path.write_text(
        json.dumps(archive, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    try:
        os.chmod(archive_path, 0o600)
    except OSError:
        pass
    return archive_path


__all__ = ("NAME", "HELP", "register", "run")
