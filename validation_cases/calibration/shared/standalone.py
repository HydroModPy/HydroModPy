"""The calibration driver and the command line of the standalone experiments.

``groundwater_1d``, ``recession_brutsaert`` and ``reservoir`` differ by their forward
model. Each case gives its ``parameter_space``, ``synthetic_observations`` and
``simulate``, and this module runs it through the calibration engine.
"""

from __future__ import annotations

import argparse
from typing import Any

from hydromodpy.calibration import (
    CalibrationEngine,
    CompositeObjective,
    ConfigBlockObjective,
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.objective import evaluate_objective


def build_standalone_calibration(
    case: Any,
    *,
    optimizer_name: str,
    max_trials: int,
    seed: int,
    metric: str,
    popsize: int,
    grid_points: int | None = None,
) -> tuple[CalibrationEngine, CompositeObjective]:
    """Assemble a ready-to-run engine, one objective block per station at equal weight.

    ``grid_points`` unset takes the finest regular grid the budget covers, because a
    grid cut short is refused.
    """
    space = case.parameter_space()
    objective = CompositeObjective(
        [
            (
                ConfigBlockObjective(
                    name=f"{metric}@{station}",
                    metric=metric,
                    uses_outputs=[station],
                    observed_by_output={station: observed},
                ),
                1.0,
            )
            for station, observed in case.synthetic_observations().items()
        ],
        name=metric,
    )
    options: dict[str, object] = {"seed": seed}
    if optimizer_name == "scipy_nelder_mead":
        options["maxiter"] = max_trials
    elif optimizer_name == "scipy_de":
        options.update({"max_trials": max_trials, "popsize": popsize, "tol": 1e-4})
    elif optimizer_name == "grid":
        finest = max(2, int(max_trials ** (1 / space.dim) + 1e-9))
        options["points_per_dim"] = grid_points or finest

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        sim = case.simulate(sugg.values)
        obj = evaluate_objective(objective, sim)
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=sim.sim_id,
            cost=obj.total,
            components=dict(obj.components),
            status="completed",
            metadata={"values": dict(sugg.values)},
        )

    engine = CalibrationEngine(
        space=space,
        optimizer=build_optimizer(optimizer_name, space, **options),
        evaluator=evaluator,
        max_trials=max_trials,
    )
    return engine, objective


def standalone_parser(description: str, max_trials: int, seed: int) -> argparse.ArgumentParser:
    """Return the command line every standalone experiment shares."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--optimizer",
        default="scipy_nelder_mead",
        choices=("scipy_nelder_mead", "scipy_de", "grid"),
    )
    parser.add_argument("--max-trials", type=int, default=max_trials)
    parser.add_argument("--seed", type=int, default=seed)
    return parser


def run_and_print(engine: CalibrationEngine, optimizer: str, truth: Any) -> None:
    """Run the search and print what it found beside the truth."""
    session = engine.run()
    completed = [r for r in session.history if r.status == "completed"]
    best = min(completed, key=lambda r: r.cost)
    print(f"optimizer        : {optimizer}")
    print(f"iterations       : {len(completed)}")
    print(f"best objective   : {best.cost:.6e}")
    print(f"best values      : {best.metadata.get('values')}")
    print(f"truth values     : {dict(truth)}")
    print(f"duration_s       : {session.duration_s:.2f}")


__all__ = ["build_standalone_calibration", "run_and_print", "standalone_parser"]
