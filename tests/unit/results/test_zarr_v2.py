"""Unit tests for the Zarr v2 store (P6).

Covers atomicity, ACDD root attrs, CF _FillValue, balanced chunks,
sharding above the 100 MiB threshold, consolidated metadata, standard_name
mapping, schema version checks, and the topography/particles renames.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr

from hydromodpy.results.zarr_store import (
    BALANCED_TARGET_BYTES,
    HIGHLY_RECOMMENDED,
    SHARD_TRIGGER_BYTES,
    ZARR_SCHEMA_VERSION,
    SimulationZarr,
    ZarrSchemaVersionError,
    atomic_write_array,
    compose_acdd_root_attrs,
    compute_balanced_chunks_2d,
    should_use_sharding,
)


@pytest.fixture
def fresh_store(tmp_path: Path) -> SimulationZarr:
    sz = SimulationZarr.create(
        tmp_path / "sim.zarr",
        n_cells=100,
        n_layers=2,
    )
    yield sz
    sz.close()


def test_atomic_write_completes_marker(tmp_path: Path) -> None:
    path = atomic_write_array(
        tmp_path,
        "alpha",
        np.arange(20, dtype="float64"),
        attrs={"long_name": "demo"},
    )
    root = zarr.open_group(zarr.storage.LocalStore(str(path)), mode="r")
    assert root.attrs["_status"] == "complete"
    assert path.name == "alpha"
    assert "value" in root
    assert np.allclose(root["value"][:], np.arange(20))


def test_atomic_write_rolls_back_on_failure(tmp_path: Path) -> None:
    bad_attrs: dict = {"unserializable": object()}
    with pytest.raises(Exception):
        atomic_write_array(tmp_path, "boom", np.arange(5, dtype="float64"), attrs=bad_attrs)
    siblings = list(tmp_path.iterdir())
    # No final 'boom' directory, and the tmp directory has been removed.
    assert not any(s.name == "boom" for s in siblings)
    assert not any(s.name.startswith("boom.zarr.tmp-") for s in siblings)


def test_filelock_prevents_concurrent_write(tmp_path: Path) -> None:
    """The .lock file uses filelock semantics: two acquire() calls from two
    independent FileLock objects must serialise."""
    from filelock import FileLock, Timeout

    path = tmp_path / "sim.zarr"
    SimulationZarr.create(path, n_cells=10, n_layers=1).close()

    lock_a = FileLock(str(path / ".lock"))
    lock_b = FileLock(str(path / ".lock"))
    lock_a.acquire(timeout=1.0)
    try:
        with pytest.raises(Timeout):
            lock_b.acquire(timeout=0.5)
    finally:
        lock_a.release()
    # After release the second lock acquires successfully.
    lock_b.acquire(timeout=1.0)
    lock_b.release()


def test_acdd_root_attrs_present(fresh_store: SimulationZarr) -> None:
    attrs = fresh_store.write_acdd_root_attrs(
        sim_row={
            "sim_id": "11111111-1111-7111-8111-111111111111",
            "name": "demo",
            "description": "tiny groundwater run",
            "project": "demo_project",
            "solver": "modflow6",
            "period_start": "2020-01-01",
            "period_end": "2020-01-10",
            "time_unit": "day",
            "contact_email": "alice@example.org",
        },
        runs_env={
            "user_name": "alice",
            "hostname": "hostX",
            "hydromodpy_version": "2.0.0",
            "git_commit": "abc1234",
            "rng_seed": 42,
            "mf6_version_text": "MODFLOW 6.5.0",
        },
    )
    for key in HIGHLY_RECOMMENDED:
        assert key in attrs, f"missing ACDD highly-recommended attribute {key}"
    assert attrs["title"] == "demo"
    assert "ACDD-1.3" in attrs["Conventions"]
    assert attrs["creator_name"] == "alice"
    assert attrs["creator_email"] == "alice@example.org"
    assert attrs["time_coverage_resolution"] == "P1D"


def test_cf_fillvalue_attached_to_head(fresh_store: SimulationZarr) -> None:
    fresh_store.write_field("head", 0, np.arange(100, dtype="float64"), n_timesteps=5)
    head = fresh_store.root["head"]
    assert "_FillValue" in head.attrs
    assert np.isnan(head.attrs["_FillValue"])
    assert head.attrs.get("csdms_standard_name") == "subsurface_water__hydraulic_head"
    assert head.attrs.get("long_name", "").startswith("Groundwater head")


def test_balanced_chunking_default(fresh_store: SimulationZarr) -> None:
    fresh_store.write_field("head", 0, np.arange(100, dtype="float64"), n_timesteps=2000)
    head = fresh_store.root["head"]
    # 2000 timesteps * 100 cells * 8 bytes = 1.6 MiB total, balanced ~1 MiB.
    time_chunk, cell_chunk = head.chunks
    assert cell_chunk == 100
    assert time_chunk > 1
    chunk_bytes = time_chunk * cell_chunk * 8
    assert chunk_bytes <= BALANCED_TARGET_BYTES * 2


def test_sharding_above_100mib_threshold() -> None:
    n_timesteps = 1000
    layer_bytes = 50_000 * 8 * 4  # 1.6 MiB per step
    assert should_use_sharding(n_timesteps, layer_bytes)
    assert not should_use_sharding(10, 1000 * 8)


def test_balanced_chunks_helper() -> None:
    shape = compute_balanced_chunks_2d(365, 1, 50_000, itemsize=8)
    # (1, 1, ~131k clipped to 50k) since per_step = 400 kB <= 1 MiB.
    assert shape == (2, 1, 50_000) or shape == (1, 1, 50_000)


def test_consolidate_metadata_written_on_finalize(tmp_path: Path) -> None:
    path = tmp_path / "consol.zarr"
    sz = SimulationZarr.create(path, n_cells=10, n_layers=1)
    sz.write_field("head", 0, np.arange(10, dtype="float64"), n_timesteps=2)
    sz.consolidate_metadata()
    sz.close()
    # ``zarr.json`` for the root contains the consolidated metadata pointer
    # in Zarr v3 directory stores; .zmetadata is the v2 equivalent. We just
    # check the store reopens without scanning.
    sz2 = SimulationZarr(path)
    try:
        assert "head" in sz2.root
    finally:
        sz2.close()


def test_standard_name_mapping(fresh_store: SimulationZarr) -> None:
    from hydromodpy.results.zarr_store import alias_for

    head = alias_for("head")
    assert head.standard_name == ""
    assert head.csdms_standard_name == "subsurface_water__hydraulic_head"
    topo = alias_for("topography")
    assert topo.standard_name == "surface_altitude"


def test_zarr_schema_version_stored(fresh_store: SimulationZarr) -> None:
    assert fresh_store.root.attrs["zarr_schema_version"] == ZARR_SCHEMA_VERSION
    meta = fresh_store.root.get("meta")
    assert meta is not None
    assert meta.attrs["zarr_schema_version"] == ZARR_SCHEMA_VERSION


def test_zarr_schema_version_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "old.zarr"
    sz = SimulationZarr.create(path, n_cells=4, n_layers=1)
    sz.root.attrs["zarr_schema_version"] = "1"
    sz.close()
    with pytest.raises(ZarrSchemaVersionError):
        SimulationZarr(path)


def test_groups_renamed_topography_and_particles(fresh_store: SimulationZarr) -> None:
    fresh_store.write_mesh(
        vertices=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]]),
        face_node_connectivity=np.array([[0, 1, 2]], dtype="int32"),
        z_interfaces=np.array([0.0, -10.0]),
        topography=np.array([5.0]),
    )
    mesh = fresh_store.root["mesh"]
    assert "topography" in mesh
    assert "surface_top" not in mesh
    topo = mesh["topography"]
    assert topo.attrs.get("standard_name") == "surface_altitude"
    # particles group is created at init.
    assert "particles" in fresh_store.root


def test_balanced_default_true_on_init(tmp_path: Path) -> None:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    assert sz.balanced is True
    sz.close()
    sz2 = SimulationZarr(tmp_path / "sim.zarr")
    assert sz2.balanced is True
    sz2.close()


def test_compose_acdd_returns_floats_for_bounds() -> None:
    attrs = compose_acdd_root_attrs(
        sim_row={"sim_id": "x"},
        runs_env={},
        geographic_bounds={
            "lat_min": 48.0,
            "lat_max": 49.0,
            "lon_min": -2.0,
            "lon_max": -1.0,
        },
    )
    assert attrs["geospatial_lat_min"] == 48.0
    assert attrs["geospatial_lat_max"] == 49.0
    assert attrs["geospatial_lon_max"] == -1.0


def test_subgroups_created_at_init(fresh_store: SimulationZarr) -> None:
    expected = {"meta", "mesh", "state", "derived", "budget", "particles", "forcing"}
    actual = set(fresh_store.root.keys())
    # Subgroups are a subset; root may also have other arrays added later.
    assert expected.issubset(actual)


def test_shard_trigger_constant_is_100_mib() -> None:
    assert SHARD_TRIGGER_BYTES == 100 * 1024 * 1024
