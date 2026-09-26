"""A phase gives each objective block its own share.

``objective_blocks`` on a phase is either a list of names, which keeps each
selected block's declared weight, or a table ``{block: share}``, which
replaces the selected blocks' weight with the phase's own share. Both forms
select the same blocks; the table changes only what the composite objective
sees, and shares are normalised to sum to one exactly like declared weights
already are.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.objective import (
    CompositeObjective,
    build_objective_from_config,
)
from hydromodpy.calibration.runners.staged_runner import _phase_config

NETWORK_BLOCK = {
    "name": "network",
    "metric": "distance_gap",
    "uses_outputs": ["net"],
}
HYDROGRAPH_BLOCK = {
    "name": "hydrograph",
    "metric": "rmse",
    "uses_outputs": ["q"],
    "weight": 3.0,
    "normalize_cost": True,
}

SEVENTY_THIRTY = {
    "name": "seventy_thirty",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": {"network": 70, "hydrograph": 30},
}
FIFTY_FIFTY = {
    "name": "fifty_fifty",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": {"network": 50, "hydrograph": 50},
}
LIST_FORM = {
    "name": "list_form",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": ["network", "hydrograph"],
}
HYDROGRAPH_ONLY = {
    "name": "hydrograph_only",
    "method": "grid",
    "parameters": ["K"],
    "objective_blocks": {"hydrograph": 1.0},
}


def _config(phases: list[dict]) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parameters": {"K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"}},
            "outputs": {
                "net": {"support": "network", "stream_geometry_path": "streams.gpkg"},
                "q": {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observed_values": [1.0, 2.0, 3.0],
                },
            },
            "objective_blocks": [NETWORK_BLOCK, HYDROGRAPH_BLOCK],
            "phases": phases,
        }
    )


def _normalized_weights(cfg: CalibrationConfig, phase) -> dict[str, float]:
    phase_cfg = _phase_config(cfg, phase)
    obj = build_objective_from_config(phase_cfg)
    assert isinstance(obj, CompositeObjective)
    return {block.name: weight for block, weight in obj.blocks}


class TestShareTable:
    def test_seventy_thirty_normalises_to_point_seven_point_three(self) -> None:
        cfg = _config([SEVENTY_THIRTY])
        weights = _normalized_weights(cfg, cfg.phases[0])

        assert weights["network"] == pytest.approx(0.7)
        assert weights["hydrograph"] == pytest.approx(0.3)

    def test_fifty_fifty_normalises_to_half_and_half(self) -> None:
        cfg = _config([FIFTY_FIFTY])
        weights = _normalized_weights(cfg, cfg.phases[0])

        assert weights["network"] == pytest.approx(0.5)
        assert weights["hydrograph"] == pytest.approx(0.5)

    def test_the_share_replaces_the_declared_weight(self) -> None:
        # hydrograph declares weight 3.0; the phase's share overrides it.
        cfg = _config([SEVENTY_THIRTY])
        phase_cfg = _phase_config(cfg, cfg.phases[0])
        weights = {block.name: block.weight for block in phase_cfg.objective_blocks}

        assert weights == {"network": 70, "hydrograph": 30}


class TestListFormUnchanged:
    def test_the_list_form_keeps_the_declared_weight(self) -> None:
        cfg = _config([LIST_FORM])
        phase_cfg = _phase_config(cfg, cfg.phases[0])
        weights = {block.name: block.weight for block in phase_cfg.objective_blocks}

        assert weights == {"network": 1.0, "hydrograph": 3.0}


class TestNoCrossPhaseMutation:
    def test_a_phase_built_twice_from_the_same_config_sees_the_same_shares(self) -> None:
        # Two phases of one config, built in turn, then the first one again:
        # a shared mutable block dict would let the second phase's share leak
        # into the first's re-read.
        cfg = _config([SEVENTY_THIRTY, FIFTY_FIFTY])

        first = _normalized_weights(cfg, cfg.phases[0])
        _normalized_weights(cfg, cfg.phases[1])
        first_again = _normalized_weights(cfg, cfg.phases[0])

        assert first == first_again
        assert first["network"] == pytest.approx(0.7)
        assert first["hydrograph"] == pytest.approx(0.3)

    def test_the_declared_blocks_keep_their_own_weight(self) -> None:
        cfg = _config([SEVENTY_THIRTY, FIFTY_FIFTY])

        _phase_config(cfg, cfg.phases[0])
        _phase_config(cfg, cfg.phases[1])

        weights = {block.name: block.weight for block in cfg.objective_blocks}
        assert weights == {"network": 1.0, "hydrograph": 3.0}


class TestPartialSelection:
    def test_a_table_naming_one_block_keeps_only_that_block_and_its_output(self) -> None:
        cfg = _config([HYDROGRAPH_ONLY])
        phase_cfg = _phase_config(cfg, cfg.phases[0])

        assert [block.name for block in phase_cfg.objective_blocks] == ["hydrograph"]
        assert set(phase_cfg.outputs) == {"q"}


class TestRefused:
    def test_an_unknown_block_in_the_share_table(self) -> None:
        with pytest.raises(ValueError, match="undeclared objective block"):
            _config([{**SEVENTY_THIRTY, "objective_blocks": {"nowhere": 1.0}}])

    def test_a_zero_share_is_refused(self) -> None:
        with pytest.raises(ValueError):
            _config([{**SEVENTY_THIRTY, "objective_blocks": {"network": 0.0, "hydrograph": 1.0}}])

    def test_a_negative_share_is_refused(self) -> None:
        with pytest.raises(ValueError):
            _config([{**SEVENTY_THIRTY, "objective_blocks": {"network": -1.0, "hydrograph": 1.0}}])
