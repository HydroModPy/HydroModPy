"""Comparison of the vertical section with a tilted K tensor.

The comparison reads the cells of every layer in a window in the middle of the
section, where the end effects are below the solver closure. There the head
must be a plane whose vertical slope is ``r = -K_xz / K_zz`` times its slope
along the section, and the flow into the west end and out of the east end must
be ``K_eff (-dh/dx) w D``. The slope along the section is fitted: it depends on
the end effects, which have no closed form. The direction and the flux do not.
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

from .reference import section_tensor

CASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class TiltedSectionComparison:
    """One run against the exact uniform flow of its ANGLE2.

    ``profile_z_m``, ``profile_numerical`` and ``profile_reference`` are the
    heads of the layers at the middle column, from the top down.
    """

    result: ValidationRunResult
    metadata: dict
    tolerances: dict
    stored: StoredStrip
    angle2_deg: float
    tensor: StripTensor
    window: np.ndarray
    fit: StripFit
    tensor_input_mismatch: float
    profile_z_m: np.ndarray
    profile_numerical: np.ndarray
    profile_reference: np.ndarray


def build_tilted_section_comparison(
    *,
    result: ValidationRunResult,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> TiltedSectionComparison:
    """Compare the stored heads and end flows of one run with the exact uniform flow."""
    case_metadata = load_case_metadata(CASE_DIR) if metadata is None else metadata
    solver_name = str(result.solver_name).strip().lower()
    case_tolerances = (
        load_case_tolerances(CASE_DIR, solver=solver_name) if tolerances is None else tolerances
    )
    ref = dict(case_metadata["reference"])
    angle2 = float(dict(ref.get("angle2_deg_by_solver", {})).get(solver_name, ref["angle2_deg"]))
    k11, k33 = float(ref["k11_m_per_s"]), float(ref["k33_m_per_s"])
    tensor = section_tensor(k11_m_per_s=k11, k33_m_per_s=k33, angle2_deg=angle2)
    length, thickness = float(ref["length_x_m"]), float(ref["thickness_m"])

    stored = load_stored_strip(result)
    s = np.broadcast_to(stored.x - 0.5 * length, stored.heads.shape)
    t = stored.z + 0.5 * thickness
    window = np.abs(s) <= float(ref["window_half_length_m"])
    fit = fit_strip(
        tensor=tensor,
        stored=stored,
        s=s,
        t=t,
        window=window,
        cross_section_m2=float(ref["length_y_m"]) * thickness,
    )

    middle = int(np.argmin(np.abs(s[0])))
    return TiltedSectionComparison(
        result=result,
        metadata=case_metadata,
        tolerances=case_tolerances,
        stored=stored,
        angle2_deg=angle2,
        tensor=tensor,
        window=window,
        fit=fit,
        tensor_input_mismatch=tensor_mismatch(
            stored,
            {
                "hydraulic_conductivity": k11,
                "hydraulic_conductivity_k33": k33,
                "conductivity_tensor_angle1": 0.0,
                "conductivity_tensor_angle2": angle2,
                "conductivity_tensor_angle3": 0.0,
            },
        ),
        profile_z_m=stored.z[:, middle],
        profile_numerical=stored.heads[:, middle],
        profile_reference=fit.reference_heads[:, middle],
    )


def run_tilted_section_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 600,
    solver: str | None = None,
) -> TiltedSectionComparison:
    """Run one variant through ``hmp run`` and compare it with the exact uniform flow."""
    result = run_launcher_validation_case(
        case_dir=CASE_DIR,
        test_file=caller_file,
        timeout=timeout,
        solver=solver,
    )
    return build_tilted_section_comparison(result=result)


__all__ = [
    "TiltedSectionComparison",
    "build_tilted_section_comparison",
    "run_tilted_section_comparison",
]
