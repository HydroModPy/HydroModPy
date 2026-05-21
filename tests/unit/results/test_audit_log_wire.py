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
        "SELECT event_type, sim_id, project, payload, actor FROM audit_log "
        "WHERE sim_id = ? AND event_type = 'sim.delete'",
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
        "SELECT payload FROM audit_log WHERE sim_id = ? AND event_type = 'sim.delete'",
        [sid],
    ).fetchone()[0]
    body = json.loads(payload)
    assert body["remove_storage"] is False


def test_delete_audit_log_has_hostname_and_actor(catalog: SimulationCatalog) -> None:
    sid = _register(catalog)
    catalog.delete(sid)
    row = catalog.connection.execute(
        "SELECT actor, hostname, actor_kind FROM audit_log "
        "WHERE sim_id = ? AND event_type = 'sim.delete'",
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
            "archive_pii": False,
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


# ---------------------------------------------------------------------------
# T6.B - rename / tag_remove / param.update / tracked_file.remove
# ---------------------------------------------------------------------------


def test_rename_simulation_emits_sim_rename(catalog: SimulationCatalog) -> None:
    sid = _register(catalog)
    catalog.rename_simulation(sid, "renamed")
    rows = catalog.connection.execute(
        "SELECT event_type, sim_id, payload FROM audit_log "
        "WHERE sim_id = ? AND event_type = 'sim.rename'",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][2]) == {"new_name": "renamed"}
    name_row = catalog.connection.execute(
        "SELECT name FROM simulations WHERE sim_id = ?", [sid]
    ).fetchone()
    assert name_row[0] == "renamed"


def test_remove_tag_emits_sim_tag_remove(catalog: SimulationCatalog) -> None:
    sid = str(uuid.uuid4())
    catalog.register_simulation(
        sid,
        "lab",
        "modflow6",
        name=f"sim-{sid[:8]}",
        n_cells=4,
        n_layers=1,
        tags=["alpha", "beta"],
    )
    removed = catalog.remove_tag(sid, "alpha")
    assert removed is True
    rows = catalog.connection.execute(
        "SELECT payload FROM audit_log WHERE sim_id = ? AND event_type = 'sim.tag_remove'",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0]) == {"tag": "alpha"}
    remaining = catalog.connection.execute(
        "SELECT tag FROM tags WHERE sim_id = ? ORDER BY tag", [sid]
    ).fetchall()
    assert [r[0] for r in remaining] == ["beta"]


def test_update_parameter_emits_param_update(catalog: SimulationCatalog) -> None:
    sid = _register(catalog)
    catalog.write_parameters(
        sid,
        [{"param_name": "K", "value": 1e-4, "unit": "m/s"}],
    )
    catalog.update_parameter(sid, "K", 2e-4, unit="m/s")
    rows = catalog.connection.execute(
        "SELECT payload FROM audit_log WHERE sim_id = ? AND event_type = 'param.update'",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    body = json.loads(rows[0][0])
    assert body["param_name"] == "K"
    assert float(body["value"]) == pytest.approx(2e-4)
    new_value = catalog.connection.execute(
        "SELECT value FROM parameters WHERE sim_id = ? AND param_name = 'K'",
        [sid],
    ).fetchone()[0]
    assert float(new_value) == pytest.approx(2e-4)


def test_remove_tracked_file_emits_tracked_file_remove(catalog: SimulationCatalog) -> None:
    sid = _register(catalog)
    # Seed one row directly so we do not depend on the full tracked_file
    # registration pipeline (filesystem walker, SHA-256, ...).
    catalog.connection.execute(
        """INSERT INTO tracked_files
           (sim_id, role, category, original_path, canonical_path,
            sha256, size_bytes, portable)
           VALUES (?, 'input.dem', 'topography', 'dem.tif', 'dem.tif',
                   'deadbeef', 1024, TRUE)""",
        [sid],
    )
    removed = catalog.remove_tracked_file(sid, "input.dem", "dem.tif")
    assert removed is True
    rows = catalog.connection.execute(
        "SELECT payload FROM audit_log WHERE sim_id = ? AND event_type = 'tracked_file.remove'",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    body = json.loads(rows[0][0])
    assert body["role"] == "input.dem"
    assert body["canonical_path"] == "dem.tif"
    remaining = catalog.connection.execute(
        "SELECT COUNT(*) FROM tracked_files WHERE sim_id = ?", [sid]
    ).fetchone()[0]
    assert remaining == 0
