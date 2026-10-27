"""A mesh stored in the project cache comes back whole, under a key that names its request."""

from __future__ import annotations

import json
from dataclasses import replace
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.mesh import cache, registry
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.model.mesh_qa import SHAPE_KEYS
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    LAMBERT93_WKT,
    grid_spec,
    mesh_request,
    regular_mesh,
)

X0, Y0 = L93_ORIGIN

RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
CONTACT = LineString([(X0 + 400, Y0), (X0 + 600, Y0 + 1000)])

needs_gmsh = pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed")


def _request(size: float = 100.0, n: int = 10) -> MeshRequest:
    """The 1 km square at Lambert-93 magnitudes, with a river and a geology contact."""
    return mesh_request(
        grid_spec(n, n, 1000.0 / n, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT),
        nominal_size_m=size,
        lines=(
            LineFamilySpec("rivers", "cell", (RIVER,)),
            LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
        ),
    )


def _assert_same_mesh(back, built) -> None:
    np.testing.assert_array_equal(back.mesh.vertices, built.mesh.vertices)
    np.testing.assert_array_equal(back.connectivity_rows, built.connectivity_rows)
    np.testing.assert_array_equal(back.centers, built.centers)
    assert back.mesh.cell_types == built.mesh.cell_types
    assert back.mesh.structured_shape == built.mesh.structured_shape
    assert back.structured_shape == built.structured_shape
    assert back.center_kind == built.center_kind
    assert back.crs_wkt == built.crs_wkt
    assert back.identity == built.identity
    assert back.qa.as_dict() == built.qa.as_dict()
    assert back.zone_names == built.zone_names
    assert set(back.mesh.cell_data) == set(built.mesh.cell_data)
    for name, values in built.mesh.cell_data.items():
        np.testing.assert_array_equal(back.mesh.cell_data[name], values)
    assert set(back.mesh.point_data) == set(built.mesh.point_data)
    for name, values in built.mesh.point_data.items():
        np.testing.assert_array_equal(back.mesh.point_data[name], values)
    assert len(back.cell_chains) == len(built.cell_chains)
    for chain, expected in zip(back.cell_chains, built.cell_chains, strict=True):
        assert (chain.family, chain.chain_id) == (expected.family, expected.chain_id)
        np.testing.assert_array_equal(chain.cell_ids, expected.cell_ids)
    if built.cell_zone is None:
        assert back.cell_zone is None
    else:
        np.testing.assert_array_equal(back.cell_zone, built.cell_zone)
    if built.face_families is None:
        assert back.face_families is None
    else:
        assert back.face_families.names == built.face_families.names
        for column in ("family", "cell_a", "cell_b", "node_a", "node_b", "zone_left", "zone_right"):
            np.testing.assert_array_equal(
                getattr(back.face_families, column), getattr(built.face_families, column)
            )


def test_a_regular_mesh_with_its_families_comes_back_whole(tmp_path) -> None:
    built = RegularMeshEngine().build(_request())
    assert built.cell_chains and built.face_families is not None

    cache.save_cell_mesh(built, tmp_path / "entry")
    back = cache.load_cell_mesh(tmp_path / "entry")

    _assert_same_mesh(back, built)


@needs_gmsh
@pytest.mark.parametrize("engine_id", ["triangle", "voronoi"])
def test_a_generated_mesh_comes_back_whole(tmp_path, engine_id) -> None:
    built = registry.create(engine_id).build(_request(size=60.0))

    cache.save_cell_mesh(built, tmp_path / "entry")
    back = cache.load_cell_mesh(tmp_path / "entry")

    _assert_same_mesh(back, built)


def test_a_complete_entry_is_not_replaced(tmp_path) -> None:
    built = RegularMeshEngine().build(_request())
    cache.save_cell_mesh(built, tmp_path / "entry")
    stored = (tmp_path / "entry" / cache.ARRAYS_FILENAME).stat().st_mtime_ns

    cache.save_cell_mesh(RegularMeshEngine().build(_request(n=20)), tmp_path / "entry")

    assert (tmp_path / "entry" / cache.ARRAYS_FILENAME).stat().st_mtime_ns == stored
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_an_entry_without_its_description_is_not_an_entry(tmp_path) -> None:
    (tmp_path / "entry").mkdir()
    (tmp_path / "entry" / cache.ARRAYS_FILENAME).write_bytes(b"")

    assert not cache.has_cell_mesh(tmp_path / "entry")
    with pytest.raises(MeshError, match="No cached mesh"):
        cache.load_cell_mesh(tmp_path / "entry")


def test_an_entry_of_another_schema_is_refused_by_name(tmp_path) -> None:
    cache.save_cell_mesh(RegularMeshEngine().build(_request()), tmp_path / "entry")
    description = tmp_path / "entry" / cache.DESCRIPTION_FILENAME
    description.write_text(description.read_text().replace(cache.SCHEMA_VERSION, "older"))

    with pytest.raises(MeshError, match="schema 'older'"):
        cache.load_cell_mesh(tmp_path / "entry")


def test_the_key_names_the_request_the_engine_and_its_version(tmp_path, monkeypatch) -> None:
    class Engine:
        engine_id = "probe"
        engine_version = "1.0.0"

    class NewerEngine(Engine):
        engine_version = "1.0.1"

    class OtherEngine(Engine):
        engine_id = "other"

    key = cache.cache_key(_request(), Engine)

    assert key == cache.cache_key(_request(), Engine)
    assert key != cache.cache_key(_request(size=80.0), Engine)
    assert key != cache.cache_key(_request(), NewerEngine)
    assert key != cache.cache_key(_request(), OtherEngine)
    monkeypatch.setattr(cache.metadata, "version", lambda name: "9.9.9")
    assert key != cache.cache_key(_request(), Engine)


def test_an_entry_lives_under_the_project_cache_directory(tmp_path) -> None:
    key = cache.cache_key(_request(), RegularMeshEngine)

    assert cache.cache_dir(tmp_path, key) == tmp_path / ".hmp" / "mesh_cache" / key


@pytest.mark.parametrize(
    "engine_id",
    [
        "regular",
        pytest.param("triangle", marks=needs_gmsh),
        pytest.param("voronoi", marks=needs_gmsh),
    ],
)
def test_an_entry_stored_before_the_shape_entries_is_read_with_them_measured(
    tmp_path, engine_id
) -> None:
    request = _request() if engine_id == "regular" else _request(size=60.0)
    built = registry.create(engine_id).build(request)
    cache.save_cell_mesh(built, tmp_path / "entry")
    path = tmp_path / "entry" / cache.DESCRIPTION_FILENAME
    description = json.loads(path.read_text())
    for name in SHAPE_KEYS:
        del description["qa"][name]
    path.write_text(json.dumps(description))

    back = cache.load_cell_mesh(tmp_path / "entry")

    assert description["schema"] == cache.SCHEMA_VERSION
    _assert_same_mesh(back, built)


def test_a_mesh_without_family_and_with_node_fields_comes_back_whole(tmp_path) -> None:
    grid = regular_mesh(3, 4, dx=25.0, xmin=X0, ymin=Y0)
    built = replace(
        grid, mesh=grid.mesh.with_point_data(z=np.arange(grid.mesh.n_nodes, dtype=float))
    )
    assert built.face_families is None and built.cell_zone is None

    cache.save_cell_mesh(built, tmp_path / "entry")

    _assert_same_mesh(cache.load_cell_mesh(tmp_path / "entry"), built)


def test_an_absent_gmsh_is_part_of_the_key(monkeypatch) -> None:
    installed = metadata.version

    def without_gmsh(name: str) -> str:
        if name == "gmsh":
            raise metadata.PackageNotFoundError(name)
        return installed(name)

    key = cache.cache_key(_request(), RegularMeshEngine)
    monkeypatch.setattr(cache.metadata, "version", without_gmsh)

    assert cache.library_versions()["gmsh"] == "absent"
    assert cache.cache_key(_request(), RegularMeshEngine) != key


def test_an_entry_stored_first_by_a_concurrent_run_stands(tmp_path, monkeypatch) -> None:
    target = tmp_path / "entry"
    theirs = RegularMeshEngine().build(_request(n=20))
    rename = Path.rename

    def lose_the_race(self: Path, destination: Path) -> Path:
        # The other run, another process, renames its staging first; ours then
        # meets a full directory.
        monkeypatch.setattr(Path, "rename", rename)
        monkeypatch.setattr(cache, "os", SimpleNamespace(getpid=lambda: 1))
        cache.save_cell_mesh(theirs, destination)
        return rename(self, destination)

    monkeypatch.setattr(Path, "rename", lose_the_race)
    cache.save_cell_mesh(RegularMeshEngine().build(_request()), target)

    assert cache.load_cell_mesh(target).n_cells == theirs.n_cells
    assert sorted(p.name for p in tmp_path.iterdir()) == ["entry"]


def test_a_failed_write_leaves_no_entry_and_no_staging(tmp_path, monkeypatch) -> None:
    def full_disk(self: Path, destination: Path) -> Path:
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "rename", full_disk)

    with pytest.raises(OSError, match="No space left"):
        cache.save_cell_mesh(RegularMeshEngine().build(_request()), tmp_path / "entry")
    assert list(tmp_path.iterdir()) == []


def test_an_entry_whose_arrays_are_unreadable_is_refused_by_name(tmp_path) -> None:
    cache.save_cell_mesh(RegularMeshEngine().build(_request()), tmp_path / "entry")
    (tmp_path / "entry" / cache.ARRAYS_FILENAME).write_bytes(b"not an npz")

    with pytest.raises(MeshError, match="is unreadable: .* Delete it"):
        cache.load_cell_mesh(tmp_path / "entry")
