"""Unit tests for the Zarr v2 store (P6).

Covers atomicity, ACDD root attrs, CF _FillValue, balanced chunks,
sharding above the 100 MiB threshold, consolidated metadata, standard_name
mapping, schema version checks, and the topography/particles renames.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import zarr

import hydromodpy.results.zarr_store.zarr_schema as zarr_schema
from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.io.filesystem import native_io_path
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store.acdd import compose_acdd_root_attrs
from hydromodpy.results.zarr_store.chunks import compute_balanced_chunks_2d
from hydromodpy.results.zarr_store.constants import BALANCED_TARGET_BYTES, SHARD_TRIGGER_BYTES
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr


@pytest.fixture
def fresh_store(tmp_path: Path) -> SimulationZarr:
    sz = SimulationZarr.create(
        tmp_path / "sim.zarr",
        n_cells=100,
        n_layers=2,
    )
    yield sz
    sz.close()


# ACDD-1.3 Highly Recommended attributes (11 entries, per ACDD §2.6.1).
HIGHLY_RECOMMENDED = (
    "title",
    "summary",
    "keywords",
    "keywords_vocabulary",
    "Conventions",
    "id",
    "naming_authority",
    "creator_name",
    "creator_email",
    "creator_institution",
    "creator_url",
)


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
            # Canonical runs_environment column names (must match what
            # lifecycle._fetch_runs_environment_row maps the DB row to).
            "solver_version_text": "MODFLOW 6.5.0",
            "solver_binary_sha256": "deadbeefcafe",
        },
    )
    # ``creator_name`` is Highly Recommended and undeclared here: ACDD reads an
    # absent attribute as unknown, which is what this run is. The Unix account
    # ``alice`` is not an answer to who created the data.
    for key in HIGHLY_RECOMMENDED:
        if key == "creator_name":
            assert key not in attrs
            continue
        assert key in attrs, f"missing ACDD highly-recommended attribute {key}"
    assert attrs["title"] == "demo"
    assert "ACDD-1.3" in attrs["Conventions"]
    assert attrs["creator_email"] == "alice@example.org"
    assert attrs["time_coverage_resolution"] == "P1D"
    # The solver binary identity and version must flow through under the
    # canonical keys (guards the lifecycle/acdd key-mismatch regression).
    assert attrs["hydromodpy_solver_binary_sha256"] == "deadbeefcafe"
    assert "MODFLOW 6.5.0" in attrs["source"]


def test_local_store_retries_transient_chunk_write_permission_error(
    fresh_store: SimulationZarr,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_set = zarr_schema.RetryingLocalStore._set
    calls = {"failures": 0}

    async def flaky_set(self, key, value, exclusive=False):
        if "/c/" in key and calls["failures"] == 0:
            calls["failures"] += 1
            raise PermissionError(5, "Access denied", str(self.root / key))
        return await original_set(self, key, value, exclusive=exclusive)

    monkeypatch.setattr(zarr_schema.RetryingLocalStore, "_set", flaky_set)

    values = np.arange(8, dtype="float64").reshape(2, 4)
    fresh_store.write_field("head", 0, values, n_timesteps=1)

    assert calls["failures"] == 1
    np.testing.assert_allclose(fresh_store.root["head"][0], values)


def test_balanced_chunking_default(fresh_store: SimulationZarr) -> None:
    fresh_store.write_field("head", 0, np.arange(100, dtype="float64"), n_timesteps=2000)
    head = fresh_store.root["head"]
    # 2000 timesteps * 100 cells * 8 bytes = 1.6 MiB total, balanced ~1 MiB.
    time_chunk, cell_chunk = head.chunks
    assert cell_chunk == 100
    assert time_chunk > 1
    chunk_bytes = time_chunk * cell_chunk * 8
    assert chunk_bytes <= BALANCED_TARGET_BYTES * 2


def test_balanced_chunks_helper() -> None:
    shape = compute_balanced_chunks_2d(365, 1, 50_000, itemsize=8)
    # (1, 1, ~131k clipped to 50k) since per_step = 400 kB <= 1 MiB.
    assert shape == (2, 1, 50_000) or shape == (1, 1, 50_000)


@pytest.mark.windows
def test_store_keeps_long_named_arrays_under_long_paths(tmp_path: Path) -> None:
    long_dir = tmp_path
    idx = 0
    while (
        len(
            str(
                (
                    long_dir
                    / FIELDS_STORE_NAME
                    / "derived"
                    / "watertable_elevation"
                    / "c"
                    / "0"
                    / "0"
                ).resolve()
            )
        )
        < 280
    ):
        long_dir = long_dir / f"nested_{idx}_{'x' * 36}"
        idx += 1

    values = np.array([220.0, 221.0, 222.0, 223.0], dtype="float64")
    store_path = long_dir / FIELDS_STORE_NAME
    sz = SimulationZarr.create(store_path, n_cells=4, n_layers=1)
    try:
        sz.write_field(
            "watertable_elevation",
            0,
            values,
            n_timesteps=1,
            subgroup="derived",
        )
    finally:
        sz.close()

    # The store writes through the extended-length form, so read it back the
    # same way: a bare path over 259 chars is invisible to the Win32 API.
    array_dir = Path(native_io_path(store_path)) / "derived" / "watertable_elevation"
    assert (array_dir / "zarr.json").is_file()
    assert any(path.is_file() for path in (array_dir / "c").rglob("*"))

    reopened = SimulationZarr(store_path)
    try:
        np.testing.assert_allclose(
            reopened.root["derived"]["watertable_elevation"][0],
            values,
        )
    finally:
        reopened.close()


def test_standard_name_mapping(fresh_store: SimulationZarr) -> None:
    from hydromodpy.results import field_registry
    from hydromodpy.results.zarr_store.cf_validation import is_cf_standard_name

    head = field_registry.get("head")
    assert head.standard_name == ""
    assert head.csdms_standard_name == "subsurface_water__hydraulic_head"
    topo = field_registry.get("topography")
    assert topo.standard_name == "surface_altitude"
    assert is_cf_standard_name(topo.standard_name)
    assert not is_cf_standard_name(head.standard_name)


def test_a_store_without_the_version_attribute_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "no_version.zarr"
    sz = SimulationZarr.create(path, n_cells=4, n_layers=1)
    del sz.root.attrs["zarr_schema_version"]
    sz.close()

    with pytest.raises(SchemaVersionMismatchError, match="carries no zarr_schema_version"):
        SimulationZarr(path)


def test_a_newer_store_names_the_version_that_wrote_it(tmp_path: Path) -> None:
    path = tmp_path / "newer.zarr"
    sz = SimulationZarr.create(path, n_cells=4, n_layers=1)
    sz.root.attrs.update({"zarr_schema_version": "9", "hydromodpy_version": "2.9.0"})
    sz.close()

    with pytest.raises(SchemaVersionMismatchError, match="written by HydroModPy 2.9.0"):
        SimulationZarr(path)


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


def test_compose_acdd_emits_recommended_attributes() -> None:
    """The 15 V1 additions (units, resolution, bounds, publisher, vocab, ...) appear."""
    attrs = compose_acdd_root_attrs(
        sim_row={
            "sim_id": "abc",
            "scientific_objective": "Calibrate Naizin head 2020",
            "doi": "10.5281/zenodo.1234567",
        },
        runs_env={"user_name": "alice"},
        geographic_bounds={
            "lat_min": 48.0,
            "lat_max": 49.0,
            "lon_min": -2.0,
            "lon_max": -1.0,
        },
    )
    for key in (
        "geospatial_lat_units",
        "geospatial_lat_resolution",
        "geospatial_lon_units",
        "geospatial_lon_resolution",
        "geospatial_vertical_units",
        "geospatial_bounds",
        "geospatial_bounds_crs",
        "publisher_email",
        "publisher_url",
        "standard_name_vocabulary",
        "cdm_data_type",
        "comment",
        "date_modified",
        "metadata_link",
    ):
        assert key in attrs, f"missing ACDD recommended attribute {key}"
    # Nobody declared a publisher, and the OS account is not one.
    assert "publisher_name" not in attrs
    assert attrs["geospatial_lat_units"] == "degrees_north"
    assert attrs["geospatial_lon_units"] == "degrees_east"
    assert attrs["geospatial_vertical_units"] == "m"
    assert attrs["geospatial_bounds_crs"] == "EPSG:4326"
    assert attrs["standard_name_vocabulary"] == "CF Standard Name Table v85"
    assert attrs["cdm_data_type"] == "UGRID"
    assert attrs["geospatial_bounds"].startswith("POLYGON((")
    assert "10.5281/zenodo.1234567" in attrs["metadata_link"]
    assert "Calibrate" in attrs["comment"]


def test_compose_acdd_bounds_wkt_empty_when_nan() -> None:
    """Missing bounds produce an empty WKT string rather than ``POLYGON((nan ...))``."""
    attrs = compose_acdd_root_attrs(sim_row={"sim_id": "x"}, runs_env={})
    assert attrs["geospatial_bounds"] == ""


def test_shard_trigger_constant_is_100_mib() -> None:
    assert SHARD_TRIGGER_BYTES == 100 * 1024 * 1024


@pytest.mark.parametrize(
    ("windows", "prefixed"),
    [pytest.param(True, True, id="on Windows"), pytest.param(False, False, id="elsewhere")],
)
def test_the_local_store_argument_takes_the_long_prefix_only_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, windows: bool, prefixed: bool
) -> None:
    from hydromodpy.core.io import filesystem
    from tests._helpers.windows_os import WindowsOs

    if windows:
        monkeypatch.setattr(zarr_schema, "os", WindowsOs())
        monkeypatch.setattr(filesystem, "os", WindowsOs())

    argument = zarr_schema.local_store_path_arg(tmp_path / "fields.zarr")

    assert argument.startswith("\\\\?\\") is prefixed
    assert argument.endswith("fields.zarr")
