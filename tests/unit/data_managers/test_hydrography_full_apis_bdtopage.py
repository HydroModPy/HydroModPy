"""BD Topage adapter of the hydrography variable (client stubbed).

What the adapter adds to the Sandre client: the default layer, the canonical
``permanence`` column read off the Sandre vocabulary, and the WGS84 entry
point site selection calls. The client's own paging and refusals are covered
by ``tests/unit/data/test_sandre_topage_client.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.common.clients import sandre_topage
from hydromodpy.data.source.permanence import PERMANENCE_COLUMN
from hydromodpy.data.variables.hydrography.apis import bdtopage
from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig


def _reaches(**columns: Sequence[object]) -> gpd.GeoDataFrame:
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

    def _get_features(typename: str, bbox: tuple, *, page_size: int) -> gpd.GeoDataFrame:
        questions.append({"typename": typename, "bbox": bbox, "page_size": page_size})
        return _reaches(PersistanceTH=["permanent", "intermittent", "permanent"])

    monkeypatch.setattr(sandre_topage, "get_features", _get_features)
    return questions


@pytest.mark.fast
def test_the_default_layer_is_every_reach_with_its_persistence() -> None:
    assert bdtopage.DEFAULT_TYPENAME == "sa:TronconHydrographique_FXX_Topage2026"
    assert HydrographySourceConfig(source="bdtopage").typename == bdtopage.DEFAULT_TYPENAME


@pytest.mark.fast
def test_the_sandre_vocabulary_maps_onto_the_canonical_one() -> None:
    native = ["permanent", "intermittent", "éphémère", "sec", "inconnue"]
    frame = bdtopage.with_permanence(_reaches(PersistanceTH=native))

    assert frame[PERMANENCE_COLUMN].tolist() == [
        "permanent",
        "intermittent",
        "ephemeral",
        "dry",
        "unknown",
    ]
    assert frame["PersistanceTH"].tolist() == native, "the native attribute stays as it came"


@pytest.mark.fast
def test_a_value_the_sandre_never_wrote_is_unknown_and_named(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    frame = bdtopage.with_permanence(_reaches(PersistanceTH=["saisonnier", None]))

    assert frame[PERMANENCE_COLUMN].tolist() == ["unknown", "unknown"]
    assert "saisonnier" in caplog.text


@pytest.mark.fast
def test_water_surfaces_read_their_own_attribute() -> None:
    frame = bdtopage.with_permanence(_reaches(PersistanceSE=["intermittent"]))

    assert frame[PERMANENCE_COLUMN].tolist() == ["intermittent"]


@pytest.mark.fast
def test_a_layer_that_says_nothing_gets_no_column() -> None:
    """``CoursEau`` has no persistence: no column, never a guessed one."""
    frame = bdtopage.with_permanence(_reaches(TopoOH=["le Val"]))

    assert PERMANENCE_COLUMN not in frame.columns


@pytest.mark.fast
def test_the_source_asks_its_layer_over_the_lambert93_box(asked: list[dict]) -> None:
    box = (346361.0, 6797325.0, 363915.0, 6821726.0)
    frame = bdtopage.BdTopageSource(page_size=17).download(box)

    assert asked == [{"typename": bdtopage.DEFAULT_TYPENAME, "bbox": box, "page_size": 17}]
    assert frame[PERMANENCE_COLUMN].tolist() == ["permanent", "intermittent", "permanent"]
    assert bdtopage.BdTopageSource.extent_crs == "EPSG:2154"


@pytest.mark.fast
def test_a_wgs84_caller_gets_degrees_back_and_asks_a_box_that_holds_its_own(
    asked: list[dict],
) -> None:
    from pyproj import Transformer

    wgs84 = (-1.8, 48.1, -1.5, 48.4)
    cfg = HydrographySourceConfig(source="bdtopage", typename=bdtopage.NAMED_RIVERS_TYPENAME)

    frame = bdtopage.fetch(cfg, wgs84)

    assert str(frame.crs) == "EPSG:4326"
    (question,) = asked
    assert question["typename"] == "sa:CoursEau_FXX_Topage2026"
    to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    xmin, ymin, xmax, ymax = question["bbox"]
    for lon, lat in [(-1.8, 48.1), (-1.8, 48.4), (-1.5, 48.1), (-1.5, 48.4)]:
        x, y = to_l93.transform(lon, lat)
        assert xmin <= x <= xmax and ymin <= y <= ymax


@pytest.mark.fast
def test_an_overseas_layer_is_refused_when_the_source_is_built() -> None:
    with pytest.raises(DataRequestError, match="MYT"):
        bdtopage.BdTopageSource(typename="sa:TronconHydrographique_MYT_Topage2026")


@pytest.mark.fast
@pytest.mark.parametrize("page_size", [0, -1, True, 2.5])
def test_a_page_size_that_never_advances_is_refused(page_size: object) -> None:
    with pytest.raises(DataRequestError, match="page_size"):
        bdtopage.BdTopageSource(page_size=page_size)  # type: ignore[arg-type]
