"""What a phase table has to say before the first solve runs."""

from __future__ import annotations

import json

import pytest

from hydromodpy.calibration.config import CalibrationConfig


def _config(phases: list[dict], **overrides) -> CalibrationConfig:
    payload = {
        "method": "grid",
        "parameters": {
            "K": {"bounds": [1e-9, 1e-3], "transform": "log", "path": "flow.param.K.field.value"},
            "Sy": {"bounds": [1e-3, 3e-1], "path": "flow.param.Sy.field.value"},
        },
        "outputs": {
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observed_values": [1.0, 2.0],
            }
        },
        "objective_blocks": [{"name": "b", "metric": "rmse", "uses_outputs": ["q"]}],
        "phases": phases,
        **overrides,
    }
    return CalibrationConfig.model_validate(payload)


STEADY = {
    "name": "steady_k_over_r",
    "method": "bisection",
    "parameters": ["K"],
    "freeze_on_success": True,
}
TRANSIENT = {
    "name": "transient_sy",
    "method": "grid",
    "parameters": ["Sy"],
    "depends_on": "steady_k_over_r",
}


class TestDefault:
    def test_a_configuration_without_phases_is_unchanged(self) -> None:
        cfg = CalibrationConfig.model_validate({"method": "grid"})
        assert cfg.phases is None

    def test_an_absent_table_leaves_the_resume_hash_untouched(self) -> None:
        # The resume lock hashes the configuration with exclude_none, so the
        # field has to default to None and not to an empty list, otherwise
        # every checkpoint in the wild stops being resumable.
        cfg = CalibrationConfig.model_validate({"method": "grid"})
        assert "phases" not in json.loads(cfg.model_dump_json(exclude_none=True))


class TestAccepted:
    def test_two_phases_in_order(self) -> None:
        cfg = _config([STEADY, TRANSIENT])
        assert [phase.name for phase in cfg.phases] == ["steady_k_over_r", "transient_sy"]
        assert cfg.phases[0].method == "bisection"
        assert cfg.phases[1].depends_on == "steady_k_over_r"

    def test_a_phase_selects_outputs_and_blocks_by_name(self) -> None:
        cfg = _config([{**STEADY, "outputs": ["q"], "objective_blocks": ["b"]}])
        assert cfg.phases[0].outputs == ["q"]

    def test_an_empty_selection_means_every_declaration(self) -> None:
        cfg = _config([STEADY])
        assert cfg.phases[0].outputs == []
        assert cfg.phases[0].objective_blocks == []


class TestRefused:
    def test_a_duplicate_phase_name(self) -> None:
        with pytest.raises(ValueError, match="declared twice"):
            _config([STEADY, {**STEADY}])

    def test_an_undeclared_parameter(self) -> None:
        with pytest.raises(ValueError, match="undeclared parameter"):
            _config([{**STEADY, "parameters": ["Kv"]}])

    def test_a_parameter_without_a_path(self) -> None:
        with pytest.raises(ValueError, match="declares no path"):
            CalibrationConfig.model_validate(
                {
                    "method": "grid",
                    "parameters": {"K": {"bounds": [1.0, 2.0]}},
                    "phases": [{"name": "p", "parameters": ["K"]}],
                }
            )

    def test_two_phases_freezing_the_same_path(self) -> None:
        # The second would overwrite what the first calibrated, and nothing
        # downstream would say which value the model actually ran with.
        with pytest.raises(ValueError, match="both freeze"):
            _config(
                [
                    STEADY,
                    {"name": "again", "parameters": ["K"], "freeze_on_success": True},
                ]
            )

    def test_a_dependency_declared_after_its_dependant(self) -> None:
        with pytest.raises(ValueError, match="not declared before it"):
            _config([TRANSIENT, STEADY])

    def test_a_dependency_on_an_unknown_phase(self) -> None:
        with pytest.raises(ValueError, match="not declared before it"):
            _config([{**TRANSIENT, "depends_on": "nowhere"}])

    def test_an_undeclared_output(self) -> None:
        with pytest.raises(ValueError, match="undeclared output"):
            _config([{**STEADY, "outputs": ["heads"]}])

    def test_an_undeclared_objective_block(self) -> None:
        with pytest.raises(ValueError, match="undeclared objective block"):
            _config([{**STEADY, "objective_blocks": ["nowhere"]}])

    def test_a_window_and_a_sample_count_together(self) -> None:
        with pytest.raises(ValueError, match="pick one convention"):
            _config(
                [{**STEADY, "scoring_window": {"start": "2012-01-01"}}],
                warmup_periods=5,
            )


class TestNetworkCriterionPairing:
    def _network_config(self, blocks: list[dict]) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {
                "method": "bisection",
                "parameters": {"K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"}},
                "outputs": {
                    "net": {"support": "network", "stream_geometry_path": "streams.gpkg"},
                    "q": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observed_values": [1.0, 2.0],
                    },
                },
                "objective_blocks": blocks,
            }
        )

    def test_the_gap_metric_on_a_network_output_is_accepted(self) -> None:
        cfg = self._network_config(
            [{"name": "abherve", "metric": "distance_gap", "uses_outputs": ["net"]}]
        )
        assert cfg.objective_blocks[0].metric == "distance_gap"

    def test_the_gap_metric_on_anything_else_is_refused(self) -> None:
        # distance_gap reads the pair (D_so, D_os); a discharge series is not
        # that pair, and scoring it would produce a number with no meaning.
        with pytest.raises(ValueError, match="is not a network output"):
            self._network_config(
                [{"name": "wrong", "metric": "distance_gap", "uses_outputs": ["q"]}]
            )

    def test_a_network_output_nobody_scores_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no block declares either"):
            self._network_config([{"name": "b", "metric": "rmse", "uses_outputs": ["q"]}])
