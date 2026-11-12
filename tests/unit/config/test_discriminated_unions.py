"""Source unions of the data sections.

A DEM or a geology source is picked by its ``source`` key. An unknown key, a retired
source name and a resolution the dataset does not offer are refused.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from hydromodpy.data.variables.dem.config import (
    DemSourceConfig,
    FileDemSource,
    IgnGeoplateformeDemSource,
)
from hydromodpy.data.variables.geology.config import (
    BrgmGeology1mSource,
    BrgmGeology50kSource,
    GeologySourceConfig,
)

pytestmark = pytest.mark.fast

PICKED = [
    pytest.param(
        DemSourceConfig, {"source": "file", "path": "dem.tif"}, FileDemSource, id="dem file"
    ),
    pytest.param(
        DemSourceConfig,
        {"source": "ign_geoplateforme_dem", "dataset": "bd-alti", "resolution_m": 25.0},
        IgnGeoplateformeDemSource,
        id="dem bd-alti",
    ),
    pytest.param(
        DemSourceConfig,
        {"source": "ign_geoplateforme_dem", "dataset": "rge-alti", "resolution_m": 5.0},
        IgnGeoplateformeDemSource,
        id="dem rge-alti",
    ),
    pytest.param(GeologySourceConfig, {"source": "brgm_1m"}, BrgmGeology1mSource, id="geology 1m"),
    pytest.param(
        GeologySourceConfig, {"source": "brgm_50k"}, BrgmGeology50kSource, id="geology 50k"
    ),
]

REJECTED = [
    pytest.param(DemSourceConfig, {"source": "missing"}, id="unknown source"),
    pytest.param(
        DemSourceConfig, {"source": "ign_bdalti", "resolution_m": 25.0}, id="retired bdalti source"
    ),
    pytest.param(
        DemSourceConfig,
        {"source": "ign_geoplateforme_dem", "dataset": "rge-alti", "resolution_m": 25.0},
        id="rge-alti at 25 m",
    ),
]


@pytest.mark.parametrize(("union", "payload", "picked"), PICKED)
def test_source_picks_its_class(union, payload, picked) -> None:
    assert type(TypeAdapter(union).validate_python(payload)) is picked


@pytest.mark.parametrize(("union", "payload"), REJECTED)
def test_refusals(union, payload) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(union).validate_python(payload)
