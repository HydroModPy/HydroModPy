"""Discriminated union dispatch tests for DataSource, SolverConfig, SimulationProcessConfig."""

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


# ---------------------------------------------------------------------------
# DataSource axis (DEM + Geology variants share the 'source' discriminator)
# ---------------------------------------------------------------------------


class TestDataSourceUnion:
    DISPATCH_CASES = [
        pytest.param(
            DemSourceConfig,
            {"source": "file", "path": "dem.tif"},
            FileDemSource,
            {"source": "file"},
            id="dem_custom",
        ),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_geoplateforme_dem", "dataset": "bd-alti", "resolution_m": 25.0},
            IgnGeoplateformeDemSource,
            {"source": "ign_geoplateforme_dem", "dataset": "bd-alti"},
            id="dem_ign_geoplateforme",
        ),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_geoplateforme_dem", "dataset": "rge-alti", "resolution_m": 5.0},
            IgnGeoplateformeDemSource,
            {"source": "ign_geoplateforme_dem", "dataset": "rge-alti"},
            id="dem_ign_geoplateforme_rge_alti",
        ),
        pytest.param(
            GeologySourceConfig,
            {"source": "brgm_1m"},
            BrgmGeology1mSource,
            {},
            id="geology_brgm_1m",
        ),
        pytest.param(
            GeologySourceConfig,
            {"source": "brgm_50k"},
            BrgmGeology50kSource,
            {},
            id="geology_brgm_50k",
        ),
    ]

    REJECT_CASES = [
        pytest.param(DemSourceConfig, {"source": "missing"}, id="dem_unknown_source"),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_bdalti", "resolution_m": 25.0},
            id="dem_ign_bdalti_legacy_source_rejected",
        ),
        pytest.param(
            DemSourceConfig,
            {"source": "ign_geoplateforme_dem", "dataset": "rge-alti", "resolution_m": 25.0},
            id="dem_geoplateforme_rge_alti_25m_rejected",
        ),
    ]

    @pytest.mark.parametrize(("union", "payload"), REJECT_CASES)
    def test_variant_rejected(self, union, payload) -> None:
        ta = TypeAdapter(union)
        with pytest.raises(ValidationError):
            ta.validate_python(payload)


# ---------------------------------------------------------------------------
# SolverConfig axis: no union any more, the backend is a registered name
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SimulationProcessConfig axis (type discriminator: flow/transport/mesh)
# ---------------------------------------------------------------------------
