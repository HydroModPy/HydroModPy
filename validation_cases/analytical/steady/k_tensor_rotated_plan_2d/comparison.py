"""Comparison of the plan-view strip with a rotated horizontal K tensor.

The comparison reads the cells of a window in the middle of the strip, where
the end effects are below the solver closure. There the head must be a plane
whose slope across the strip is ``r = -K_xy / K_yy`` times its slope along it,
and the flow into the west end and out of the east end must be
``K_eff (-dh/dx) w b``. The slope along the strip is fitted: it depends on the
end effects, which have no closed form. The direction and the flux do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from validation_cases.analytical.steady.k_tensor_strip import (
    StoredStrip,
    StripFit,
    StripTensor,
    fit_strip,
    load_stored_strip,
    tensor_mismatch,
)
from validation_cases.shared import (
    ValidationRunResult,
    load_case_metadata,
    load_case_tolerances,
    run_launcher_validation_case,
)
from validation_cases.shared.loaders import map_polygons_payload

from .reference import plan_tensor

CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class RotatedPlanComparison:
    """One run against the exact uniform flow of its ANGLE1.

    ``profile_y_m``, ``profile_numerical`` and ``profile_reference`` are the
    heads across the strip at its middle column. The map holds the window.
    """

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    stored: StoredStrip
    angle1_deg: float
    tensor: StripTensor
    window: np.ndarray
    fit: StripFit
    tensor_input_mismatch: float
    profile_y_m: np.ndarray
    profile_numerical: np.ndarray
    profile_reference: np.ndarray
    map_cell_polygons: list[list[tuple[float, float]]]
    map_simulated: np.ndarray
    map_reference: np.ndarray


def build_rotated_plan_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> RotatedPlanComparison:
    """Compare the stored heads and end flows of one run with the exact uniform flow."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(result.solver_name).strip().lower()
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )
    ref = dict(case_metadata["reference"])
    angle1 = float(dict(ref.get("angle1_deg_by_solver", {})).get(solver_name, ref["angle1_deg"]))
    k11, k22 = float(ref["k11_m_per_s"]), float(ref["k22_m_per_s"])
    tensor = plan_tensor(k11_m_per_s=k11, k22_m_per_s=k22, angle1_deg=angle1)
    length, width = float(ref["length_x_m"]), float(ref["length_y_m"])

    stored = load_stored_strip(result)
    s = np.broadcast_to(stored.x - 0.5 * length, stored.heads.shape)
    t = np.broadcast_to(stored.y - 0.5 * width, stored.heads.shape)
    window = np.abs(s) <= float(ref["window_half_length_m"])
    fit = fit_strip(
        tensor=tensor,
        stored=stored,
        s=s,
        t=t,
        window=window,
        cross_section_m2=width * float(ref["thickness_m"]),
    )

    heads, reference = stored.heads[0], fit.reference_heads[0]
    middle = np.isclose(stored.x, stored.x[np.argmin(np.abs(s[0]))])
    order = np.argsort(stored.y[middle])
    cells = np.flatnonzero(window[0])
    return RotatedPlanComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        stored=stored,
        angle1_deg=angle1,
        tensor=tensor,
        window=window,
        fit=fit,
        tensor_input_mismatch=tensor_mismatch(
            stored,
            {
                "hydraulic_conductivity": k11,
                "hydraulic_conductivity_k22": k22,
                "conductivity_tensor_angle1": angle1,
            },
        ),
        profile_y_m=stored.y[middle][order],
        profile_numerical=heads[middle][order],
        profile_reference=reference[middle][order],
        map_cell_polygons=map_polygons_payload(
            [stored.polygons[i] for i in cells], origin_x=0.0, origin_y=0.0
        ),
        map_simulated=heads[cells],
        map_reference=reference[cells],
    )


def run_rotated_plan_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 600,
    solver: str | None = None,
) -> RotatedPlanComparison:
    """Run one variant through ``hmp run`` and compare it with the exact uniform flow."""
    result = run_launcher_validation_case(
        case_dir=CASE_DIR,
        test_file=caller_file,
        timeout=timeout,
        solver=solver,
    )
    return build_rotated_plan_comparison(result=result)


__all__ = [
    "RotatedPlanComparison",
    "build_rotated_plan_comparison",
    "run_rotated_plan_comparison",
]
