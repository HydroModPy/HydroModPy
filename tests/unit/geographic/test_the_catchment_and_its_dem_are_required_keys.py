"""The reference shows [geographic.catchment] and the DEM of the dem shape as required.

Both fields have no default. A synthetic support still leaves the catchment out,
and a [data.dem] source may still give the DEM: what is missing then is refused
with a message that names the key.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.geographic_config import DemCatchDef, GeographicConfig


@pytest.mark.fast
def test_the_catchment_and_the_dem_of_the_dem_shape_have_no_default() -> None:
    assert GeographicConfig.model_fields["catchment"].is_required()
    dem = DemCatchDef.model_fields["dem_init_path"]
    assert dem.is_required()
    assert dem.examples == ["dem.tif"]


@pytest.mark.fast
def test_a_synthetic_support_leaves_the_catchment_out() -> None:
    assert GeographicConfig.model_validate({"source_mode": "synthetic"}).catchment is None


@pytest.mark.fast
def test_a_standard_support_without_catchment_names_the_table() -> None:
    with pytest.raises(ValidationError, match=r"Add a \[geographic.catchment\] table"):
        GeographicConfig.model_validate({})


@pytest.mark.fast
def test_a_dem_shape_without_its_dem_names_the_key() -> None:
    with pytest.raises(ValidationError, match="requires 'dem_init_path'"):
        GeographicConfig.model_validate({"catchment": {"catch_def": "dem"}})


@pytest.mark.fast
def test_a_dem_source_may_still_give_the_dem() -> None:
    cfg = GeographicConfig.model_validate(
        {"catchment": {"catch_def": "dem"}}, context={"allow_dem_bootstrap": True}
    )

    assert cfg.dem_init_path is None
