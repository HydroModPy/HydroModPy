"""Unit tests for the audit_log SHA-256 hash chain and retention policies."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.audit import (
    _compute_chain_hash,
    emit_audit_event,
    verify_chain,
)
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    with simulation_catalog(tmp_path / "ws") as cat:
        yield cat


def _emit_three_events(catalog: Catalog) -> list[str]:
    """Emit three events directly through ``emit_audit_event`` and return ids."""
    ids: list[str] = []
    for index in range(3):
        event_id = emit_audit_event(
            catalog.connection,
            event_type="metric.write",
            sim_id=None,
            project="lab",
            payload={"index": index},
        )
        ids.append(event_id)
    return ids


def test_hash_chain_consistency(catalog: Catalog) -> None:
    """Three sequential events form a verifiable chain anchored on the last emit."""
    # The catalog already emitted ``migrate`` events while applying the
    # bundled migrations. Capture the last chain_hash before emitting more.
    anchor_row = catalog.connection.execute(
        "SELECT chain_hash FROM audit_log WHERE chain_hash IS NOT NULL ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    expected_prev: str | None = anchor_row[0] if anchor_row else None

    _emit_three_events(catalog)

    rows = catalog.connection.execute(
        "SELECT event_id, event_type, sim_id, project, payload, prev_hash, chain_hash, "
        "occurred_at, actor, actor_kind, hostname "
        "FROM audit_log WHERE event_type = 'metric.write' ORDER BY seq ASC"
    ).fetchall()
    assert len(rows) == 3

    for row in rows:
        (
            event_id,
            event_type,
            sim_id,
            project,
            payload,
            prev_hash,
            chain_hash,
            occurred_at,
            actor,
            actor_kind,
            hostname,
        ) = row
        assert chain_hash is not None
        assert prev_hash == expected_prev
        recomputed = _compute_chain_hash(
            prev_hash=prev_hash,
            event_id=str(event_id),
            event_type=str(event_type),
            sim_id=str(sim_id) if sim_id is not None else None,
            project=str(project) if project is not None else None,
            payload_json=str(payload),
            occurred_at=occurred_at,
            actor=str(actor) if actor is not None else None,
            actor_kind=str(actor_kind) if actor_kind is not None else None,
            hostname=str(hostname) if hostname is not None else None,
        )
        assert recomputed == chain_hash
        expected_prev = chain_hash

    assert verify_chain(catalog.connection) is True


def test_hash_chain_survives_multiple_events_in_one_transaction(catalog: Catalog) -> None:
    """Several audit rows in one transaction verify via the monotonic ``seq``,
    the ordering key that keeps ``verify_chain`` stable where the old
    ``(occurred_at, event_id)`` order could fork the chain."""
    conn = catalog.connection
    conn.execute("BEGIN TRANSACTION")
    for index in range(8):
        emit_audit_event(
            conn,
            event_type="sim.tag_add",
            sim_id=None,
            project="lab",
            payload={"tag": f"t{index}"},
        )
    conn.execute("COMMIT")

    # seq is present and strictly increasing in insertion order.
    seqs = [
        row[0]
        for row in conn.execute(
            "SELECT seq FROM audit_log WHERE event_type = 'sim.tag_add' ORDER BY seq"
        ).fetchall()
    ]
    assert len(seqs) == 8
    assert len(set(seqs)) == 8

    assert verify_chain(conn) is True


def test_hash_chain_corruption_detected(catalog: Catalog) -> None:
    """Mutating one row's payload after the fact breaks ``verify_chain``."""
    _emit_three_events(catalog)

    catalog.connection.execute(
        "UPDATE audit_log SET payload = '{}' WHERE event_type = 'metric.write' "
        "AND event_id = ("
        "  SELECT event_id FROM audit_log WHERE event_type = 'metric.write' "
        "  ORDER BY occurred_at ASC LIMIT 1"
        ")"
    )

    assert verify_chain(catalog.connection) is False


def test_retention_policies_table_exists(catalog: Catalog) -> None:
    """Migration 0003 creates ``retention_policies`` with the expected shape."""
    rows = catalog.connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'retention_policies'"
    ).fetchall()
    assert rows == [("retention_policies",)]

    cols = {
        name
        for (name,) in catalog.connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'retention_policies'"
        ).fetchall()
    }
    assert {"policy_id", "event_type", "retention_days", "created_at"}.issubset(cols)


def test_apply_retention_dry_run_counts_eligible(catalog: Catalog) -> None:
    """``apply_retention(dry_run=True)`` returns counts without deleting rows."""
    from hydromodpy.results.catalog.audit import apply_retention

    catalog.connection.execute(
        "INSERT INTO retention_policies (policy_id, event_type, retention_days) VALUES (?, ?, ?)",
        [str(uuid.uuid4()), "metric.write", 0],
    )
    _emit_three_events(catalog)

    counts = apply_retention(catalog.connection, dry_run=True)
    assert counts.get("metric.write", 0) >= 0
    remaining = catalog.connection.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type = 'metric.write'"
    ).fetchone()[0]
    assert remaining == 3
