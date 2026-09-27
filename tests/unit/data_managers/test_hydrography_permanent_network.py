"""The hydrography loader writes the permanent network beside the full one.

Only when the network says which reaches flow all year, through the canonical
``permanence`` column; the loader knows no provider vocabulary, and a network
that says nothing has no permanent part. The cache answers the layer it was
asked for, not any layer of the same source over the same box.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN
from hydromodpy.data.variables.hydrography.config import HydrographyConfig
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_VECTOR_FILENAME,
)

from ._test_hydrography_full_builders import WhiteboxStubBackend, _fake_inputs

pytestmark = pytest.mark.fast

_FETCH = "hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source"
_BACKEND = "hydromodpy.spatial.delineation.get_whitebox_backend"


def _reaches(permanence: list[str] | None, *, x0: float = 350000.0) -> gpd.GeoDataFrame:
    """Parallel reaches inside the fake watershed, one per entry."""
    n = 3 if permanence is None else len(permanence)
    columns: dict[str, list[object]] = {"gid": list(range(n))}
    if permanence is not None:
        columns[PERMANENCE_COLUMN] = permanence
    return gpd.GeoDataFrame(
        columns,
        geometry=[
            LineString([(x0 + i * 100, 6750000.0), (x0 + i * 100, 6751000.0)]) for i in range(n)
        ],
        crs="EPSG:2154",
    )


def _manager(tmp_path: Path, sources: list[dict]):
    from hydromodpy.data.variables.hydrography.manager import HydrographyManager

    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=sources, mask_path=inputs.mask_path)
    return HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)


def _permanent_path(tmp_path: Path) -> Path:
    return (
        tmp_path
        / PREPROCESSING_DIR
        / "hydrography"
        / HYDROGRAPHIC_NETWORK_REFERENCE_PERMANENT_VECTOR_FILENAME
    )


def _metadata(result) -> dict:
    return result.fields[0].metadata


@patch(_FETCH)
@patch(_BACKEND)
def test_the_permanent_reaches_are_written_beside_the_full_network(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent", "intermittent", "permanent"])

    result = _manager(tmp_path, [{"source": "osm"}]).load()

    full = gpd.read_file(_metadata(result)["vector_path"])
    permanent = gpd.read_file(_metadata(result)["permanent_vector_path"])
    assert len(full) == 3, "the reference network keeps every reach"
    assert sorted(full[PERMANENCE_COLUMN]) == ["intermittent", "permanent", "permanent"]
    assert sorted(permanent["gid"]) == [0, 2]
    assert set(permanent[PERMANENCE_COLUMN]) == {"permanent"}
    assert Path(_metadata(result)["permanent_vector_path"]) == _permanent_path(tmp_path)


@patch(_FETCH)
@patch(_BACKEND)
def test_a_network_that_says_nothing_has_no_permanent_part(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(None)

    result = _manager(tmp_path, [{"source": "osm"}]).load()

    assert _metadata(result)["permanent_vector_path"] is None
    assert not _permanent_path(tmp_path).exists()


@patch(_FETCH)
@patch(_BACKEND)
def test_a_permanent_network_left_by_an_earlier_run_is_removed(
    backend_factory, fetch, tmp_path: Path
) -> None:
    """Switching to a source that does not say must not leave the old file to be read."""
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent", "permanent"])
    _manager(tmp_path, [{"source": "osm"}]).load()
    assert _permanent_path(tmp_path).exists()

    fetch.return_value = _reaches(None)
    result = _manager(tmp_path, [{"source": "osm"}]).load()

    assert _metadata(result)["permanent_vector_path"] is None
    assert list(_permanent_path(tmp_path).parent.glob("streams_permanent.*")) == []


@patch(_FETCH)
@patch(_BACKEND)
def test_a_network_with_no_permanent_reach_writes_no_permanent_file(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["intermittent", "dry"])

    result = _manager(tmp_path, [{"source": "osm"}]).load()

    assert _metadata(result)["permanent_vector_path"] is None


@patch(_FETCH)
@patch(_BACKEND)
def test_reaches_from_a_source_that_does_not_say_are_unknown_not_permanent(
    backend_factory, fetch, tmp_path: Path
) -> None:
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.side_effect = [_reaches(["permanent"]), _reaches(None, x0=351000.0)]

    result = _manager(tmp_path, [{"source": "bdtopage"}, {"source": "osm"}]).load()

    full = gpd.read_file(_metadata(result)["vector_path"])
    permanent = gpd.read_file(_metadata(result)["permanent_vector_path"])
    assert sorted(full[PERMANENCE_COLUMN]) == ["permanent", "unknown", "unknown", "unknown"]
    assert len(permanent) == 1


@patch(_FETCH)
@patch(_BACKEND)
def test_sources_answering_in_two_crs_are_concatenated(
    backend_factory, fetch, tmp_path: Path
) -> None:
    """BD Topage answers in Lambert-93 and OSM in WGS84; one section may name both."""
    backend_factory.return_value = WhiteboxStubBackend()
    fetch.side_effect = [
        _reaches(["permanent"]),
        _reaches(None, x0=351000.0).to_crs("EPSG:4326"),
    ]

    result = _manager(tmp_path, [{"source": "bdtopage"}, {"source": "osm"}]).load()

    full = gpd.read_file(_metadata(result)["vector_path"])
    assert len(full) == 4
    assert full.crs.to_epsg() == 2154


# --------------------------------------------------------------------------- #
# The cache answers the layer it was asked for
# --------------------------------------------------------------------------- #


def _cached_manager(tmp_path: Path, catalog, typename: str):
    from hydromodpy.data.variables.hydrography.manager import HydrographyManager

    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(
        sources=[{"source": "bdtopage", "typename": typename}],
        mask_path=inputs.mask_path,
    )
    return HydrographyManager(
        config=cfg,
        out_path=tmp_path,
        base_raster=inputs.base_raster,
        catalog=catalog,
        data_dir=tmp_path / "cache",
    )


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_the_cache_serves_the_layer_it_was_asked_for_and_no_other(
    backend_factory, fetch, tmp_path: Path
) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    backend_factory.return_value = WhiteboxStubBackend()
    fetch.return_value = _reaches(["permanent"])
    catalog = DataCatalogDuckDB(db_path=None)
    reaches = "sa:TronconHydrographique_FXX_Topage2026"
    rivers = "sa:CoursEau_FXX_Topage2026"

    _cached_manager(tmp_path, catalog, reaches).load()
    _cached_manager(tmp_path, catalog, reaches).load()
    assert fetch.call_count == 1, "the same layer over the same box is served from disk"

    _cached_manager(tmp_path, catalog, rivers).load()
    assert fetch.call_count == 2, "another layer over the same box is not the cached one"
    assert [call.args[0] for call in fetch.call_args_list] == [reaches, rivers]
    names = sorted(path.name for path in (tmp_path / "cache").glob("*.gpkg"))
    assert all(name.startswith("bdtopage_") for name in names), "the gitignore prefix holds"


@patch("hydromodpy.data.variables.hydrography.apis.bdtopage.fetch_projected")
@patch(_BACKEND)
def test_an_entry_recorded_before_the_question_was_is_still_served(
    backend_factory, fetch, tmp_path: Path
) -> None:
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    backend_factory.return_value = WhiteboxStubBackend()
    catalog = DataCatalogDuckDB(db_path=None)
    old = tmp_path / "cache" / "bdtopage_old.gpkg"
    old.parent.mkdir(parents=True)
    _reaches(["permanent"]).to_crs("EPSG:4326").to_file(old, driver="GPKG")
    catalog.register(
        variable="hydrography",
        source="bdtopage",
        file_path=str(old),
        bbox=(0.0, 0.0, 1e7, 1e7),
        crs="EPSG:4326",
        is_custom=False,
    )

    _cached_manager(tmp_path, catalog, "sa:TronconHydrographique_FXX_Topage2026").load()

    assert fetch.call_count == 0
