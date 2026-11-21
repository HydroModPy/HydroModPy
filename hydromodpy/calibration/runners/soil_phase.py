"""A calibration phase with ``regime = "soil"``: ru from the water budget, without a solver.

The capacity ``ru`` of the soil reservoir sets the yearly volume of recharge,
K and Sy set how the aquifer gives it back. Calibrating the three together
lets ``ru`` absorb what K and Sy miss, so the phase fixes ``ru`` first, on the
budget alone: the multi-year recharge plus runoff of the soil has to match the
gauged discharge. ``model/forcing/soil_ru_budget.py`` finds that capacity by
bisection, and this module only plays the data step of one fork of the
prepared trials, reads the answer and hands it to the next phases frozen, the
way a phase that searched would. No trial is run and none is recorded.
"""

from __future__ import annotations

import time
from typing import Any

from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.report import CalibrationReport, FrozenParameter
from hydromodpy.calibration.runners.trial import TrialContext, trial_pipeline
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.model.forcing.soil_budget import gauged_mm_per_day
from hydromodpy.model.forcing.soil_ru_budget import ru_closing_budget

SOIL_RU_PATH = "flow.sinks_sources.recharge.soil.ru"
DATA_STEP = "load_data"


def soil_phase_refusal(decl: CalibPhaseDecl, *, last: bool) -> str | None:
    """Say why a soil phase cannot run as declared, or None."""
    if decl.regime != "soil":
        return None
    if last:
        return (
            "it fixes ru for the phases after it and none follows: add the phase that "
            "calibrates K and Sy with ru fixed, after it."
        )
    if len(decl.parameters) != 1:
        return (
            f"it sets {SOIL_RU_PATH} from the water budget and nothing else, and it lists "
            f"{list(decl.parameters)}: list the one parameter that moves ru."
        )
    return None


def _soil_and_gauge(trial_ctx: TrialContext) -> tuple[Any, Any, float | None]:
    """The soil forcings, the loaded gauge and the catchment area after the data step."""
    forked = trial_ctx.fork({})
    steps = forked.downstream_steps
    names = [step.name for step in steps]
    ctx = forked.ctx
    if DATA_STEP in names and forked.earliest <= names.index(DATA_STEP):
        pipeline = trial_pipeline()
        state = pipeline.make_state(
            "calibration-soil-phase",
            {
                "cfg": ctx.cfg,
                "config_path": forked.cfg_path,
                "raw_toml": dict(forked.raw_toml),
                "ctx": ctx,
                "skip_display": True,
            },
        )
        pipeline.make_pipeline(steps[forked.earliest : names.index(DATA_STEP) + 1]).run(state)
    area = getattr(getattr(ctx.setup, "geographic", None), "catch_area", None)
    return ctx.setup.soil_forcings, ctx.loaded_data.hydrometry, area


def solve_soil_phase(
    trial_ctx: TrialContext,
    decl: CalibPhaseDecl,
    space: ParameterSpace,
    *,
    session_id: str,
    save_runs: str,
) -> tuple[CalibrationReport, tuple[FrozenParameter, ...]]:
    """Set ru to the capacity that closes the budget, and freeze it for the next phases."""
    started = time.monotonic()
    resolved = {param.name: param.effective_path for param in trial_ctx.parameter_space or ()}
    (name,) = decl.parameters
    if resolved.get(name) != SOIL_RU_PATH:
        raise CalibrationError(
            f'phase {decl.name!r} gives regime = "soil", which sets {SOIL_RU_PATH}, and '
            f"[calibration.parameters.{name}] moves {resolved.get(name)!r}: list the "
            "parameter that moves ru."
        )
    soil, hydrometry, area = _soil_and_gauge(trial_ctx)
    if soil is None:
        raise CalibrationError(
            f'phase {decl.name!r} gives regime = "soil", and the project has no '
            "[flow.sinks_sources.recharge.soil]: there is no ru to set."
        )
    gauged = gauged_mm_per_day(hydrometry, days=soil.days, catchment_area_km2=area)
    if isinstance(gauged, str):
        raise CalibrationError(
            f"phase {decl.name!r} closes the water budget against the gauge, and {gauged}: "
            "load the gauge at the outlet under [data.hydrometry]."
        )
    closure = ru_closing_budget(soil, gauged[0])
    if closure.ru_mm is None:
        raise CalibrationError(f"phase {decl.name!r} found no ru: {closure.reason}.")
    for name in decl.parameters:
        low, high = space[name].lower, space[name].upper
        if not low <= closure.ru_mm <= high:
            raise CalibrationError(
                f"phase {decl.name!r} closes the budget at ru = {closure.ru_mm:.0f} mm, outside "
                f"the bounds [{low:g}, {high:g}] of [calibration.parameters.{name}]: widen "
                "them, or check the rain and the catchment area."
            )
    values = {name: float(closure.ru_mm) for name in decl.parameters}
    report = CalibrationReport(
        session_id=session_id,
        method="water_budget",
        n_trials=0,
        best_cost=0.0,
        duration_s=time.monotonic() - started,
        save_runs=save_runs,
        promoted=0,
        cost_name="budget_closure",
        cost_label="recharge plus runoff against the gauge, closed by bisection on ru",
        best_parameters=values,
        extra={
            "search_status": "completed",
            "ru_closure": {
                "ru_mm": closure.ru_mm,
                "band_mm": None if closure.band_mm is None else list(closure.band_mm),
                "years": closure.years,
                "rain_minus_5_mm": closure.rain_minus_5_mm,
                "rain_plus_5_mm": closure.rain_plus_5_mm,
                "gauge_minus_5_mm": closure.gauge_minus_5_mm,
                "gauge_plus_5_mm": closure.gauge_plus_5_mm,
            },
        },
    )
    if not decl.freeze_on_success:
        return report, ()
    frozen = tuple(
        FrozenParameter(parameter=space[name], value=values[name], phase=decl.name)
        for name in decl.parameters
    )
    return report, frozen


__all__ = ["SOIL_RU_PATH", "soil_phase_refusal", "solve_soil_phase"]
