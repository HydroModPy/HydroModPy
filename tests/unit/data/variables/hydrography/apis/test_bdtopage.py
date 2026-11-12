"""BD TOPAGE river reaches from the Sandre WFS, asked over a Lambert-93 box (m).

Each reach gets a permanence class from the layer attribute PersistanceTH.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import DataRequestError, DataSourceError
from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.common.clients import sandre_topage
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN
from hydromodpy.data.variables.hydrography.apis import bdtopage
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

pytestmark = pytest.mark.fast


def reaches(**columns: Sequence[object]) -> gpd.GeoDataFrame:
    n = len(next(iter(columns.values()))) if columns else 1
    return gpd.GeoDataFrame(
        {"gid": list(range(n)), **columns},
        geometry=[LineString([(350000.0 + i, 6800000.0), (350010.0, 6800010.0)]) for i in range(n)],
        crs="EPSG:2154",
    )


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stub the client: record each question and answer with three reaches."""
    questions: list[dict] = []

    def get_features(
        typename: str, bbox: tuple, *, page_size: int, client: HTTPClient
    ) -> gpd.GeoDataFrame:
        questions.append({"typename": typename, "bbox": bbox, "page_size": page_size})
        return reaches(PersistanceTH=["permanent", "intermittent", "permanent"])

    monkeypatch.setattr(sandre_topage, "get_features", get_features)
    return questions


def test_unknown_permanence_is_named(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)

    frame = bdtopage.with_permanence(reaches(PersistanceTH=["saisonnier", None]))

    assert frame[PERMANENCE_COLUMN].tolist() == ["unknown", "unknown"]
    assert "saisonnier" in caplog.text


def test_no_reach_is_not_an_error() -> None:
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")

    assert bdtopage.with_permanence(empty).empty


def test_the_source_asks_its_layer_over_the_lambert93_box(asked: list[dict]) -> None:
    box = (346361.0, 6797325.0, 363915.0, 6821726.0)

    frame = bdtopage.BdTopageSource(page_size=17).download(box, client=HTTPClient())

    assert asked == [{"typename": bdtopage.LAYER, "bbox": box, "page_size": 17}]
    assert frame[PERMANENCE_COLUMN].tolist() == ["permanent", "intermittent", "permanent"]
    assert bdtopage.BdTopageSource.extent_crs == "EPSG:2154"


def test_a_wgs84_caller_gets_degrees_back(asked: list[dict]) -> None:
    from pyproj import Transformer

    frame = bdtopage.fetch(
        HydrographySourceConfig(source="bdtopage"), (-1.8, 48.1, -1.5, 48.4), client=HTTPClient()
    )

    assert str(frame.crs) == "EPSG:4326"
    (question,) = asked
    assert question["typename"] == bdtopage.LAYER
    # The box asked in Lambert-93 holds the four corners of the box given in degrees.
    to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    xmin, ymin, xmax, ymax = question["bbox"]
    for lon, lat in [(-1.8, 48.1), (-1.8, 48.4), (-1.5, 48.1), (-1.5, 48.4)]:
        x, y = to_l93.transform(lon, lat)
        assert xmin <= x <= xmax and ymin <= y <= ymax


REFUSED_PAGE_SIZES = [
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
    pytest.param(True, id="bool"),
    pytest.param(2.5, id="float"),
]


def test_refusals() -> None:
    with pytest.raises(DataSourceError, match="PersistanceTH"):
        bdtopage.with_permanence(reaches(TopoOH=["le Val"]))  # the layer lost its attribute


@pytest.mark.parametrize("page_size", REFUSED_PAGE_SIZES)
def test_a_page_size_that_never_advances_is_refused(page_size: object) -> None:
    with pytest.raises(DataRequestError, match="page_size"):
        bdtopage.BdTopageSource(page_size=page_size)  # type: ignore[arg-type]
