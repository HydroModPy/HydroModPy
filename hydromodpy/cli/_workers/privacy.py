"""Private worker helpers for ``hmp privacy`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def purge_simulation(
    sim_ref: str,
    *,
    workspace: Any = None,
    reason: str = "unspecified",
    archive_pii: bool = False,
) -> dict:
    """Remove a run directory for good and write a JSON purge certificate.

    The directory goes through the trash and is removed at once: its name
    stays taken by a tombstone in ``trash/tombstones.txt``. The index, when
    the project has one, is brought up to date afterwards.

    Returns a dict with ``sim_id``, ``rel_dir``, ``removed_paths``,
    ``certificate``, ``archive``, ``sha256_snapshot``.
    """
    import hashlib
    import json
    from datetime import UTC, datetime

    from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.trash import identity_of, list_trash, purge_trashed, trash_run

    project_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    rel_dir = resolve_rel_dir(project_root, sim_ref, unambiguous=True)
    run_dir = project_root / rel_dir
    snapshot = _purge_collect_snapshot(run_dir, rel_dir)
    sid = identity_of(run_dir) or rel_dir
    sha256_snapshot = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    now = datetime.now(UTC)
    trashed = trash_run(project_root, rel_dir, now=now)
    entry = next(entry for entry in list_trash(project_root) if entry.path == trashed)
    purge_trashed(project_root, [entry], now=now)
    if catalog_path_for(project_root).is_file():
        from hydromodpy.results.catalog.indexer import index_new_runs

        index_new_runs(project_root)

    removed = [str(run_dir)]
    workspace_top = _purge_resolve_workspace_top(project_root)
    cert_path = _purge_write_certificate(
        workspace_top, sim_id=sid, reason=reason, sha256_snapshot=sha256_snapshot
    )
    archive_path: Path | None = None
    if archive_pii:
        archive_path = _purge_write_pii_archive(
            workspace_top,
            sim_id=sid,
            snapshot=snapshot,
            reason=reason,
            removed_paths=removed,
            sha256_snapshot=sha256_snapshot,
        )

    return {
        "sim_id": sid,
        "rel_dir": rel_dir,
        "removed_paths": removed,
        "certificate": str(cert_path),
        "archive": str(archive_path) if archive_path else None,
        "sha256_snapshot": sha256_snapshot,
    }


def verify_purge_certificate(certificate: Any, *, strict: bool = False) -> dict:
    """Verify a purge certificate JSON file. Returns the parsed payload + status."""
    import json

    cert_path = Path(certificate).expanduser().resolve()
    if not cert_path.is_file():
        raise FileNotFoundError(f"Certificate not found: {cert_path}")
    try:
        payload = json.loads(cert_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Certificate is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Certificate must be a JSON object")
    required = ("sim_id", "timestamp_utc", "operator", "reason", "sha256_snapshot")
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"Certificate missing required fields: {', '.join(missing)}")
    digest = str(payload.get("sha256_snapshot", ""))
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        raise ValueError(f"sha256_snapshot has invalid form: {digest!r}")
    try:
        stat = cert_path.stat()
        mode = stat.st_mode & 0o777
    except OSError:
        mode = None
    permissions_ok = mode == 0o600 if mode is not None else True
    if not permissions_ok and strict:
        raise ValueError(f"certificate permissions {oct(mode)} != 0o600")
    return {
        "certificate": str(cert_path),
        "permissions_ok": permissions_ok,
        "permissions": oct(mode) if mode is not None else None,
        "payload": payload,
    }


def _purge_resolve_workspace_top(project_root: Path) -> Path:
    if project_root.parent.name == "projects":
        return project_root.parent.parent
    return project_root


def _purge_collect_snapshot(run_dir: Path, rel_dir: str) -> dict[str, object]:
    """Return what the directory declares about itself, read from its manifest."""
    from hydromodpy.results.manifest import is_sealed, read_manifest

    if not is_sealed(run_dir):
        return {"rel_dir": rel_dir}
    manifest = read_manifest(run_dir)
    run = manifest.get("run", {})
    snapshot: dict[str, object] = {
        "rel_dir": rel_dir,
        "sim_id": run.get("sim_id"),
        "name": run.get("name"),
        "project": run.get("project"),
        "created_at": run.get("created_at"),
        "config_hash": manifest.get("config", {}).get("hash"),
        "site": manifest.get("site"),
        "period": manifest.get("period"),
    }
    return snapshot


def _purge_resolve_operator() -> str:
    """Resolve the purge operator through the active ``AuthBackend``.

    Delegates to :func:`hydromodpy.core.auth.get_auth_backend`. Falls back
    to ``"anonymous"`` if the backend itself fails: a purge must not stop on
    an identity probe.
    """
    try:
        from hydromodpy.core.auth import get_auth_backend

        return get_auth_backend().current_user() or "anonymous"
    except Exception:  # noqa: BLE001 - purge must not crash on identity probe
        return "anonymous"


def _purge_write_certificate(
    workspace_root: Path, *, sim_id: str, reason: str, sha256_snapshot: str
) -> Path:
    import json
    import os
    from datetime import UTC, datetime

    cert_dir = workspace_root / ".hmp" / "purge_certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / f"{sim_id}.json"
    certificate = {
        "sim_id": sim_id,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "operator": _purge_resolve_operator(),
        "reason": reason,
        "sha256_snapshot": sha256_snapshot,
    }
    cert_path.write_text(
        json.dumps(certificate, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    try:
        os.chmod(cert_path, 0o600)
    except OSError:
        pass
    return cert_path


def _purge_write_pii_archive(
    workspace_root: Path,
    *,
    sim_id: str,
    snapshot: dict[str, object],
    reason: str,
    removed_paths: list[str],
    sha256_snapshot: str,
) -> Path:
    import json
    import os
    from datetime import UTC, datetime

    cert_dir = workspace_root / ".hmp" / "purge_certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cert_dir / f"{sim_id}.pii.json"
    archive = {
        "sim_id": sim_id,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "operator": _purge_resolve_operator(),
        "reason": reason,
        "sha256_snapshot": sha256_snapshot,
        "removed_paths": removed_paths,
        "snapshot": snapshot,
    }
    archive_path.write_text(
        json.dumps(archive, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    try:
        os.chmod(archive_path, 0o600)
    except OSError:
        pass
    return archive_path
