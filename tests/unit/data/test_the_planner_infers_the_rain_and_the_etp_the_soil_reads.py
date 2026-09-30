"""DataPlanner: activate precipitation and ETP for a declared soil reservoir.

``[flow.sinks_sources.recharge.soil]`` fills and empties day by day from
``[data.precipitation]`` and ``[data.etp]``; the planner infers them by
``flow_soil_reservoir`` when the file forgets them in ``data.types``, with a
traceable reason. A config without a soil section infers neither, and a
family the file already lists is not re-inferred.

The same ``build()`` call also infers ``soil_capacity`` when
``[data.soil_capacity]`` is declared, independently of
``flow_soil_reservoir``: `config/hydromodpy_config.py` (R12) already refuses
any file that declares the capacity map without the soil section, so by the
time a validated config reaches the planner the two are never seen apart.
"""

from __future__ import annotations

from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.data.loading.planner import DataPlanner


def _empty_config() -> DataManagersConfig:
    return DataManagersConfig.model_validate({"types": []})


def _config_with_capacity_map() -> DataManagersConfig:
    return DataManagersConfig.model_validate(
        {
            "types": [],
            "soil_capacity": {"sources": [{"source": "custom", "path": "ru.tif"}]},
        }
    )


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


def test_a_capacity_map_beside_the_soil_reservoir_names_the_soil_section_in_its_reason() -> None:
    plan = DataPlanner().build(_config_with_capacity_map(), flow_soil_reservoir=True)

    assert "soil_capacity" in plan.inferred_types
    assert any(
        reason == "inferred from [data.soil_capacity] beside [flow.sinks_sources.recharge.soil]"
        for reason in plan.reasons_by_type["soil_capacity"]
    )


def test_a_capacity_map_without_the_soil_reservoir_flag_is_still_inferred() -> None:
    # R12 (hydromodpy_config.py) refuses a declared soil_capacity without the
    # soil section before build() ever runs, so the two callers of build()
    # never pass flow_soil_reservoir=False alongside a declared capacity map.
    # The planner itself does not re-check that pairing: locked here so a
    # future change to this independence is a deliberate decision, not a
    # silent regression.
    plan = DataPlanner().build(_config_with_capacity_map(), flow_soil_reservoir=False)

    assert "soil_capacity" in plan.inferred_types
