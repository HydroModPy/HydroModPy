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
of the chunk layout or of the static attributes has to be intentional. It
was re-captured a second time when every array started declaring
``dimension_names`` and float fields stopped carrying a NaN ``_FillValue``
attribute, and a third time when the root attributes stopped asserting a
creator nobody declared and a CDM feature type the mesh is not: same members,
same chunk bytes, different node metadata. It was re-captured a fourth time
when fields became compact by default: the head array is float32 rounded to
16 mantissa bits, carries the CF ``quantization`` attributes, and the store
gains the ``quantization_info`` container. The head values of this store are
exact in float32, so the decoded field is unchanged.

The store built without a mesh layout (``_build_legacy_store``) kept the digest of
that fourth capture: ``layout=None`` writes the same bytes as before the layout
existed. A fifth digest, ``EXPECTED_LAYOUT_DIGEST``, was captured for the store
built with a ``MeshLayout`` (``_build_layout_store``): it adds the cell centres,
the family bit fields, the zone codes, the edge tables and the engine attributes
of ``mesh/``. The layout arrays are synthetic and only valid in shape, since the
geometry of this golden (22 nodes, connectivity 0..39) has no real edges.

Both digests were re-captured with schema 3: ``mesh/z_interfaces`` holds one
column per cell, shape (layer interface, face), so its single chunk is
``c/0/0``, and ``zarr_schema_version`` is ``"3"``. The column given to the
writer is the same under every cell.

Both digests were re-captured again when ``mesh/`` became readable by UGRID
tools as stored: it gains ``node_x`` and ``node_y``, the topology names them in
``node_coordinates`` and ``face_node_connectivity`` declares ``_FillValue = -1``.
The golden store has no CRS, so it holds no ``mesh/crs``. ``layout=None`` still
writes no layout array.

Everything entering the digest is byte-identical on Linux and on Windows:

* member names are ``as_posix()`` relatives, so no path separator and no
  drive letter reaches the hash, and they are sorted by code point, so the
  order carries no locale;
* the member set is frozen in ``STORE_MEMBERS`` and holds Zarr nodes and
  chunks only, never a runtime artefact whose lifetime is platform-specific
  (a POSIX file lock outlives its release, its Windows twin does not);
* payloads are read and hashed as bytes, so no newline translation applies,
  and the JSON ones are re-serialised canonically, which drops key order and
  insignificant whitespace;
* chunk payloads are little-endian arrays compressed by the codec pinned in
  the node metadata, and nothing samples mtime, size, mode or owner.
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
from hydromodpy.results.zarr_store.mesh_layout import MeshLayout
from hydromodpy.results.zarr_store.zarr_finalizer import lock_path_for_store

_FROZEN_NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)

# Volatile attribute keys to strip from root / meta ``zarr.json`` payloads
# before computing the snapshot SHA-256.
_VOLATILE_KEYS = frozenset({"history", "created_at", "date_modified"})

# The root attributes carry no ``project`` nor ``processing_level``: the
# identity of the run poses them at the seal, not the ACDD composer.
EXPECTED_DIGEST = "0507a6484988f14c3ab039288bcc705dc39aed7ab5163d5b8788f8d6f6f7a331"
EXPECTED_LAYOUT_DIGEST = "9902066e758af116657d90272983cfcd6ac82ec8a7e5985321b3d8b02593fc6d"

STORE_MEMBERS: tuple[str, ...] = (
    "forcing/zarr.json",
    "head/c/0/0/0",
    "head/zarr.json",
    "mesh/face_node_connectivity/c/0/0",
    "mesh/face_node_connectivity/zarr.json",
    "mesh/node_x/c/0",
    "mesh/node_x/zarr.json",
    "mesh/node_y/c/0",
    "mesh/node_y/zarr.json",
    "mesh/topography/c/0",
    "mesh/topography/zarr.json",
    "mesh/topology/zarr.json",
    "mesh/vertices/c/0/0",
    "mesh/vertices/zarr.json",
    "mesh/z_interfaces/c/0/0",
    "mesh/z_interfaces/zarr.json",
    "mesh/zarr.json",
    "meta/zarr.json",
    "particles/zarr.json",
    "quantization_info/zarr.json",
    "state/zarr.json",
    "time/c/0",
    "time/zarr.json",
    "zarr.json",
)
"""Every file the digest walks, in the order it hashes them."""

LAYOUT_STORE_MEMBERS: tuple[str, ...] = (
    "forcing/zarr.json",
    "head/c/0/0/0",
    "head/zarr.json",
    "mesh/edge_face_connectivity/c/0/0",
    "mesh/edge_face_connectivity/zarr.json",
    "mesh/edge_family/c/0",
    "mesh/edge_family/zarr.json",
    "mesh/edge_node_connectivity/c/0/0",
    "mesh/edge_node_connectivity/zarr.json",
    "mesh/face_family/c/0",
    "mesh/face_family/zarr.json",
    "mesh/face_node_connectivity/c/0/0",
    "mesh/face_node_connectivity/zarr.json",
    "mesh/face_x/c/0",
    "mesh/face_x/zarr.json",
    "mesh/face_y/c/0",
    "mesh/face_y/zarr.json",
    "mesh/face_zone/c/0",
    "mesh/face_zone/zarr.json",
    "mesh/node_x/c/0",
    "mesh/node_x/zarr.json",
    "mesh/node_y/c/0",
    "mesh/node_y/zarr.json",
    "mesh/topography/c/0",
    "mesh/topography/zarr.json",
    "mesh/topology/zarr.json",
    "mesh/vertices/c/0/0",
    "mesh/vertices/zarr.json",
    "mesh/z_interfaces/c/0/0",
    "mesh/z_interfaces/zarr.json",
    "mesh/zarr.json",
    "meta/zarr.json",
    "particles/zarr.json",
    "quantization_info/zarr.json",
    "state/zarr.json",
    "time/c/0",
    "time/zarr.json",
    "zarr.json",
)
"""Every file the digest of the store written with a mesh layout walks."""


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


def _store_members(store_path: Path) -> list[tuple[str, Path]]:
    """Return the sorted ``(posix relative name, path)`` of every store file."""
    return sorted(
        (path.relative_to(store_path).as_posix(), path)
        for path in store_path.rglob("*")
        if path.is_file()
    )


def _content_digest(store_path: Path) -> str:
    """SHA-256 over sorted ``(relative_path, scrubbed_bytes)`` pairs of the store."""
    hasher = hashlib.sha256()
    for name, path in _store_members(store_path):
        scrubbed = _strip_volatile(path.read_bytes())
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(scrubbed)
        hasher.update(b"\xff")
    return hasher.hexdigest()


def _synthetic_layout() -> MeshLayout:
    """Return a layout valid in shape for the 10 cells and 22 nodes of the golden mesh."""
    return MeshLayout(
        face_x=np.linspace(0.5, 9.5, 10),
        face_y=np.full(10, 0.5),
        center_kind="cell_center",
        face_family=np.array([1, 1, 3, 2, 0, 0, 0, 4, 4, 0], dtype="int32"),
        family_names=("rivers", "lakes", "boundary:west"),
        face_zone=np.array([0, 0, 0, 0, 1, 1, 1, 1, -1, -1], dtype="int32"),
        zone_names=("zone_1", "zone_2"),
        edge_node_connectivity=np.array([[0, 1], [1, 2], [2, 3], [3, 4]], dtype="int32"),
        edge_face_connectivity=np.array([[0, -1], [0, 1], [1, 2], [2, -1]], dtype="int32"),
        edge_family=np.array([4, 0, 2, 4], dtype="int32"),
        edge_family_names=("lakes", "boundary:west", "boundary:east"),
        attrs={
            "engine": "regular",
            "engine_version": "1.0.0",
            "crs": 'LOCAL_CS["golden"]',
            "mesh_request_hash": "0123456789abcdef",
            "qa": {"n_cells": 10, "area_sum_m2": 10.0, "ratio": None},
            "library_versions": {"shapely": "2.0.0"},
        },
    )


def _build_store(path: Path, *, layout: MeshLayout | None) -> Path:
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
        layout=layout,
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


def _build_legacy_store(path: Path) -> Path:
    """Create the store as it was written before the mesh layout existed."""
    return _build_store(path, layout=None)


def _build_layout_store(path: Path) -> Path:
    """Create the same store with the mesh layout written under ``mesh/``."""
    return _build_store(path, layout=_synthetic_layout())


@pytest.fixture
def pinned_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the hydromodpy version label that bleeds into the root attrs.

    The digest is then independent of the installed package version.
    """
    monkeypatch.setattr("hydromodpy.results.zarr_store.zarr_schema._HMP_VERSION", "test-version")
    monkeypatch.setattr("hydromodpy.results.zarr_store.acdd._HMP_VERSION", "test-version")


def test_simulation_zarr_store_is_byte_stable(
    tmp_path: Path, freeze_clock: None, pinned_versions: None
) -> None:
    """The directory-store content must match the golden SHA-256."""
    store_path = _build_legacy_store(tmp_path / FIELDS_STORE_NAME)
    digest = _content_digest(store_path)

    assert digest == EXPECTED_DIGEST, (
        "SimulationZarr store content drifted from the golden snapshot.\n"
        f"  expected: {EXPECTED_DIGEST}\n"
        f"  actual:   {digest}\n"
        "If the change is intentional, recompute the snapshot."
    )


def test_a_store_with_a_mesh_layout_is_byte_stable(
    tmp_path: Path, freeze_clock: None, pinned_versions: None
) -> None:
    """The store written with a layout must match its own golden SHA-256."""
    store_path = _build_layout_store(tmp_path / FIELDS_STORE_NAME)
    digest = _content_digest(store_path)

    assert digest == EXPECTED_LAYOUT_DIGEST, (
        "The store written with a mesh layout drifted from the golden snapshot.\n"
        f"  expected: {EXPECTED_LAYOUT_DIGEST}\n"
        f"  actual:   {digest}\n"
        "If the change is intentional, recompute the snapshot."
    )


def test_store_holds_only_zarr_hierarchy_members(tmp_path: Path) -> None:
    """The store carries the Zarr hierarchy and nothing else.

    A stray member shifts the digest without changing any simulation result,
    and the store stops being what a reader opens: ``zarr`` warns that the
    entry is not a component of the hierarchy.
    """
    legacy = _build_legacy_store(tmp_path / "legacy" / FIELDS_STORE_NAME)
    layout = _build_layout_store(tmp_path / "layout" / FIELDS_STORE_NAME)

    assert tuple(name for name, _ in _store_members(legacy)) == STORE_MEMBERS
    assert tuple(name for name, _ in _store_members(layout)) == LAYOUT_STORE_MEMBERS


def test_the_write_lock_is_never_a_store_member(tmp_path: Path) -> None:
    """The write lock is addressed outside the store, on every platform.

    POSIX keeps a lock file on disk after release while Windows unlinks it,
    so a lock inside the store makes its content platform-dependent. Reading
    the members while the lock is held catches the defect on both.
    """
    store_path = tmp_path / FIELDS_STORE_NAME
    store = SimulationZarr.create(store_path, n_cells=4, n_layers=1)
    try:
        idle = _store_members(store_path)
        with store._guard_write():
            held = _store_members(store_path)
            lock_is_outside = lock_path_for_store(store_path).is_file()
    finally:
        store.close()

    assert held == idle
    assert lock_is_outside
