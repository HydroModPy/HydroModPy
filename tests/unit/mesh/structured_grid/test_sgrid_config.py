"""The ``sgrid`` table of a MODFLOW backend, :mod:`hydromodpy.spatial.mesh.structured_grid.sgrid_config`.

It only says how the top of the solver grid is sampled from the DEM. A key it
held before is refused with the name of the table that replaces it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.mesh.structured_grid.sgrid_config import SolverSGridConfig


@pytest.mark.parametrize(
    ("key", "match"),
    [
        ("planar", r"sgrid\.planar is replaced by \[mesh\]: write cell_size"),
        ("grid_dual", r"sgrid\.grid_dual is replaced by \[mesh\] engine"),
        ("vertical", r"sgrid\.vertical is replaced by \[domain\.layers\]"),
    ],
    ids=["planar", "grid_dual", "vertical"],
)
def test_a_retired_sgrid_key_is_refused_naming_the_table_that_replaces_it(key, match):
    with pytest.raises(ValidationError, match=match):
        SolverSGridConfig.model_validate({key: {"nlay": 2}})


@pytest.mark.parametrize(
    "payload",
    [
        {"sgrid": {"top_sampling": {"mode": "zonal", "hillslope_stat": "p25"}}},
        {"top_sampling": {"mode": "zonal", "hillslope_stat": "p25"}},
    ],
    ids=["backend-table", "bare-sgrid-table"],
)
def test_from_mapping_reads_the_sgrid_table_of_a_backend_or_the_table_itself(payload):
    config = SolverSGridConfig.from_mapping(payload)

    assert config.top_sampling.mode == "zonal"
    assert config.top_sampling.hillslope_stat == "p25"


def test_an_sgrid_value_that_is_not_a_table_is_refused():
    with pytest.raises(ValidationError, match="Input should be a valid dictionary"):
        SolverSGridConfig.model_validate("zonal")


def test_a_backend_without_sgrid_table_takes_the_default_sampling():
    assert SolverSGridConfig.from_mapping({}) == SolverSGridConfig()
