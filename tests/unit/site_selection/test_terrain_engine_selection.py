"""The third door named in ``_site_selection_dem.py``: F10f.

``[geographic]`` already lets a project TOML name a flow-routing engine
(``tests/unit/geographic/test_terrain_engine_selection.py``, gate 1). This
mirrors that gate for ``[site_selection]`` and adds the one thing the
geographic suite cannot exercise here: proof that the value actually reaches
the two builders every ``pipelines/build.py`` entry point calls through,
using the same fake-builder pattern as
``tests/unit/site_selection/test_build_from_point_records.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.pipelines.build import (
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.terrain import registry
from tests._helpers.terrain_doubles import fake_flow_products

from ._test_build_builders import make_config, make_record

pytestmark = pytest.mark.fast


def _an_installed_engine() -> str:
    return registry.builtin_engine_ids()[0]


def _config_with_engine(tmp_path, engine_id: str | None) -> SiteSelectionConfig:
    """Build the config the way a document does, through validation.

    ``model_copy(update=...)`` would be shorter and would prove nothing:
    Pydantic v2 runs no validator on it, so an engine nobody installed would
    be accepted and the gate below would pass for the wrong reason. Revalidating
    a dumped payload is what a TOML read does.
    """
    payload = make_config(tmp_path).model_dump(mode="python")
    if engine_id is not None:
        payload["terrain_engine"] = engine_id
    return SiteSelectionConfig.model_validate(payload)


# --- Gate 1: the document ---------------------------------------------------


def test_a_project_can_name_an_engine_this_installation_serves(tmp_path) -> None:
    engine_id = _an_installed_engine()

    config = _config_with_engine(tmp_path, engine_id)

    assert config.terrain_engine == engine_id


def test_a_project_that_names_no_engine_carries_none_and_not_a_default(tmp_path) -> None:
    """The default lives in the registry, not in the document.

    A configuration that wrote the default down would freeze it: the day this
    build changes which engine it defaults to, a project file that still
    names the old one would keep it, silently.
    """
    assert _config_with_engine(tmp_path, None).terrain_engine is None


def test_a_project_naming_an_engine_nobody_installed_is_refused_while_reading(tmp_path) -> None:
    """Refused at the document, not at the first delineation.

    A DEM is conditioned before anything routes; finding out afterwards that
    the engine does not exist costs that conditioning for nothing.
    """
    with pytest.raises(ValidationError) as raised:
        _config_with_engine(tmp_path, "no-such-engine")

    message = str(raised.value)
    assert "site_selection.terrain_engine" in message
    assert registry.ENTRY_POINT_GROUP in message
    for engine_id in registry.builtin_engine_ids():
        assert engine_id in message


# --- Gate 2: the value reaches both builders --------------------------------


def _fake_delineation_builder(calls: list[dict]):
    def build(**kwargs):
        calls.append(kwargs)
        output_dir = kwargs["output_dir"]
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    return build


def test_the_configured_engine_reaches_the_flow_and_delineation_builders(tmp_path) -> None:
    engine_id = _an_installed_engine()
    flow_calls: dict = {}
    delineation_calls: list[dict] = []

    def fake_flow_builder(**kwargs):
        flow_calls.update(kwargs)
        return fake_flow_products(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    build_site_selection_from_point_records(
        config=_config_with_engine(tmp_path, engine_id),
        point_records=[make_record("J123456701")],
        flow_products_builder=fake_flow_builder,
        delineation_builder=_fake_delineation_builder(delineation_calls),
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert flow_calls["engine_id"] == engine_id
    assert delineation_calls[0]["engine_id"] == engine_id


def test_an_unset_engine_reaches_the_builders_as_none_not_a_missing_argument(tmp_path) -> None:
    """A silently dropped ``engine_id`` and an explicit ``None`` look identical

    to a builder using ``dict.get``. Asserting the key's presence, not only
    its value, is what would have caught a call site that forgot the keyword.
    """
    flow_calls: dict = {}
    delineation_calls: list[dict] = []

    def fake_flow_builder(**kwargs):
        flow_calls.update(kwargs)
        return fake_flow_products(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    build_site_selection_from_point_records(
        config=_config_with_engine(tmp_path, None),
        point_records=[make_record("J123456701")],
        flow_products_builder=fake_flow_builder,
        delineation_builder=_fake_delineation_builder(delineation_calls),
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert "engine_id" in flow_calls
    assert flow_calls["engine_id"] is None
    assert "engine_id" in delineation_calls[0]
    assert delineation_calls[0]["engine_id"] is None
