"""The ``sgrid`` table of a MODFLOW backend only says how the top is sampled from the DEM.

The keys it had before the mesh and layer tables took over are refused with the table that
replaces them. The table is read from a backend table or on its own.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig

RETIRED_KEYS = [
    pytest.param(
        SolverSGridConfig,
        {"planar": {"nlay": 2}},
        r"sgrid\.planar is replaced by \[mesh\]: write cell_size",
        id="planar",
    ),
    pytest.param(
        SolverSGridConfig,
        {"grid_dual": {"nlay": 2}},
        r"sgrid\.grid_dual is replaced by \[mesh\] engine",
        id="grid dual",
    ),
    pytest.param(
        SolverSGridConfig,
        {"vertical": {"nlay": 2}},
        r"sgrid\.vertical is replaced by \[domain\.layers\]",
        id="vertical",
    ),
    pytest.param(
        SolverSGridConfig, "zonal", "Input should be a valid dictionary", id="not a table"
    ),
    pytest.param(
        Modflow6Config,
        {"sgrid": {"vertical": {"nlay": 2}}},
        r"does not rewrite the file",
        id="modflow6 vertical says the file is not rewritten",
    ),
]

ZONAL_P25 = {"top_sampling": {"mode": "zonal", "hillslope_stat": "p25"}}


@pytest.mark.parametrize(("model", "payload", "match"), RETIRED_KEYS)
def test_retired_key_refusals(model, payload, match):
    with pytest.raises(ValidationError, match=match):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"sgrid": ZONAL_P25}, id="backend table"),
        pytest.param(ZONAL_P25, id="bare table"),
    ],
)
def test_from_mapping(payload):
    config = SolverSGridConfig.from_mapping(payload)

    assert (config.top_sampling.mode, config.top_sampling.hillslope_stat) == ("zonal", "p25")
    assert SolverSGridConfig.from_mapping({}) == SolverSGridConfig()
