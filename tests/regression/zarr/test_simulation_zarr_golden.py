"""Content-level golden snapshot for :class:`SimulationZarr`.

The snapshot hashes the sorted ``(relative_path, bytes)`` of every file of
the ``fields.zarr`` directory store after stripping volatile JSON keys
(``history``, ``created_at``, ``date_modified``). This way the SHA-256 is
independent of the local clock and of filesystem metadata but still pins:

* the on-disk hierarchy (mesh, time, head field, ACDD root attrs),
* the array bytes for mesh / time / head,
* the static ACDD attributes derived from inputs.

The constant ``EXPECTED_DIGEST`` was re-captured when the store stopped
being packed to a zip: the snapshot now covers ``fields.zarr`` as it lives
on disk, which is exactly what a reader opens. Any drift of the hierarchy,
of the chunk layout or of the static attributes has to be intentional.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store import SimulationZarr

_FROZEN_NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)

# Volatile attribute keys to strip from root / meta ``zarr.json`` payloads
# before computing the snapshot SHA-256.
_VOLATILE_KEYS = frozenset({"history", "created_at", "date_modified"})

EXPECTED_DIGEST = "698fdddbb832b2d5a03a2ed321e2aeff53b0e2e7b226b0da442cf4a780afd9bc"


class _FrozenDatetime(datetime):
    """``datetime`` subclass returning ``_FROZEN_NOW`` from ``now``."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return _FROZEN_NOW if tz is None else _FROZEN_NOW.astimezone(tz)


@pytest.fixture
def freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``datetime.now`` everywhere SimulationZarr writes a timestamp."""
    import hydromodpy.results.zarr_store.acdd as acdd_mod
    import hydromodpy.results.zarr_store.zarr_schema as schema_mod

    monkeypatch.setattr(schema_mod, "datetime", _FrozenDatetime)
    monkeypatch.setattr(acdd_mod, "datetime", _FrozenDatetime)


def _strip_volatile(payload: bytes) -> bytes:
    """Return the JSON bytes with volatile keys removed when ``payload`` is JSON."""
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload

    def _scrub(node):
        if isinstance(node, dict):
            return {k: _scrub(v) for k, v in node.items() if k not in _VOLATILE_KEYS}
        if isinstance(node, list):
            return [_scrub(item) for item in node]
        return node

    return json.dumps(_scrub(obj), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _content_digest(store_path: Path) -> str:
    """SHA-256 over sorted ``(relative_path, scrubbed_bytes)`` pairs of the store."""
    hasher = hashlib.sha256()
    members = sorted(
        (path.relative_to(store_path).as_posix(), path)
        for path in store_path.rglob("*")
        if path.is_file()
    )
    for name, path in members:
        scrubbed = _strip_volatile(path.read_bytes())
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(scrubbed)
        hasher.update(b"\xff")
    return hasher.hexdigest()


def _build_synthetic_store(path: Path) -> Path:
    """Create a tiny store (10 cells x 2 layers) and return its directory."""
    sz = SimulationZarr.create(
        path,
        n_cells=10,
        n_layers=2,
        cell_types=["square"] * 10,
        geographic_fingerprint="abcdef0123456789",
    )

    n_nodes = 22
    vertices = np.arange(n_nodes * 3, dtype="float64").reshape(n_nodes, 3)
    face_node_connectivity = np.arange(10 * 4, dtype="int32").reshape(10, 4)
    z_interfaces = np.array([0.0, -1.0, -2.0], dtype="float64")
    topography = np.linspace(100.0, 110.0, 10, dtype="float64")

    sz.write_mesh(
        vertices=vertices,
        face_node_connectivity=face_node_connectivity,
        z_interfaces=z_interfaces,
        topography=topography,
        start_index=0,
        grid_type="structured",
        structured_shape=(2, 5),
    )

    sz.write_time(
        values=np.array([0, 86400, 172800], dtype="int64"),
        epoch="1970-01-01T00:00:00",
        calendar="proleptic_gregorian",
        units="seconds since 1970-01-01T00:00:00",
    )

    head = np.full((2, 10), 5.5, dtype="float64")
    head[0, 0] = 1.0
    head[1, -1] = 9.0
    sz.write_field("head", timestep=0, values=head, n_timesteps=3)
    sz.write_field("head", timestep=1, values=head + 0.25, n_timesteps=3)
    sz.write_field("head", timestep=2, values=head + 0.50, n_timesteps=3)

    sz.write_acdd_root_attrs(
        sim_row={
            "sim_id": "11111111-1111-7111-8111-111111111111",
            "name": "golden",
            "description": "golden snapshot",
            "project": "demo",
            "solver": "modflow6",
            "period_start": "2020-01-01",
            "period_end": "2020-01-04",
            "time_unit": "day",
            "contact_email": "user@example.org",
            "creator_institution": "Example Lab",
            "creator_url": "https://example.org",
            "license": "CC-BY-4.0",
        },
        runs_env={
            "user_name": "user",
            "hydromodpy_version": "test-version",
            "git_commit": "deadbeef",
            "rng_seed": 42,
        },
        geographic_bounds={
            "lat_min": 47.0,
            "lat_max": 48.0,
            "lon_min": -3.0,
            "lon_max": -2.0,
            "vertical_min": 0.0,
            "vertical_max": 110.0,
        },
    )

    sz.consolidate_metadata()
    sz.close()
    return path


def test_simulation_zarr_store_is_byte_stable(
    tmp_path: Path,
    freeze_clock: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The directory-store content must match the golden SHA-256."""
    # Pin the hydromodpy version label that bleeds into root attrs so the
    # digest is independent of the installed package version.
    monkeypatch.setattr(
        "hydromodpy.results.zarr_store.zarr_schema._HMP_VERSION",
        "test-version",
    )
    monkeypatch.setattr(
        "hydromodpy.results.zarr_store.acdd._HMP_VERSION",
        "test-version",
    )

    store_path = _build_synthetic_store(tmp_path / FIELDS_STORE_NAME)
    digest = _content_digest(store_path)

    assert digest == EXPECTED_DIGEST, (
        "SimulationZarr store content drifted from the golden snapshot.\n"
        f"  expected: {EXPECTED_DIGEST}\n"
        f"  actual:   {digest}\n"
        "If the change is intentional, recompute the snapshot."
    )
