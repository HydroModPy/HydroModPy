"""Private worker helpers for ``hmp privacy`` actions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def purge_simulation(
    sim_ref: str,
    *,
    workspace: Any = None,
    reason: str = "unspecified",
    archive_pii: bool = False,
) -> dict:
    """Hard-delete a simulation and emit a JSON purge certificate.

    Returns a dict with ``sim_id``, ``removed_paths``, ``certificate``,
    ``archive``, ``sha256_snapshot``.
    """
    import hashlib
    import json

    from hydromodpy.core.state.paths import catalog_path_for, resolve_project_root
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.audit import emit_deletion_tombstone

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    if not (catalog_path_for(workspace_root)).exists():
        raise FileNotFoundError(f"No catalog at {workspace_root}")

    with Catalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        snapshot = _purge_collect_snapshot(catalog, sid)
        run_dir = catalog.run_dir_for(sid)
        existing = [str(run_dir)] if run_dir.is_dir() else []
        sha256_snapshot = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        catalog.delete(
            sid,
            remove_storage=True,
            audit_event_type="sim.purge",
            audit_payload={"reason": reason, "sha256_snapshot": sha256_snapshot},
        )
        emit_deletion_tombstone(
            catalog._db,  # type: ignore[attr-defined]
            sim_id=sid,
            sha256_snapshot=sha256_snapshot,
            reason=reason,
            components={"removed_paths": existing},
        )

    workspace_top = _purge_resolve_workspace_top(workspace_root)
    extra_removed = _purge_prune_orphan_geographic_cache(workspace_top)
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
            removed_paths=[*existing, *extra_removed],
            sha256_snapshot=sha256_snapshot,
        )

    return {
        "sim_id": sid,
        "removed_paths": existing + extra_removed,
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


def _purge_collect_snapshot(catalog: Any, sim_id: str) -> dict[str, object]:
    from datetime import datetime

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

    def _coerce(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "hex") and not isinstance(value, (bytes, bytearray)):
            return str(value)
        return value

    return dict(zip(cols, [_coerce(value) for value in row], strict=False))


def _purge_prune_orphan_geographic_cache(workspace: Path) -> list[str]:
    from hydromodpy.cli._workers.catalog import (
        _gc_iter_project_roots,
        _gc_referenced_geographic_fingerprints,
    )
    from hydromodpy.results.geographic_cache import CACHE_DIRNAME

    cache_dir = workspace / CACHE_DIRNAME
    if not cache_dir.is_dir():
        return []
    referenced = _gc_referenced_geographic_fingerprints(_gc_iter_project_roots(workspace))
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


def _purge_resolve_operator() -> str:
    """Resolve the purge operator through the active ``AuthBackend``.

    Delegates to :func:`hydromodpy.core.auth.get_auth_backend` so the purge
    certificate, the deletion tombstone, and the audit row all carry the
    same identity. Falls back to ``"anonymous"`` if the backend itself
    fails (matches the historical CLI contract).
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
