"""DataPlanner: activate precipitation and ETP for a declared soil reservoir.

``[flow.sinks_sources.recharge.soil]`` fills and empties day by day from
``[data.precipitation]`` and ``[data.etp]``; the planner infers them by
``flow_soil_reservoir`` when the file forgets them in ``data.types``, with a
traceable reason. A config without a soil section infers neither, and a
family the file already lists is not re-inferred.
"""

from __future__ import annotations

from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.data.loading.planner import DataPlanner


def _empty_config() -> DataManagersConfig:
    return DataManagersConfig.model_validate({"types": []})


def test_a_declared_soil_reservoir_infers_precipitation_and_etp() -> None:
    plan = DataPlanner().build(_empty_config(), flow_soil_reservoir=True)

    assert "precipitation" in plan.inferred_types
    assert "etp" in plan.inferred_types
    assert any(
        "[flow.sinks_sources.recharge.soil]" in reason
        for reason in plan.reasons_by_type["precipitation"]
    )
    assert any(
        "[flow.sinks_sources.recharge.soil]" in reason for reason in plan.reasons_by_type["etp"]
    )


def test_no_soil_reservoir_infers_neither() -> None:
    plan = DataPlanner().build(_empty_config(), flow_soil_reservoir=False)

    assert "precipitation" not in plan.inferred_types
    assert "etp" not in plan.inferred_types


def test_a_type_already_declared_is_not_re_inferred() -> None:
    cfg = DataManagersConfig.model_validate({"types": ["precipitation"]})

    plan = DataPlanner().build(cfg, flow_soil_reservoir=True)

    assert "precipitation" not in plan.inferred_types
    assert "etp" in plan.inferred_types
