"""Value types of the data-source port, and what they refuse before a provider is contacted.

An extent (degrees or m, with its CRS) that is empty or says no CRS, a period that ends
before it starts, a request that names stations twice, a result whose payload
contradicts its kind, and a request that selects nothing for a source that selects.
A ``files`` payload carries sealed :class:`FileRecord`, and the request carries the
:class:`Bounds` of the call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

pyproj = pytest.importorskip("pyproj")
pytest.importorskip("shapely")

from hydromodpy.core.exceptions import DataCapabilityError, DataProductError, DataRequestError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.contracts.file_record import FileRecord
from hydromodpy.data.source.port import (
    Extent,
    FetchRequest,
    FetchResult,
    Period,
    Selector,
    require_declared_variables,
    require_period,
    require_selectors,
    shipped_hosts,
)

# A basin-sized box over eastern Brittany, in a CRS no source of this suite
# declares: every adapter has to convert it, one of them by 300 kilometers.
CALLER_EXTENT = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")


class SelectingSource:
    """The minimum a source that selects by extent is asked for."""

    source_id = "selecting-double"
    section = "double"
    payload_kind = "features"
    extent_crs = "EPSG:4326"
    selectors: tuple[Selector, ...] = ("extent",)
    period_need = "refused"
    writes_out_dir = False

    def __init__(self) -> None:
        self.variables: tuple[str, ...] = ("double",)
        self.hosts: tuple[str, ...] = ()

    def fetch(self, request: FetchRequest) -> FetchResult:  # pragma: no cover - never called
        raise AssertionError("these tests read the refusals, not the answers")


class NeedingPeriodSource(SelectingSource):
    source_id = "period-double"
    period_need = "required"


class TwoSelectorsSource(SelectingSource):
    selectors: tuple[Selector, ...] = ("extent", "station_ids")


SEALED = FileRecord.of(Path(__file__), state="raw", origin="test")

EXTENT_REFUSALS = [
    pytest.param({"crs": "  "}, "carries the CRS", id="no crs"),
    pytest.param({"xmin": 1.0, "xmax": 0.0}, "empty or inverted", id="x inverted"),
    pytest.param({"ymin": 1.0, "ymax": 0.0}, "empty or inverted", id="y inverted"),
    pytest.param({"xmin": 0.0, "xmax": 0.0}, "empty or inverted", id="x degenerate"),
    pytest.param({"xmin": "0"}, "not a number", id="string coordinate"),
    pytest.param({"xmin": False}, "boolean", id="boolean coordinate"),
    pytest.param({"xmin": float("nan")}, "not finite", id="nan coordinate"),
]


@pytest.mark.parametrize(("changes", "message"), EXTENT_REFUSALS)
def test_extent_refusals(changes, message):
    unit_box = {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0, "crs": "EPSG:4326"}

    with pytest.raises(DataRequestError, match=message):
        Extent(**(unit_box | changes))


def test_extent_with_no_image_in_the_target_crs():
    # The far side of the globe has no image in an orthographic projection. A
    # conic such as Lambert-93 extrapolates far past its area of use with finite
    # bounds, so only an orthographic projection really returns inf.
    far_side = Extent(xmin=100.0, ymin=-40.0, xmax=140.0, ymax=-20.0, crs="EPSG:4326")

    with pytest.raises(DataRequestError, match="no image in"):
        far_side.to_crs("+proj=ortho +lat_0=48 +lon_0=-2 +datum=WGS84")


def test_conversion_wrapping_the_antimeridian_is_refused():
    # Lambert-93 meters a thousand times past the planet convert to a longitude
    # range that wraps. Every number is finite, so Extent itself refuses it.
    nonsense = Extent(xmin=1e12, ymin=1e12, xmax=2e12, ymax=2e12, crs="EPSG:2154")

    with pytest.raises(DataRequestError, match="empty or inverted"):
        nonsense.to_crs("EPSG:4326")


def test_conversion_to_the_same_crs_reuses_the_extent():
    assert CALLER_EXTENT.to_crs("EPSG:4326") is CALLER_EXTENT

    respelled = CALLER_EXTENT.to_crs("epsg:4326")

    assert respelled is not CALLER_EXTENT
    assert respelled.bbox == CALLER_EXTENT.bbox
    assert respelled.crs == "epsg:4326"


def test_conversion_densifies_the_edges():
    # Over the French mainland the Lambert-93 parallels bow south between the
    # corners, so a four-corner transform puts the southern edge 26 163 m too far
    # north. At basin scale the two agree to the meter.
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

    def southern_gap_m(extent: Extent) -> float:
        corners = [
            transformer.transform(x, y)
            for x in (extent.xmin, extent.xmax)
            for y in (extent.ymin, extent.ymax)
        ]
        return min(point[1] for point in corners) - extent.to_crs("EPSG:2154").ymin

    france = Extent(xmin=-5.0, ymin=41.0, xmax=10.0, ymax=51.5, crs="EPSG:4326")

    np.testing.assert_allclose(southern_gap_m(france), 26162.6, atol=1.0)
    np.testing.assert_allclose(southern_gap_m(CALLER_EXTENT), 0.0, atol=1.0)


def test_numpy_scalars_are_coordinates():
    # numpy.int64 and numpy.float32 are not subclasses of int or float, and a
    # geopandas total_bounds hands them out.
    bounds = np.array([317000, 6780000, 354000, 6826000], dtype=np.int64)
    extent = Extent(xmin=bounds[0], ymin=bounds[1], xmax=bounds[2], ymax=bounds[3], crs="EPSG:2154")

    assert extent.bbox == (317000.0, 6780000.0, 354000.0, 6826000.0)
    assert all(isinstance(value, float) for value in extent.bbox)

    as_float32 = Extent(
        xmin=np.float32(-2.0),
        ymin=np.float32(48.0),
        xmax=np.float32(-1.5),
        ymax=np.float32(48.4),
        crs="EPSG:4326",
    )
    assert as_float32.crs == "EPSG:4326"


PERIOD_REFUSALS = [
    pytest.param(datetime(2020, 2, 1), datetime(2020, 1, 1), "ends", id="ends before it starts"),
    pytest.param(
        datetime(2020, 1, 1), datetime(2020, 2, 1, tzinfo=UTC), "aware", id="aware and naive"
    ),
]


@pytest.mark.parametrize(("start", "end", "message"), PERIOD_REFUSALS)
def test_period_refusals(start, end, message):
    with pytest.raises(DataRequestError, match=message):
        Period(start=start, end=end)


# What a rule refuses: (rule, source, request fields besides out_dir, error, message).
SOURCE_RULES = [
    pytest.param(
        require_selectors,
        SelectingSource(),
        {},
        DataRequestError,
        "selects nothing",
        id="selects nothing",
    ),
    # Measured in piezometry/apis/hubeau.py: with both, the station list wins and
    # the extent is dropped without a word, so two selectors are refused for all.
    pytest.param(
        require_selectors,
        TwoSelectorsSource(),
        {"extent": CALLER_EXTENT, "station_ids": ("BSS000XXXX",)},
        DataCapabilityError,
        "at once",
        id="two selectors",
    ),
    pytest.param(
        require_period,
        NeedingPeriodSource(),
        {},
        DataRequestError,
        "needs a period",
        id="period needed",
    ),
]


@pytest.mark.parametrize(("rule", "source", "fields", "error", "message"), SOURCE_RULES)
def test_source_rules(tmp_path, rule, source, fields, error, message):
    with pytest.raises(error, match=message):
        rule(source, FetchRequest(out_dir=tmp_path, **fields))


REQUEST_REFUSALS = [
    # station_ids="BSS1" would be read one character per station.
    pytest.param({"station_ids": "BSS1"}, "single string", id="string of station ids"),
    pytest.param({"station_ids": ("A", "B", "A")}, "repeat", id="repeated station ids"),
    pytest.param({"extent": (-2.0, 48.0, -1.5, 48.4)}, "which CRS", id="bare tuple extent"),
    pytest.param({"out_dir": 42}, "", id="no folder to write"),
    pytest.param({"bounds": "api.geosas.fr"}, "is not a Bounds", id="bounds of another form"),
]


@pytest.mark.parametrize(("fields", "message"), REQUEST_REFUSALS)
def test_request_refusals(tmp_path, fields, message):
    with pytest.raises(DataRequestError, match=message):
        FetchRequest(**({"out_dir": tmp_path} | fields))


def test_request_carries_the_default_bounds(tmp_path):
    assert FetchRequest(out_dir=tmp_path).bounds == Bounds()


def test_empty_result_is_an_answer():
    # A box over the sea holds no gauging station.
    assert FetchResult(source_id="x", kind="points", variables=("v",)).is_empty


RESULT_REFUSALS = [
    pytest.param(
        {"kind": "files", "variables": (), "files": ()}, "names no variable", id="no variable"
    ),
    pytest.param(
        {"kind": "points", "files": (SEALED,)}, "declares kind", id="payload of another kind"
    ),
    # A bare path says nothing about the bytes it names.
    pytest.param({"kind": "files", "files": (Path("a.tif"),)}, "FileRecord", id="unsealed file"),
]


@pytest.mark.parametrize(("fields", "message"), RESULT_REFUSALS)
def test_result_refusals(fields, message):
    with pytest.raises(DataProductError, match=message):
        FetchResult(**({"source_id": "x", "variables": ("v",)} | fields))


def test_undeclared_variable_is_refused():
    with pytest.raises(DataProductError, match="does not name"):
        require_declared_variables(SelectingSource(), ("other",))


def test_file_record_is_read_not_written(tmp_path):
    path = tmp_path / "tiles.tif"
    path.write_bytes(b"abc")
    first = FileRecord.of(path, state="conditioned", origin="test")
    path.write_bytes(b"abc")
    second = FileRecord.of(path, state="conditioned", origin="test")

    assert first == second
    assert hash(first) == hash(second)
    assert repr(first).startswith("FileRecord(path=")


def test_file_record_refusals(tmp_path):
    path = tmp_path / "tiles.tif"
    path.write_bytes(b"abc")

    with pytest.raises(DataProductError, match="state"):
        FileRecord.of(path, state="guessing", origin="test")
    with pytest.raises(DataProductError, match="state"):
        FileRecord(path, "0" * 64, state=3.0, origin="test")
    with pytest.raises(DataProductError, match="sha256"):
        FileRecord(Path("a.tif"), "not-a-digest", origin="test")
    with pytest.raises(DataProductError, match="origin"):
        FileRecord(Path("a.tif"), "0" * 64, origin="  ")
    with pytest.raises(DataProductError, match="not-there.tif"):
        FileRecord.of(tmp_path / "not-there.tif", origin="test")


def test_id_without_a_licence_entry_is_refused():
    with pytest.raises(DataRequestError, match="licence entry"):
        shipped_hosts("not-a-source-of-this-build")
