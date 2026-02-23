"""Calibration-case implementation for the Brutsaert recession example."""

from __future__ import annotations

from typing import Any, Mapping

from hydromodpy.calibration2.analysis.diagnostics import compute_performance_metrics
from hydromodpy.calibration2.core.case_interface import (
    AbstractCalibrationCase,
    CalibrationCaseContext,
)
from hydromodpy.calibration2.cases.recession_brutsaert.case_config import (
    validate_brutsaert_chronicle_config,
)
from hydromodpy.calibration2.cases.recession_brutsaert.workflow import (
    MODEL_PARAMETER_ORDER,
    BaseflowConfig,
    build_noisy_coarse_sand_chronicle,
    make_baseflow_simulator,
)


def _true_baseflow_parameters(chronicle_params):
    """Return model parameters used to generate the synthetic truth."""
    return {
        "K": float(chronicle_params["K"]),
        "Sy": float(chronicle_params["Sy"]),
    }


class BrutsaertCalibrationCase(AbstractCalibrationCase):
    """Brutsaert recession implementation of the generic calibration interface."""

    CASE_NAME = "recession_brutsaert"

    def validate_case_config(
        self,
        chronicle_section: Mapping[str, Any],
        *,
        calibration_section: Mapping[str, Any],
        full_config: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Validate and normalize Brutsaert chronicle config."""
        _ = calibration_section, full_config
        return validate_brutsaert_chronicle_config(chronicle_section)

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
        _ = calibration_section, full_config
        chronicle = build_noisy_coarse_sand_chronicle(case_config)
        params = chronicle["params"]
        model_config = BaseflowConfig(
            Q0=float(params["Q0"]),
            solution=str(params["solution"]),
            b=params.get("b"),
            A=params.get("A"),
            L=params.get("L"),
            ag=float(params.get("ag", 0.7)),
            p=float(params.get("p", 0.346)),
        )
        simulator = make_baseflow_simulator(
            t_seconds=chronicle["t_seconds"],
            model_config=model_config,
        )
        return CalibrationCaseContext(
            observed=chronicle["q_obs"],
            simulator=simulator,
            parameter_order=MODEL_PARAMETER_ORDER,
            chronicle=chronicle,
            metadata={},
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
        Build Brutsaert-specific diagnostics payload from a generic calibration result.
        """
        _ = case_config, config
        chronicle = dict(case_context.chronicle or {})
        parameter_names = tuple(settings["parameter_names"])
        true_params_all = _true_baseflow_parameters(chronicle["params"])

        params_best = dict(result.params_best)
        params_true = {name: float(true_params_all[name]) for name in parameter_names}
        q_calib = calibration_engine.simulate(result.x_best)
        all_metrics = compute_performance_metrics(
            observed=calibration_engine.observed,
            simulated=q_calib,
            nse_log_floor=None,
        )
        return {
            "result_final": result,
            "global_method": settings["method"],
            "params_best": params_best,
            "params_true": params_true,
            "q_calib": q_calib,
            "metrics": all_metrics,
        }


CASE_IMPLEMENTATION = BrutsaertCalibrationCase()


__all__ = (
    "BrutsaertCalibrationCase",
    "CASE_IMPLEMENTATION",
)
