"""Wire-level tests for ``audit_log`` and ``deletions`` table feeding.

These tests guard the contract that:

* ``catalog.delete()`` emits one ``audit_log`` row tagged ``sim.delete``
  in the same transaction as the row removal and does **not** create a
  ``deletions`` tombstone.
* ``hmp privacy purge`` emits one ``audit_log`` row tagged ``sim.purge``
  and one ``deletions`` tombstone with a stable ``sha256_snapshot``.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from hydromodpy.cli.commands import privacy as privacy_cmd
from hydromodpy.results.catalog.facade import SimulationCatalog


@pytest.fixture
def catalog(tmp_path: Path) -> SimulationCatalog:
    cat = SimulationCatalog(tmp_path)
    try:
        yield cat
    finally:
        cat.close()


def _register(catalog: SimulationCatalog, project: str = "lab") -> str:
    sid = str(uuid.uuid4())
    catalog.register_simulation(
        sid,
        project,
        "modflow6",
        name=f"sim-{sid[:8]}",
        n_cells=4,
        n_layers=1,
    )
    return sid


# ---------------------------------------------------------------------------
# catalog.delete()
# ---------------------------------------------------------------------------


def test_delete_simulation_inserts_audit_log_entry(catalog: SimulationCatalog) -> None:
    sid = _register(catalog)
    catalog.delete(sid)

    rows = catalog.connection.execute(
        "SELECT event_type, sim_id, project, payload, actor FROM audit_log WHERE sim_id = ?",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    event_type, log_sid, project, payload, actor = rows[0]
    assert event_type == "sim.delete"
    assert str(log_sid) == sid
    assert project == "lab"
    assert actor and isinstance(actor, str)
    body = json.loads(payload)
    assert body["remove_storage"] is True


def test_delete_simulation_does_not_insert_deletion_tombstone(
    catalog: SimulationCatalog,
) -> None:
    sid = _register(catalog)
    catalog.delete(sid)

    count = catalog.connection.execute(
        "SELECT COUNT(*) FROM deletions WHERE sim_id = ?", [sid]
    ).fetchone()[0]
    assert count == 0


def test_delete_audit_log_records_remove_storage_false(catalog: SimulationCatalog) -> None:
    sid = _register(catalog)
    catalog.delete(sid, remove_storage=False)
    payload = catalog.connection.execute(
        "SELECT payload FROM audit_log WHERE sim_id = ?", [sid]
    ).fetchone()[0]
    body = json.loads(payload)
    assert body["remove_storage"] is False


def test_delete_audit_log_has_hostname_and_actor(catalog: SimulationCatalog) -> None:
    sid = _register(catalog)
    catalog.delete(sid)
    row = catalog.connection.execute(
        "SELECT actor, hostname, actor_kind FROM audit_log WHERE sim_id = ?",
        [sid],
    ).fetchone()
    actor, hostname, actor_kind = row
    assert actor
    assert hostname is not None
    assert actor_kind == "os_user"


# ---------------------------------------------------------------------------
# hmp privacy purge
# ---------------------------------------------------------------------------


def _run_privacy_purge(tmp_path: Path, sid: str, reason: str = "gdpr-request") -> None:
    """Invoke the privacy purge CLI handler on the given workspace and sim."""
    args = type(
        "A",
        (),
        {
            "sim_ref": sid,
            "workspace": str(tmp_path),
            "reason": reason,
            "yes": True,
        },
    )()
    with patch.object(privacy_cmd.sys, "exit") as fake_exit:
        privacy_cmd._cmd_purge(args)
    fake_exit.assert_called_with(privacy_cmd.EXIT_OK)


def test_privacy_purge_inserts_deletion_tombstone_with_sha256(tmp_path: Path) -> None:
    catalog = SimulationCatalog(tmp_path)
    try:
        sid = _register(catalog)
    finally:
        catalog.close()

    _run_privacy_purge(tmp_path, sid)

    catalog = SimulationCatalog(tmp_path)
    try:
        rows = catalog.connection.execute(
            "SELECT sim_id, sha256_snapshot, reason FROM deletions WHERE sim_id = ?",
            [sid],
        ).fetchall()
    finally:
        catalog.close()
    assert len(rows) == 1
    db_sid, sha256_snapshot, reason = rows[0]
    assert str(db_sid) == sid
    assert isinstance(sha256_snapshot, str)
    assert len(sha256_snapshot) == 64
    assert reason == "gdpr-request"


def test_privacy_purge_inserts_audit_log_entry_with_event_type_purge(tmp_path: Path) -> None:
    catalog = SimulationCatalog(tmp_path)
    try:
        sid = _register(catalog)
    finally:
        catalog.close()

    _run_privacy_purge(tmp_path, sid, reason="legal-hold")

    catalog = SimulationCatalog(tmp_path)
    try:
        rows = catalog.connection.execute(
            "SELECT event_type, payload FROM audit_log WHERE sim_id = ?",
            [sid],
        ).fetchall()
    finally:
        catalog.close()
    event_types = [r[0] for r in rows]
    assert "sim.purge" in event_types
    assert "sim.delete" not in event_types
    payload_idx = event_types.index("sim.purge")
    body = json.loads(rows[payload_idx][1])
    assert body.get("reason") == "legal-hold"
    assert "sha256_snapshot" in body


def test_privacy_purge_writes_certificate(tmp_path: Path) -> None:
    catalog = SimulationCatalog(tmp_path)
    try:
        sid = _register(catalog)
    finally:
        catalog.close()

    _run_privacy_purge(tmp_path, sid)

    cert_path = tmp_path / ".hmp" / "purge_certificates" / f"{sid}.json"
    assert cert_path.is_file()
    cert = json.loads(cert_path.read_text(encoding="utf-8"))
    assert cert["sim_id"] == sid
    assert len(cert["sha256_snapshot"]) == 64


def test_privacy_purge_sha256_matches_tombstone_and_certificate(tmp_path: Path) -> None:
    """The same sha256_snapshot lands in deletions, audit_log payload, and cert."""
    catalog = SimulationCatalog(tmp_path)
    try:
        sid = _register(catalog)
    finally:
        catalog.close()

    _run_privacy_purge(tmp_path, sid)

    cert = json.loads(
        (tmp_path / ".hmp" / "purge_certificates" / f"{sid}.json").read_text(encoding="utf-8")
    )
    cat = SimulationCatalog(tmp_path)
    try:
        tomb_sha = cat.connection.execute(
            "SELECT sha256_snapshot FROM deletions WHERE sim_id = ?", [sid]
        ).fetchone()[0]
        audit_payload = cat.connection.execute(
            "SELECT payload FROM audit_log WHERE sim_id = ? AND event_type = 'sim.purge'",
            [sid],
        ).fetchone()[0]
    finally:
        cat.close()
    audit_sha = json.loads(audit_payload)["sha256_snapshot"]
    assert cert["sha256_snapshot"] == tomb_sha == audit_sha
