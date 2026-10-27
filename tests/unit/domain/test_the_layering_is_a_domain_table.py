"""The layering is ``[domain.layers]``, never a key of a solver ``sgrid`` table.

The refusal of ``sgrid.vertical`` itself is a row of the retired keys in
``tests/unit/solver/modflow_grid/test_sgrid_config.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig


def test_a_modflow6_sgrid_vertical_table_is_refused_naming_the_doctor_fix() -> None:
    with pytest.raises(ValidationError, match=r"hmp doctor --fix-config"):
        Modflow6Config.model_validate({"sgrid": {"vertical": {"nlay": 2}}})


def test_domain_layers_defaults_to_one_constant_layer() -> None:
    layers = DomainConfig().layers

    assert isinstance(layers, VerticalGridConfig)
    assert layers.genmtd_lay == "constant"
    assert layers.nlay == 1


def test_domain_layers_validates_its_table() -> None:
    config = DomainConfig.model_validate(
        {"layers": {"genmtd_lay": "decay", "nlay": 4, "lay_decay": 1.5}}
    )

    assert config.layers.nlay == 4
    assert config.layers.lay_decay == 1.5
    with pytest.raises(ValidationError):
        DomainConfig.model_validate({"layers": {"nlay": 0}})
