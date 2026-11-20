"""Types the data planner adds when ``[data.types]`` forgets them, each with a traceable reason.

A declared soil reservoir (``[flow.sinks_sources.recharge.soil]``) is filled by
precipitation and ETP, so the planner infers both. A ``[data.soil_capacity]``
section is inferred on its own. The config refuses a capacity map without the
soil section before the planner runs, so the two are never seen apart.
"""

from __future__ import annotations

from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.loading.planner import DataPlanner

CAPACITY_MAP = {"sources": [{"source": "file", "path": "ru.tif"}]}


def test_a_type_already_declared_is_not_inferred_again():
    cfg = DataConfig.model_validate({"types": ["precipitation"]})

    plan = DataPlanner().build(cfg, flow_soil_reservoir=True)

    assert "precipitation" not in plan.inferred_types
    assert "etp" in plan.inferred_types


def test_a_capacity_map_beside_the_soil_reservoir_names_the_soil_section():
    cfg = DataConfig.model_validate({"types": [], "soil_capacity": CAPACITY_MAP})

    plan = DataPlanner().build(cfg, flow_soil_reservoir=True)

    assert "soil_capacity" in plan.inferred_types
    assert (
        "inferred from [data.soil_capacity] beside [flow.sinks_sources.recharge.soil]"
        in plan.reasons_by_type["soil_capacity"]
    )


def test_a_capacity_map_without_the_soil_reservoir_is_still_inferred():
    # The planner does not re-check the pairing, so a change to this
    # independence is a decision and not a silent regression.
    cfg = DataConfig.model_validate({"types": [], "soil_capacity": CAPACITY_MAP})

    plan = DataPlanner().build(cfg, flow_soil_reservoir=False)

    assert "soil_capacity" in plan.inferred_types


def test_no_capacity_map_infers_nothing():
    plan = DataPlanner().build(DataConfig.model_validate({"types": []}))

    assert "soil_capacity" not in plan.inferred_types
