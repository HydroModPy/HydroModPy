# -*- coding: utf-8 -*-
"""Calibration-case implementation for the reservoir example."""

from __future__ import annotations

from typing import Any, Mapping

from hydromodpy.calibration.core.case_interface import (
    AbstractCalibrationCase,
    CalibrationCaseContext,
)
from hydromodpy.calibration.cases.reservoir.case_config import (
    validate_reservoir_chronicle_config,
)
from hydromodpy.calibration.cases.reservoir.synthetic_data import (
    build_noisy_reservoir_chronicle,
)
from hydromodpy.calibration.cases.reservoir.workflow import (
    DEFAULT_MODEL_NAME,
    MODEL_REGISTRY,
    evaluate_metrics,
    get_model_parameter_order,
    make_reservoir_simulator,
)


def _resolve_model_name_for_case(*, case_config, calibration_section):
    """Resolve selected reservoir structure from case/global config context."""
    raw_value = case_config.get("model_name", None)
    if raw_value is None:
        raw_value = calibration_section.get("model_name", DEFAULT_MODEL_NAME)
    model_name = str(raw_value).strip().lower()
    if model_name not in MODEL_REGISTRY:
        allowed_txt = ", ".join(sorted(MODEL_REGISTRY))
        raise ValueError(
            f"Unknown model_name '{model_name}'. Allowed canonical names: {allowed_txt}"
        )
    return model_name


class ReservoirCalibrationCase(AbstractCalibrationCase):
    """Reservoir implementation of the generic calibration case interface."""

    CASE_NAME = "reservoir"

    def validate_case_config(
        self,
        chronicle_section: Mapping[str, Any],
        *,
        calibration_section: Mapping[str, Any],
        full_config: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """
        Validate and normalize reservoir chronicle config.
        """
        _ = calibration_section, full_config
        return validate_reservoir_chronicle_config(chronicle_section)

    def build_case(
        self,
        case_config: Mapping[str, Any],
        *,
        calibration_section: Mapping[str, Any],
        full_config: Mapping[str, Any],
    ) -> CalibrationCaseContext:
        """
        Build observed series, simulator and parameter order for calibration.
        """
        _ = full_config
        model_name = _resolve_model_name_for_case(
            case_config=dict(case_config),
            calibration_section=dict(calibration_section),
        )

        chronicle_cfg = dict(case_config)
        chronicle_cfg.pop("model_name", None)
        chronicle = build_noisy_reservoir_chronicle(
            chronicle_cfg,
            model_name=model_name,
        )
        simulator = make_reservoir_simulator(
            forcing_mm_day=chronicle["forcing_mm_day"],
            initial_state=chronicle["config"].initial_state,
            model_name=model_name,
            solver_backend=getattr(chronicle["config"], "solver_backend", "analytic"),
        )
        parameter_order = get_model_parameter_order(model_name)

        return CalibrationCaseContext(
            observed=chronicle["q_obs_mm_day"],
            simulator=simulator,
            parameter_order=parameter_order,
            chronicle=chronicle,
            metadata={"model_name": model_name},
        )

    def build_case_outputs(
        self,
        *,
        config: Mapping[str, Any],
        case_config: Mapping[str, Any],
        case_context: CalibrationCaseContext,
        calibration_engine,
        result,
        settings: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """
        Build reservoir-specific diagnostics payload from a generic calibration result.
        """
        _ = case_config, config
        chronicle = dict(case_context.chronicle or {})
        model_name = str(case_context.metadata.get("model_name", DEFAULT_MODEL_NAME))
        parameter_names = tuple(settings["parameter_names"])

        true_params_all = dict(chronicle["config"].true_params)
        params_best = dict(result.params_best)
        params_true = {name: float(true_params_all[name]) for name in parameter_names}
        q_calib_mm_day = calibration_engine.simulate(result.x_best)
        metrics = evaluate_metrics(
            observed=chronicle["q_obs_mm_day"],
            simulated=q_calib_mm_day,
            nse_log_floor=1e-8,
        )

        return {
            "model_name": model_name,
            "params_best": params_best,
            "params_true": params_true,
            "q_calib_mm_day": q_calib_mm_day,
            "metrics": metrics,
        }


CASE_IMPLEMENTATION = ReservoirCalibrationCase()


__all__ = (
    "ReservoirCalibrationCase",
    "CASE_IMPLEMENTATION",
)

