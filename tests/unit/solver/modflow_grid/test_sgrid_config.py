"""The ``sgrid`` table of a MODFLOW backend only says how the top is sampled from the DEM."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig


@pytest.mark.parametrize(
    ("model", "payload", "match"),
    [
        (SolverSGridConfig, {"planar": {"nlay": 2}}, r"sgrid\.planar is replaced by \[mesh\]: write cell_size"),
        (SolverSGridConfig, {"grid_dual": {"nlay": 2}}, r"sgrid\.grid_dual is replaced by \[mesh\] engine"),
        (SolverSGridConfig, {"vertical": {"nlay": 2}}, r"sgrid\.vertical is replaced by \[domain\.layers\]"),
        (SolverSGridConfig, "zonal", "Input should be a valid dictionary"),
        (Modflow6Config, {"sgrid": {"vertical": {"nlay": 2}}}, r"hmp doctor --fix-config"),
    ],
    ids=["planar", "grid_dual", "vertical", "not_a_table", "modflow6_vertical_names_the_doctor_fix"],
)  # fmt: skip
def test_a_retired_sgrid_key_is_refused_naming_the_table_that_replaces_it(model, payload, match):
    with pytest.raises(ValidationError, match=match):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [{"sgrid": {"top_sampling": {"mode": "zonal", "hillslope_stat": "p25"}}}, {"top_sampling": {"mode": "zonal", "hillslope_stat": "p25"}}],
    ids=["backend-table", "bare-sgrid-table"],
)  # fmt: skip
def test_from_mapping_reads_the_sgrid_table_of_a_backend_or_the_table_itself(payload):
    config = SolverSGridConfig.from_mapping(payload)

    assert (config.top_sampling.mode, config.top_sampling.hillslope_stat) == ("zonal", "p25")
    assert SolverSGridConfig.from_mapping({}) == SolverSGridConfig()
