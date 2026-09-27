"""A run writes the aquifer thickness it solved into its parameters table.

The thickness is calibrable, so a trial that moved it has to say which value
it ran with. ``Domain`` keeps its depth model under ``config``; reading
``domain.depth_model`` found nothing and the row was never written.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_params


class _Store:
    def __init__(self) -> None:
        self.written: list[dict] = []

    def write_parameters(self, sim_id: str, params: list[dict]) -> None:
        del sim_id
        self.written.extend(params)


def _persist(config: DomainConfig) -> list[dict]:
    store = _Store()
    step_persist_params(
        store,
        "sim",
        SimpleNamespace(parameters={}),
        domain=SimpleNamespace(config=config),
    )
    return store.written


def test_a_constant_thickness_reaches_the_parameters_table() -> None:
    rows = _persist(DomainConfig.with_thickness(30.0))

    assert rows == [
        {
            "param_name": "thickness",
            "zone_id": None,
            "value": 30.0,
            "unit": "m",
            "parameterization": "homogeneous",
        }
    ]


def test_a_flat_substratum_writes_no_thickness() -> None:
    config = DomainConfig.model_validate(
        {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 0.0}}
    )

    assert _persist(config) == []
