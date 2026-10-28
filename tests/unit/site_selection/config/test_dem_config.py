"""A ``[site_selection]`` names its flow-routing engine, checked while reading.

This mirrors the gate of ``[geographic]`` (``tests/unit/geographic/``). That the
value reaches the builders is checked in ``pipelines/test_build.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.terrain import registry
from tests._helpers.site_selection_cases import make_config

pytestmark = pytest.mark.fast


def config_with_engine(tmp_path, engine_id: str | None) -> SiteSelectionConfig:
    """Revalidate a dumped payload, the way a TOML read does.

    ``model_copy(update=...)`` runs no validator, so it would accept an engine
    nobody installed and the refusal below would pass for the wrong reason.
    """
    payload = make_config(tmp_path).model_dump(mode="python")
    if engine_id is not None:
        payload["terrain_engine"] = engine_id
    return SiteSelectionConfig.model_validate(payload)


def test_a_project_can_name_an_engine_this_installation_serves(tmp_path) -> None:
    engine_id = registry.builtin_engine_ids()[0]

    assert config_with_engine(tmp_path, engine_id).terrain_engine == engine_id


def test_a_project_that_names_no_engine_carries_none_and_not_a_default(tmp_path) -> None:
    """The default lives in the registry. A document that wrote it would freeze it."""
    assert config_with_engine(tmp_path, None).terrain_engine is None


def test_a_project_naming_an_engine_nobody_installed_is_refused_while_reading(tmp_path) -> None:
    """Refused at the document, before a DEM is conditioned for nothing."""
    with pytest.raises(ValidationError) as raised:
        config_with_engine(tmp_path, "no-such-engine")

    message = str(raised.value)
    assert "site_selection.terrain_engine" in message
    assert registry.ENTRY_POINT_GROUP in message
    for engine_id in registry.builtin_engine_ids():
        assert engine_id in message
