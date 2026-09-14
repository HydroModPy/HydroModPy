"""Adding a cost in metres to a cost in m3/s lets the unit set the weighting.

``normalize_cost`` exists for exactly this: it divides a block's cost by a
reference scale so that two blocks become comparable. Nothing enforced it. A file
could weight a head RMSE in metres at 0.5 and a discharge RMSE in m3/s at 0.5,
believe it had split the cost evenly, and hand the metres whatever share their
own magnitude happened to buy.

The criterion now declares the unit of its cost, so the composite can see the
mix and refuse it. Two costs in the same unit add up fine. Dimensionless ones add
up fine. A mix is refused unless every dimensionful member is normalised, which
is what makes the weights mean what they say.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibrationConfig


def _config(blocks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
        "outputs": {
            "head": {
                "variable": "head",
                "support": "cell",
                "row": 0,
                "col": 0,
                "observed_values": [1.0, 2.0],
            },
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observed_values": [1.0, 2.0],
            },
        },
        "objective_blocks": blocks,
    }


def _rmse(name: str, output: str, **extra: object) -> dict[str, object]:
    return {"name": name, "metric": "rmse", "uses_outputs": [output], **extra}


class TestWhatIsRefused:
    def test_two_dimensionful_costs_from_different_families_are_refused(self) -> None:
        with pytest.raises(ValueError, match="unit"):
            CalibrationConfig.model_validate(_config([_rmse("heads", "head"), _rmse("flows", "q")]))

    def test_the_refusal_names_both_blocks_and_the_way_out(self) -> None:
        with pytest.raises(ValueError) as caught:
            CalibrationConfig.model_validate(_config([_rmse("heads", "head"), _rmse("flows", "q")]))

        message = str(caught.value)
        assert "heads" in message and "flows" in message
        assert "normalize_cost" in message


class TestWhatIsAccepted:
    def test_normalising_every_dimensionful_member_makes_it_legitimate(self) -> None:
        cfg = CalibrationConfig.model_validate(
            _config(
                [
                    _rmse("heads", "head", normalize_cost=True),
                    _rmse("flows", "q", normalize_cost=True),
                ]
            )
        )

        assert len(cfg.objective_blocks) == 2

    def test_mixing_a_dimensionless_score_with_a_normalised_residual_is_fine(self) -> None:
        cfg = CalibrationConfig.model_validate(
            _config(
                [
                    {"name": "flows", "metric": "nse_log", "uses_outputs": ["q"]},
                    _rmse("heads", "head", normalize_cost=True),
                ]
            )
        )

        assert len(cfg.objective_blocks) == 2

    def test_two_dimensionless_scores_add_up_without_a_word(self) -> None:
        cfg = CalibrationConfig.model_validate(
            _config(
                [
                    {"name": "flows", "metric": "nse_log", "uses_outputs": ["q"]},
                    {"name": "heads", "metric": "kge", "uses_outputs": ["head"]},
                ]
            )
        )

        assert len(cfg.objective_blocks) == 2

    def test_a_single_block_is_never_a_mix(self) -> None:
        cfg = CalibrationConfig.model_validate(_config([_rmse("heads", "head")]))

        assert len(cfg.objective_blocks) == 1

    def test_two_residual_costs_on_the_same_family_add_up(self) -> None:
        """Same unit, so nothing to reconcile."""
        cfg = CalibrationConfig.model_validate(
            _config([_rmse("a", "q"), {"name": "b", "metric": "mae", "uses_outputs": ["q"]}])
        )

        assert len(cfg.objective_blocks) == 2


def test_the_declaration_stands_alone() -> None:
    """The check is on the calibration, not on one block: a block has no siblings."""
    assert CalibObjectiveBlockDecl(name="b", metric="rmse", uses_outputs=["q"]) is not None
