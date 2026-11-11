"""PETSc ``flow/boussinesq`` runtime for the steady linearized drainage benchmark."""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_uniform_strip import run_boussinesq_uniform_strip_case

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "linearized_unconfined_drainage_1d"
NX = 50
# Right triangles of dx = dy = 2 m, all of area 2 m2: the conductance of the
# solver is one scalar per cell, so K * A / b is the leakance K / b only when
# every cell has the same area.
NY = 5
LENGTH_X_M = 100.0
WIDTH_Y_M = 10.0
STORAGE_COEFFICIENT = 0.1


def run_boussinesq_linearized_unconfined_drainage_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    public_solver_label: str = "boussinesq",
) -> object:
    """Run the steady linearized drainage case on the PETSc VI obstacle engine.

    The drain is ``C * max(h - z_top, 0)`` with the explicit conductance
    ``C = K * A / b`` in m2/s. A positive value is what lifts the upper
    obstacle of the VI engine; zero would derive ``K * A / b`` but keep the
    head under the surface.
    """
    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    output_cfg = dict(metadata.get("output", {}))
    expected_shape = tuple(output_cfg["expected_shape"])
    if expected_shape != (NY, NX):
        raise ValueError(f"The strip is {NY} x {NX}, metadata expects {expected_shape}.")

    hydraulic_conductivity = float(reference_cfg["hydraulic_conductivity_m_per_s"])
    drain_bed_thickness_m = float(reference_cfg["drain_bed_thickness_m"])
    cell_area_m2 = 0.5 * (LENGTH_X_M / NX) * (WIDTH_Y_M / NY)
    drain_conductance_m2_s = hydraulic_conductivity * cell_area_m2 / drain_bed_thickness_m
    west_head_m = float(reference_cfg["west_head_m"])
    east_head_m = float(reference_cfg["east_head_m"])
    drainage_elevation_m = float(reference_cfg["drainage_elevation_m"])

    flow_section = {
        "flow_regime": "steady",
        "ic": {"kind": "custom", "value": 0.5 * (west_head_m + east_head_m)},
        "bc": {
            "west_side": {"value": west_head_m},
            "east_side": {"value": east_head_m},
            "drainage": {
                "application_domain": "top",
                "value": drain_conductance_m2_s,
            },
        },
    }
    return run_boussinesq_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id=CASE_ID,
        caller_file=caller_file,
        timeout=timeout,
        nx=NX,
        ny=NY,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=drainage_elevation_m,
        z_bottom_m=drainage_elevation_m - float(reference_cfg["aquifer_thickness_m"]),
        hydraulic_conductivity_m_s=hydraulic_conductivity,
        storage_coefficient=STORAGE_COEFFICIENT,
        flow_section=flow_section,
        plan_name="Boussinesq linearized drainage validation",
        plan_description="Steady 1D strip with fixed side heads and a finite-conductance top drain",
        public_solver_label=public_solver_label,
    )


__all__ = ["run_boussinesq_linearized_unconfined_drainage_case"]
