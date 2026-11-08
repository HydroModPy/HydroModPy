"""The value types of the data-source port, one test per behaviour.

What the port refuses before any provider is contacted: an extent that says no
CRS, a period that ends before it starts, a request that names stations twice,
a result whose payload contradicts its kind. And the two rules this phase added:
a request that selects nothing is accepted by the type and refused by
:func:`require_selectors` unless the source declares ``selectors = ()``, and a
``files`` payload carries :class:`FileRecord`, sealed by digest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pyproj = pytest.importorskip("pyproj")

from hydromodpy.core.exceptions import DataCapabilityError, DataProductError, DataRequestError
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

pytest.importorskip("shapely")

# A basin-sized box over eastern Brittany, in the CRS no source of this suite
# declares: every adapter has to convert it, one of them by 300 kilometers.
CALLER_EXTENT = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 3, 31))


class _SelectingSource:
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


class _NeedingPeriodSource(_SelectingSource):
    """The minimum a source with a time axis is asked for."""

    source_id = "period-double"
    period_need = "required"


class _OptionalPeriodSource(_SelectingSource):
    """The minimum a source with an optional time axis declares."""

    source_id = "optional-double"
    period_need = "optional"


class _SelectingNothingSource(_SelectingSource):
    """The minimum a source with no selector declares, the computed constants."""

    source_id = "nothing-double"
    selectors: tuple[Selector, ...] = ()


# --------------------------------------------------------------------------- #
# Extent
# --------------------------------------------------------------------------- #


def test_an_extent_without_a_crs_is_refused() -> None:
    with pytest.raises(DataRequestError, match="carries the CRS"):
        Extent(xmin=0.0, ymin=0.0, xmax=1.0, ymax=1.0, crs="  ")


@pytest.mark.parametrize(
    "bounds",
    [(1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)],
    ids=["x-inverted", "y-inverted", "x-degenerate"],
)
def test_an_empty_or_inverted_extent_is_refused(bounds: tuple[float, ...]) -> None:
    with pytest.raises(DataRequestError, match="empty or inverted"):
        Extent(xmin=bounds[0], ymin=bounds[1], xmax=bounds[2], ymax=bounds[3], crs="EPSG:4326")


def test_an_extent_with_no_image_in_the_target_crs_is_refused() -> None:
    """The far side of the globe has no image in an orthographic projection.

    Measured rather than assumed: pyproj happily extrapolates a conic such as
    Lambert-93 well past its area of use -- a box off New Zealand comes back at
    x = 17 435 929 m with every bound finite -- so a guard tested on that case
    would have been dead code. An orthographic projection centered on the basin
    is the one that really returns ``inf``, and it is what proves the branch is
    reachable at all.
    """
    far_side = Extent(xmin=100.0, ymin=-40.0, xmax=140.0, ymax=-20.0, crs="EPSG:4326")
    with pytest.raises(DataRequestError, match="no image in"):
        far_side.to_crs("+proj=ortho +lat_0=48 +lon_0=-2 +datum=WGS84")


def test_a_conversion_that_wraps_the_antimeridian_is_refused_as_inverted() -> None:
    """A nonsense box does not come back as a plausible one.

    Lambert-93 meters a thousand times past the planet convert to a longitude
    range that wraps: ``(163.6, -90.0, -145.5, -90.0)``. Nothing in those four
    numbers is non-finite, so the finiteness guard does not see it -- what
    refuses it is :class:`Extent` itself, on the invariant every extent holds.
    """
    nonsense = Extent(xmin=1e12, ymin=1e12, xmax=2e12, ymax=2e12, crs="EPSG:2154")
    with pytest.raises(DataRequestError, match="empty or inverted"):
        nonsense.to_crs("EPSG:4326")


def test_a_conversion_to_the_same_crs_reuses_the_exact_floats() -> None:
    """No round trip through a transformer when there is nothing to convert."""
    direct = CALLER_EXTENT.to_crs("EPSG:4326")
    assert direct is CALLER_EXTENT, "the same spelling is the same extent, not a copy"
    respelled = CALLER_EXTENT.to_crs("epsg:4326")
    assert respelled is not CALLER_EXTENT
    assert respelled.bbox == CALLER_EXTENT.bbox
    assert respelled.crs == "epsg:4326", "the result carries the CRS as it was asked for"


def test_densifying_the_edges_is_not_the_same_as_transforming_the_corners() -> None:
    """Why :meth:`Extent.to_crs` uses ``transform_bounds``, with the number.

    Over the French mainland envelope the conic parallels of Lambert-93 bow
    south between the corners, so the image of the box is not the box of the
    images: a four-corner transform puts the southern edge 26 163 m too far
    north. At basin scale the two agree to the meter, which is why the defect
    would not have shown up in any example project of this tree.
    """
    france = Extent(xmin=-5.0, ymin=41.0, xmax=10.0, ymax=51.5, crs="EPSG:4326")
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    corners = [
        transformer.transform(x, y)
        for x, y in ((-5.0, 41.0), (10.0, 41.0), (-5.0, 51.5), (10.0, 51.5))
    ]
    corner_ymin = min(point[1] for point in corners)
    densified = france.to_crs("EPSG:2154")
    assert corner_ymin - densified.ymin == pytest.approx(26162.6, abs=1.0)

    basin = CALLER_EXTENT.to_crs("EPSG:2154")
    basin_corners = [
        transformer.transform(x, y)
        for x, y in (
            (CALLER_EXTENT.xmin, CALLER_EXTENT.ymin),
            (CALLER_EXTENT.xmax, CALLER_EXTENT.ymin),
            (CALLER_EXTENT.xmin, CALLER_EXTENT.ymax),
            (CALLER_EXTENT.xmax, CALLER_EXTENT.ymax),
        )
    ]
    assert min(point[1] for point in basin_corners) - basin.ymin == pytest.approx(0.0, abs=1.0)


def test_a_numpy_scalar_is_a_coordinate() -> None:
    """An extent built straight off a geopandas ``total_bounds`` is legitimate.

    ``numpy.int64`` and ``numpy.float32`` are not subclasses of ``int`` or
    ``float`` in CPython -- only ``numpy.float64`` is -- so an ``isinstance``
    whitelist refused a real number from the one place callers get bounds.
    """
    numpy = pytest.importorskip("numpy")

    bounds = numpy.array([317000, 6780000, 354000, 6826000], dtype=numpy.int64)
    extent = Extent(xmin=bounds[0], ymin=bounds[1], xmax=bounds[2], ymax=bounds[3], crs="EPSG:2154")
    assert extent.bbox == (317000.0, 6780000.0, 354000.0, 6826000.0)
    assert all(isinstance(value, float) for value in extent.bbox)

    as_float32 = Extent(
        xmin=numpy.float32(-2.0),
        ymin=numpy.float32(48.0),
        xmax=numpy.float32(-1.5),
        ymax=numpy.float32(48.4),
        crs="EPSG:4326",
    )
    assert as_float32.crs == "EPSG:4326"

    with pytest.raises(DataRequestError, match="not a number"):
        Extent(xmin="0", ymin=0.0, xmax=1.0, ymax=1.0, crs="EPSG:4326")  # type: ignore[arg-type]
    with pytest.raises(DataRequestError, match="boolean"):
        Extent(xmin=False, ymin=0.0, xmax=1.0, ymax=1.0, crs="EPSG:4326")  # type: ignore[arg-type]
    with pytest.raises(DataRequestError, match="not finite"):
        Extent(xmin=float("nan"), ymin=0.0, xmax=1.0, ymax=1.0, crs="EPSG:4326")


# --------------------------------------------------------------------------- #
# Period
# --------------------------------------------------------------------------- #


def test_a_period_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(DataRequestError, match="ends"):
        Period(start=datetime(2020, 2, 1), end=datetime(2020, 1, 1))


def test_a_period_mixing_an_aware_bound_with_a_naive_one_is_refused() -> None:
    with pytest.raises(DataRequestError, match="aware"):
        Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1, tzinfo=UTC))


# --------------------------------------------------------------------------- #
# FetchRequest, and the selectors rule
# --------------------------------------------------------------------------- #


def test_an_empty_request_is_accepted_by_the_type() -> None:
    """A file content and a computed constant are asked exactly nothing."""
    request = FetchRequest(out_dir=Path("."))
    assert request.selectors == ()


def test_a_request_that_selects_nothing_is_refused_for_a_source_that_selects(
    tmp_path: Path,
) -> None:
    with pytest.raises(DataRequestError, match="selects nothing"):
        require_selectors(_SelectingSource(), FetchRequest(out_dir=tmp_path))


def test_a_request_that_selects_nothing_is_served_by_a_source_that_selects_nothing(
    tmp_path: Path,
) -> None:
    """The declaration says the truth: ``selectors = ()`` answers the empty request."""
    require_selectors(_SelectingNothingSource(), FetchRequest(out_dir=tmp_path))
    require_selectors(_SelectingNothingSource(), FetchRequest(out_dir=tmp_path, period=PERIOD))


def test_a_selector_the_source_does_not_declare_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataCapabilityError, match="does not select by"):
        require_selectors(_SelectingSource(), FetchRequest(out_dir=tmp_path, station_ids=("BSS1",)))


def test_no_source_answers_two_selectors_at_once(tmp_path: Path) -> None:
    """The silent one: the station list wins and the extent is dropped.

    Measured in ``piezometry/apis/hubeau.py``: ``if station_ids: ... elif
    bbox:``. A caller that passed both would get exactly what it would have got
    by passing the ids alone, and nothing in the result would say the box was
    ignored. Refused for every source until a provider can intersect them.
    """

    class _TwoSelectorsSource(_SelectingSource):
        selectors: tuple[Selector, ...] = ("extent", "station_ids")

    request = FetchRequest(out_dir=tmp_path, extent=CALLER_EXTENT, station_ids=("BSS000XXXX",))
    with pytest.raises(DataCapabilityError, match="at once"):
        require_selectors(_TwoSelectorsSource(), request)


def test_a_single_string_of_station_ids_is_refused(tmp_path: Path) -> None:
    """``station_ids="BSS1"`` would be read one character per station."""
    with pytest.raises(DataRequestError, match="single string"):
        FetchRequest(out_dir=tmp_path, station_ids="BSS1")  # type: ignore[arg-type]


def test_repeated_station_ids_are_refused(tmp_path: Path) -> None:
    with pytest.raises(DataRequestError, match="repeat"):
        FetchRequest(out_dir=tmp_path, station_ids=("A", "B", "A"))


def test_a_bare_tuple_is_not_an_extent(tmp_path: Path) -> None:
    with pytest.raises(DataRequestError, match="which CRS"):
        FetchRequest(out_dir=tmp_path, extent=(-2.0, 48.0, -1.5, 48.4))  # type: ignore[arg-type]


def test_a_request_needs_somewhere_to_write(tmp_path: Path) -> None:
    with pytest.raises(DataRequestError):
        FetchRequest(out_dir=42)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# FetchResult
# --------------------------------------------------------------------------- #


def test_an_empty_result_is_not_an_error() -> None:
    """A box over the sea holds no gauging station, and that is an answer."""
    empty = FetchResult(source_id="x", kind="points", variables=("v",))
    assert empty.is_empty


def test_a_result_that_names_no_variable_is_refused() -> None:
    with pytest.raises(DataProductError, match="names no variable"):
        FetchResult(source_id="x", kind="files", variables=(), files=())


def test_a_result_carrying_a_payload_its_kind_does_not_name_is_refused() -> None:
    sealed = FileRecord.of(Path(__file__), state="raw", origin="test")
    with pytest.raises(DataProductError, match="declares kind"):
        FetchResult(source_id="x", kind="points", variables=("v",), files=(sealed,))


def test_a_result_whose_files_are_not_sealed_records_is_refused() -> None:
    """A bare path says nothing about the bytes it names, so it is refused by name."""
    with pytest.raises(DataProductError, match="FileRecord"):
        FetchResult(source_id="x", kind="files", variables=("v",), files=(Path("a.tif"),))


def test_a_record_the_source_does_not_declare_is_refused() -> None:
    with pytest.raises(DataProductError, match="does not name"):
        require_declared_variables(_SelectingSource(), ("other",))


def test_a_period_refused_by_a_source_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataCapabilityError, match="no time axis"):
        require_period(_SelectingSource(), FetchRequest(out_dir=tmp_path, period=PERIOD))


def test_a_period_a_source_needs_is_demanded(tmp_path: Path) -> None:
    with pytest.raises(DataRequestError, match="needs a period"):
        require_period(_NeedingPeriodSource(), FetchRequest(out_dir=tmp_path))


def test_an_optional_period_is_accepted_with_or_without_period(tmp_path: Path) -> None:
    src = _OptionalPeriodSource()
    assert require_period(src, FetchRequest(out_dir=tmp_path, period=PERIOD)) == PERIOD
    assert require_period(src, FetchRequest(out_dir=tmp_path, period=None)) is None


# --------------------------------------------------------------------------- #
# FileRecord
# --------------------------------------------------------------------------- #


def test_of_hashes_the_bytes_it_read(tmp_path: Path) -> None:
    path = tmp_path / "tiles.tif"
    path.write_bytes(b"\x89DEM")
    record = FileRecord.of(path, state="raw", nodata=-9999.0, origin="test")
    import hashlib  # not the port's digest: the check is against the primitive

    assert record.sha256 == hashlib.sha256(b"\x89DEM").hexdigest()
    assert record.state == "raw"
    assert record.nodata == -9999.0
    assert record.origin == "test"
    assert record.path == path


def test_of_reads_the_file_without_writing_it(tmp_path: Path) -> None:
    path = tmp_path / "tiles.tif"
    path.write_bytes(b"abc")
    first = FileRecord.of(path, state="conditioned", origin="test")
    path.write_bytes(b"abc")
    second = FileRecord.of(path, state="conditioned", origin="test")
    assert first == second
    assert hash(first) == hash(second)
    assert repr(first).startswith("FileRecord(path=")


def test_a_state_out_of_the_vocabulary_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "tiles.tif"
    path.write_bytes(b"abc")
    with pytest.raises(DataProductError, match="state"):
        FileRecord.of(path, state="guessing", origin="test")  # type: ignore[arg-type]
    with pytest.raises(DataProductError, match="state"):
        FileRecord(path, "0" * 64, state=3.0, origin="test")  # type: ignore[arg-type]


def test_a_digest_that_is_not_a_sha256_is_refused() -> None:
    with pytest.raises(DataProductError, match="sha256"):
        FileRecord(Path("a.tif"), "not-a-digest", origin="test")
    with pytest.raises(DataProductError, match="origin"):
        FileRecord(Path("a.tif"), "0" * 64, origin="  ")


def test_a_file_that_cannot_be_read_is_refused_naming_it(tmp_path: Path) -> None:
    missing = tmp_path / "not-there.tif"
    with pytest.raises(DataProductError, match="not-there.tif"):
        FileRecord.of(missing, origin="test")


# --------------------------------------------------------------------------- #
# shipped_hosts
# --------------------------------------------------------------------------- #


def test_shipped_hosts_reads_the_licence_table() -> None:
    from hydromodpy.schema.sources import source_entry

    hosts = shipped_hosts("bdtopage")
    assert hosts == tuple(source_entry("bdtopage").hosts)
    assert all("/" not in host for host in hosts)


def test_an_id_without_a_licence_entry_is_refused() -> None:
    with pytest.raises(DataRequestError, match="licence entry"):
        shipped_hosts("not-a-source-of-this-build")
