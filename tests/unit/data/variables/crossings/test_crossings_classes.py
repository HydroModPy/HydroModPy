"""The two crossings sources of the port, on a stubbed provider.

The contract suite (``tests/ports/test_data_source.py``) checks the
declarations against the port on every source; this table checks what these two
classes do that only they do: the GeoPackage they write under the request's
directory, its name, the file record it returns, and what becomes of a box that
holds no crossing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pytest

pyproj = pytest.importorskip("pyproj")

from hydromodpy.core.exceptions import DataCapabilityError  # noqa: E402
from hydromodpy.data.source.port import (  # noqa: E402
    Extent,
    FetchRequest,
    Period,
    require_period,
)
from hydromodpy.data.variables.crossings import records  # noqa: E402
from hydromodpy.data.variables.crossings.apis import bdtopo, roe  # noqa: E402
from hydromodpy.data.variables.crossings.apis.bdtopo import BdTopoCrossings  # noqa: E402
from hydromodpy.data.variables.crossings.apis.roe import RoeCrossings  # noqa: E402
from hydromodpy.data.variables.crossings.variable import cache_file_name  # noqa: E402

BOX = (340000.0, 6800000.0, 350000.0, 6810000.0)
EXTENT = Extent(xmin=BOX[0], ymin=BOX[1], xmax=BOX[2], ymax=BOX[3], crs="EPSG:2154")
FOREIGN = Extent(xmin=-2.0, ymin=48.0, xmax=-1.5, ymax=48.4, crs="EPSG:4326")
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1))

CLASSES = [
    pytest.param(BdTopoCrossings, bdtopo, id="bdtopo"),
    pytest.param(RoeCrossings, roe, id="roe"),
]


def _sample(source: str = "", drop: float = float("nan")) -> gpd.GeoDataFrame:
    """One page of records, in the fixed columns every crossings page is written in."""
    from shapely.geometry import LineString

    return records.build(
        [LineString([(0.0, 0.0), (1.0, 1.0)]), LineString([(2.0, 0.0), (3.0, 1.0)])],
        kind=["road", "weir"],
        source=source,
        name=["", "seuil"],
        drop_m=[drop, drop],
        crs="EPSG:2154",
    )


def _expected_box(extent: Extent) -> tuple[float, float, float, float]:
    """Reproject with pyproj directly, so the port is not its own reference."""
    transformer = pyproj.Transformer.from_crs(extent.crs, "EPSG:2154", always_xy=True)
    return tuple(transformer.transform_bounds(*extent.bbox))  # type: ignore[return-value]


def _stub(monkeypatch: pytest.MonkeyPatch, module, pages) -> list:
    """Replace one provider, and record the boxes and page sizes it is asked."""
    asked: list = []

    def fetch(*, bbox, page_size, client):
        asked.append((bbox, page_size))
        yield from pages()

    monkeypatch.setattr(module, "fetch_pages", fetch)
    return asked


@pytest.mark.fast
@pytest.mark.parametrize("cls, module", CLASSES)
def test_a_request_over_a_foreign_crs_box_is_served_in_lambert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls, module
) -> None:
    asked = _stub(monkeypatch, module, lambda: [_sample(module.SOURCE_ID)])

    result = cls(page_size=7).fetch(FetchRequest(out_dir=tmp_path, extent=FOREIGN))

    assert asked[0][0] == pytest.approx(_expected_box(FOREIGN), rel=0, abs=1e-6)
    assert result.extent is not None and result.extent.crs == "EPSG:2154"
    assert asked[0][1] == 7


@pytest.mark.fast
@pytest.mark.parametrize("cls, module", CLASSES)
def test_a_box_without_a_crossing_answers_an_empty_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls, module
) -> None:
    _stub(monkeypatch, module, lambda: [records.empty("EPSG:2154")])

    result = cls().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT))

    assert result.is_empty
    frame = gpd.read_file(tmp_path / cache_file_name(cls.source_id, BOX))
    assert list(frame.columns) == [*records.ATTRIBUTES, "geometry"]
    assert len(frame) == 0


@pytest.mark.fast
@pytest.mark.parametrize("cls, module", CLASSES)
def test_the_refusals_of_the_port_are_made_before_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cls, module
) -> None:
    """Stations are not a selector of a crossings source, and neither is a period.

    The both-at-once wording of the port is for a source that declares the two
    selectors; one that declares only the extent refuses the stations as a
    selector it does not have, whether the request carries a box as well.
    """
    from hydromodpy.data.source.port import ALL_SELECTORS

    assert list(cls.selectors) != list(ALL_SELECTORS)
    asked = _stub(monkeypatch, module, lambda: [_sample(module.SOURCE_ID)])

    with pytest.raises(DataCapabilityError, match="does not select by"):
        cls().fetch(FetchRequest(out_dir=tmp_path, station_ids=("X1",)))
    with pytest.raises(DataCapabilityError, match="does not select by"):
        cls().fetch(FetchRequest(out_dir=tmp_path, extent=EXTENT, station_ids=("X1",)))
    with pytest.raises(DataCapabilityError, match="no time axis"):
        require_period(cls(), FetchRequest(out_dir=tmp_path, extent=EXTENT, period=PERIOD))
    assert asked == [], "the provider was reached before the request was refused"
