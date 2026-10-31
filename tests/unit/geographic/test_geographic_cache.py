"""The geographic cache: what a tree must hold to be reused, and what its fingerprint reads."""

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.spatial.geographic.core.ground_corrections import GROUND_FILENAME
from hydromodpy.spatial.geographic.geographic_cache import (
    DESCRIPTION_FILENAME,
    geographic_artifact_paths,
    geographic_cache_fingerprint,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from tests._helpers.geographic_cases import (
    BENCH_RIVER,
    cached_tree,
    capped_breach_flow_products,
    capped_breach_report,
    load_cached,
    outlet_config,
    outlet_document,
    touch_artifact,
    write_features,
)
from tests._helpers.geotiffs import write_geotiff

FILL_FINGERPRINT_WITHOUT_THE_BURN = (
    "e98e054d5ea4b7e52eb24e122f7a85384b6e2338528dedb35b527b8708490ffb"
)
"""The fingerprint of 79fe734ea, before the capped breach existed, minus the retired sections.

Removing ``[geographic.enforce_streams]``, then ``[geographic.dam_carve]`` and the ramp and
capture keys of ``[geographic.enforce_lakes]``, took them and their path signatures out of
the payload, so every cached tree was rebuilt once. Putting the burn back (defaults, no path)
gives back ``ab83e008ba427355b3c68345745088b13a0337e006164879216e8d7571f626b3``, the value a
clean export of 79fe734ea computes, and putting the dam and lake keys back as well gives back
``7b2ef36222c1439414f36aa3464a7c51e18ed18111f14601fb4112f79344a363``. The DEM is a bare
file name that does not exist, the one input that hashes alike on every OS.
"""


def _fingerprint(**sections) -> str:
    return geographic_cache_fingerprint(outlet_document(**sections))


def test_a_complete_matching_tree_is_a_hit_and_one_that_differs_or_cannot_be_described_a_miss(
    tmp_path: Path,
) -> None:
    """A restored domain says which rule drew its margin, as a fresh one does."""
    buffer = {
        "buffer_rule": "area_percent",
        "buffer_declared": "10%",
        "buffer_area_increase": 0.106,
    }
    config, paths = cached_tree(tmp_path, domain={"buffer_distance_m": 150.0, **buffer})
    cached = load_cached(config, paths)
    assert cached is not None
    assert cached.catchment_area_km2 == 12.0
    assert cached.flow_products.direc.endswith("dem_direc.tif")
    domain = cached.domain_products
    assert domain.buffer_distance_m == 150.0
    assert {key: getattr(domain, key) for key in buffer} == buffer
    changed = config.model_copy(
        update={"catchment": config.catchment.model_copy(update={"x_outlet": 99.0})}
    )
    assert geographic_cache_fingerprint(config) != geographic_cache_fingerprint(changed)
    assert load_cached(changed, paths) is None
    # An accumulation that declares no nodata cannot describe the flow stack:
    # a miss that rebuilds, never an exception that aborts the run.
    accumulation = Path(paths.correcflow_path) / "dem_acc.tif"
    write_geotiff(accumulation, np.zeros((1, 1), dtype="float32"), nodata=None)
    assert load_cached(config, paths) is None


def test_a_tree_whose_polygon_lost_its_prj_is_a_miss_that_rebuilds(tmp_path: Path) -> None:
    config, paths = cached_tree(tmp_path)
    assert load_cached(config, paths) is not None
    Path(paths.watershed_shp).with_suffix(".prj").unlink()
    assert load_cached(config, paths) is None


@pytest.mark.parametrize(
    ("notch", "ground_written", "hit"),
    [(True, True, True), (True, False, False), (False, False, True)],
    ids=["notched-ground-is-a-hit", "tree-older-than-the-ground-is-a-miss", "no-correction"],
)
def test_the_model_top_of_a_hit_is_the_ground_so_a_tree_that_lacks_it_is_a_miss(
    tmp_path: Path, notch: bool, ground_written: bool, hit: bool
) -> None:
    sections = {}
    if notch:
        line = write_features(tmp_path / "crossings.gpkg", [LineString([(0, 0), (1, 1)])])
        sections = {"crossings": {"enabled": True, "path": line}, "river_network": BENCH_RIVER}
    config, paths = cached_tree(tmp_path, **sections)
    if ground_written:
        touch_artifact(Path(paths.correcflow_path) / GROUND_FILENAME)
    assert (load_cached(config, paths) is not None) is hit


def test_a_capped_breach_tree_keeps_its_report_and_a_hit_reads_it_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config, paths = cached_tree(
        tmp_path, dem_correc_type="capped_breach", flow_products=capped_breach_flow_products()
    )
    with caplog.at_level(logging.INFO):
        cached = load_cached(config, paths)
    assert cached is not None
    assert (
        cached.flow_products.accumulation.directions.conditioned_dem.breach_report
        == capped_breach_report()
    )
    assert any("realised max lowering 0.560 m" in record.getMessage() for record in caplog.records)


def test_a_fill_config_fingerprints_as_before_the_capped_breach_existed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="no_such_dem.tif", dem_correc_type="fill"
    )
    assert geographic_cache_fingerprint(config) == FILL_FINGERPRINT_WITHOUT_THE_BURN


_LIMITS = {"max_depth": 0.8, "max_distance": 100.0}


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ({"dem_correc_type": "breach"}, {"dem_correc_type": "fill"}, False),
        (
            {"dem_correc_type": "capped_breach"},
            {"dem_correc_type": "capped_breach", "capped_breach": _LIMITS},
            False,
        ),
        (
            {"river_network": BENCH_RIVER, "crossings": {"max_depth": 2.0}},
            {"river_network": BENCH_RIVER, "crossings": {}},
            True,
        ),
        (
            {"river_network": BENCH_RIVER, "crossings": {"enabled": True, "max_depth": 2.0}},
            {"river_network": BENCH_RIVER, "crossings": {"enabled": True, "max_depth": 2.5}},
            False,
        ),
        (
            {"river_network": BENCH_RIVER, "crossings": {}},
            {"river_network": BENCH_RIVER, "crossings": {"enabled": True}},
            False,
        ),
        (
            {"river_network": BENCH_RIVER},
            {
                "river_network": BENCH_RIVER,
                "bed_regularization": {"enabled": False, "min_slope": 1e-3},
            },
            True,
        ),
        (
            {"river_network": BENCH_RIVER},
            {"river_network": BENCH_RIVER, "bed_regularization": {"enabled": True}},
            False,
        ),
    ],
    ids=[
        "the-breach-is-not-the-fill",
        "the-capped-breach-limits-sign-the-cache",
        "a-limit-of-a-notch-that-is-off-keeps-the-cache",
        "a-limit-of-a-notch-that-is-on-does-not",
        "switching-the-notch-on",
        "a-bed-regularisation-that-is-off-keeps-the-cache",
        "a-bed-regularisation-that-is-on-does-not",
    ],
)
def test_only_what_a_rebuild_reads_signs_the_cache(first, second, same) -> None:
    assert (_fingerprint(**first) == _fingerprint(**second)) is same


def test_editing_the_structures_file_in_place_changes_the_fingerprint(tmp_path) -> None:
    structures = tmp_path / "crossings.gpkg"
    structures.write_bytes(b"one")
    config = outlet_document(
        river_network=BENCH_RIVER, crossings={"enabled": True, "path": structures}
    )
    before = geographic_cache_fingerprint(config)
    structures.write_bytes(b"two, longer")
    assert geographic_cache_fingerprint(config) != before


def test_a_runtime_declares_every_file_it_still_holds_once_and_in_order(tmp_path) -> None:
    geographic_path, correcflow = tmp_path / "geographic", tmp_path / "correcflow"
    watershed = write_features(geographic_path / "watershed.shp", [LineString([(0, 0), (1, 1)])])
    for path in (
        geographic_path / DESCRIPTION_FILENAME,
        correcflow / "dem_acc_cells.tif",
        correcflow / "dem_fill.tif",
    ):
        touch_artifact(path)
    runtime = SimpleNamespace(
        geographic_path=str(geographic_path),
        correcflow_path=str(correcflow),
        watershed_shp=str(watershed),
        box_buff=str(watershed),
        watershed_dem=str(tmp_path / "never_written.tif"),
        watershed_contour_shp="",
        _flow_products=SimpleNamespace(correc=str(correcflow / "dem_fill.tif")),
    )
    found = geographic_artifact_paths(runtime)
    sidecars = {p.suffix for p in found if p.stem == "watershed"}
    assert {".shp", ".shx", ".dbf", ".prj"} <= sidecars
    assert geographic_path / DESCRIPTION_FILENAME in found
    assert correcflow / "dem_acc_cells.tif" in found
    assert correcflow / "dem_fill.tif" in found
    assert tmp_path / "never_written.tif" not in found
    assert list(found) == sorted(set(found))
    assert geographic_artifact_paths(None) == ()


def test_the_geographic_cache_sees_the_cell_size(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", np.ones((10, 10)), cell=100.0)

    def config(**catchment):
        return outlet_config(dem, x=450.0, y=550.0, catchment=catchment)

    assert geographic_cache_fingerprint(config()) != geographic_cache_fingerprint(
        config(dem_resolution="300 m")
    )
