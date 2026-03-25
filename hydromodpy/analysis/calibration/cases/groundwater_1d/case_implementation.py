"""Calibration-case implementation for the transient 1D groundwater example."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from hydromodpy.analysis.calibration.core.case_interface import (
    AbstractCalibrationCase,
    CalibrationCaseContext,
)
from hydromodpy.analysis.calibration.cases.groundwater_1d.case_config import (
    validate_groundwater_1d_chronicle_config,
)
from hydromodpy.analysis.calibration.cases.groundwater_1d.workflow import (
    MODEL_PARAMETER_ORDER,
    build_noisy_groundwater_chronicle,
    evaluate_metrics,
    make_groundwater_simulator,
    run_simulation_for_params,
)


class Groundwater1DCalibrationCase(AbstractCalibrationCase):
    """
    Groundwater 1D implementation of the generic calibration case interface.
    """

    CASE_NAME = "groundwater_1d"

    def validate_case_config(
        self,
        chronicle_section: Mapping[str, Any],
        *,
        calibration_section: Mapping[str, Any],
        full_config: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        _ = calibration_section, full_config
        return validate_groundwater_1d_chronicle_config(chronicle_section)

    def build_case(
        self,
        case_config: Mapping[str, Any],
        *,
        calibration_section: Mapping[str, Any],
        full_config: Mapping[str, Any],
    ) -> CalibrationCaseContext:
        _ = calibration_section, full_config
        chronicle = build_noisy_groundwater_chronicle(case_config)
        simulator = make_groundwater_simulator(chronicle)
        return CalibrationCaseContext(
            observed=np.asarray(chronicle["obs_vector"], dtype=float),
            simulator=simulator,
            parameter_order=MODEL_PARAMETER_ORDER,
            chronicle=chronicle,
            metadata={"formulation_true": case_config["formulation_true"]},
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
        _ = config, case_config
        chronicle = dict(case_context.chronicle or {})
        parameter_names = tuple(settings["parameter_names"])

        params_best = dict(result.params_best)
        params_true_all = dict(chronicle["true_params"])
        params_true = {name: float(params_true_all[name]) for name in parameter_names}

        obs_sim_best_vector = calibration_engine.simulate(result.x_best)
        simulation_best = run_simulation_for_params(chronicle, params_best)
        metrics = evaluate_metrics(
            observed=chronicle["obs_vector"],
            simulated=obs_sim_best_vector,
        )

        return {
            "result_final": result,
            "global_method": settings["method"],
            "params_best": params_best,
            "params_true": params_true,
            "obs_sim_best_vector": obs_sim_best_vector,
            "simulation_best": simulation_best,
            "metrics": metrics,
        }


CASE_IMPLEMENTATION = Groundwater1DCalibrationCase()


__all__ = (
    "Groundwater1DCalibrationCase",
    "CASE_IMPLEMENTATION",
)


