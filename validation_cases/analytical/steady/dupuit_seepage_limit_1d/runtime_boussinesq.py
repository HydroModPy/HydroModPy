"""``flow/boussinesq`` runtime for the Dupuit seepage-limit case.

The strip has no lateral boundary: it is closed on both sides and drains
through its surface. The PETSc VI obstacle holds the head at the surface with
an exact complementarity. The default local engine releases the water above the
surface through a regularized partition, so a cell that seeps is read from its
head (within ``SEEPAGE_BAND_M`` of the surface), and the water that leaves is the
``surface_excess`` flux, which these runtimes carry where a MODFLOW run carries
``drain``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.mesh.io.bundle import load_catchment_mesh_bundle
from hydromodpy.model.flow import Flow
from hydromodpy.solver.boussinesq.assembly.fluxes import saturated_thickness_from_head
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.state import BoussinesqState
from validation_cases.shared import load_case_metadata
from validation_cases.shared.boussinesq_analytical_runtime import (
    boussinesq_bundle_model,
    boussinesq_variant_flow_section,
    boussinesq_variant_options,
)
from validation_cases.shared.boussinesq_uniform_strip import (
    build_flow_config,
    write_uniform_strip_bundle,
)
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
    write_validation_fields_to_store,
)

CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "dupuit_seepage_limit_1d"

BOUSSINESQ_BACKENDS = frozenset({"boussinesq", "boussinesq_local"})

NX = 80
NY = 2
LENGTH_X_M = 400.0
WIDTH_Y_M = 10.0
SLOPE = 0.02
STORAGE_COEFFICIENT = 0.1
SEEPAGE_BAND_M = 1e-6
"""A head this close to the surface, or above it, is a seeping head (m)."""
TOP_FLOOR_M = 1e-6
"""The bundle writer wants the surface strictly above the bottom, also at the toe (m)."""

# Conductivity (m/s) and recharge (mm/day) of the four scenarios, as the
# MODFLOW configs of the case state them.
SCENARIO_FORCING = {
    "": (2.5e-4, 8.64),
    "_scaled_down": (2.5e-6, 0.0864),
    "_scaled_up": (2.5e-2, 864.0),
    "_k_only": (5.0e-4, 8.64),
}


def _split_scenario(scenario: str) -> tuple[str, str]:
    """Return the solver and the suffix of a scenario key."""
    name = str(scenario).strip().lower()
    for suffix in ("_scaled_down", "_scaled_up", "_k_only"):
        if name.endswith(suffix):
            return name[: -len(suffix)], suffix
    return name, ""


def boussinesq_scenario_forcing(scenario: str) -> tuple[float, float]:
    """Return ``(K, R)`` in SI units of one Boussinesq scenario."""
    _, suffix = _split_scenario(scenario)
    conductivity, recharge_mm_day = SCENARIO_FORCING[suffix]
    return conductivity, recharge_mm_day / 1000.0 / 86400.0


def _bin_indices(model) -> tuple[np.ndarray, np.ndarray]:
    """Return the column and the row of each triangle on the ``NY x NX`` grid."""
    dx = (float(model.mesh.x_max_m) - float(model.mesh.x_min_m)) / NX
    dy = (float(model.mesh.y_max_m) - float(model.mesh.y_min_m)) / NY
    col = np.floor((np.asarray(model.mesh.cell_centroid_x_m) - float(model.mesh.x_min_m)) / dx)
    row = np.floor((np.asarray(model.mesh.cell_centroid_y_m) - float(model.mesh.y_min_m)) / dy)
    return np.clip(col.astype(int), 0, NX - 1), np.clip(row.astype(int), 0, NY - 1)


def _bin(values: np.ndarray, col: np.ndarray, row: np.ndarray, *, total: bool) -> np.ndarray:
    """Return the mean (or the sum) of the triangle values of each bin of the grid."""
    flat = row * NX + col
    summed = np.bincount(flat, weights=np.asarray(values, dtype=float), minlength=NX * NY)
    counts = np.bincount(flat, minlength=NX * NY)
    if np.any(counts == 0):
        raise AssertionError("Every structured validation bin must receive at least one triangle.")
    return (summed if total else summed / counts).reshape(NY, NX)


def _solve_steady(
    *,
    bundle_parent: Path,
    flow_section: dict,
    config_name: str,
    solver: str,
    conductivity: float,
    substratum: float,
    start_head: np.ndarray | None = None,
):
    """Build the strip for one conductivity, solve it at steady state, return the model.

    ``solver`` is the label of the variant, which picks the Boussinesq settings.
    ``start_head`` replaces the flat start of the config when given.
    """
    bundle_dir = write_uniform_strip_bundle(
        bundle_parent / "mesh_bundle",
        nx=NX,
        ny=NY,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=lambda x_m: substratum + SLOPE * (LENGTH_X_M - x_m) + TOP_FLOOR_M,
        z_bottom_m=substratum,
        hydraulic_conductivity_m_s=conductivity,
        storage_coefficient=STORAGE_COEFFICIENT,
    )
    simulations_folder = bundle_parent / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)
    flow = Flow(build_flow_config(flow_section, case_dir=CASE_DIR, config_name=config_name))
    model = Boussinesq(
        mesh_bundle=load_catchment_mesh_bundle(bundle_dir),
        model=boussinesq_bundle_model(flow),
        runtime=boussinesq_variant_options(
            flow_regime="steady", solver=solver, case_dir=CASE_DIR, config_name=config_name
        ),
        model_folder=simulations_folder,
        model_name="flow_validation__boussinesq",
    )
    model.pre_processing()
    model._assert_supported_runtime_subset()
    model.state = model._build_initial_state()
    if start_head is not None:
        head = np.array(start_head, dtype=float)
        model.state = BoussinesqState(
            head_m=head,
            saturated_thickness_m=saturated_thickness_from_head(model.mesh, head),
        )
    model.solve_stage = "initialized"
    if not bool(model._run_steady_runtime()):
        model.has_numerical_solution = False
        model.solve_stage = "failed"
        summary = model.runtime_summary
        raise RuntimeError(
            "Boussinesq seepage-limit steady solve did not converge: "
            f"residual_inf={float(summary.get('steady_residual_norm_inf', np.inf)):.6g} "
            f"after {summary.get('steady_nonlinear_iterations')} iterations "
            f"({summary.get('steady_termination_reason')}), workspace={model.full_path}"
        )
    model.has_numerical_solution = True
    model.solve_stage = "solved"
    model.post_processing()
    return model


def run_boussinesq_seepage_limit_case(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    scenario: str = "boussinesq",
) -> ValidationRunResult:
    """Run one scenario of the seepage-limit case on one Boussinesq engine.

    The doubled-K control of the default engine starts from the solution of the
    reference scenario. From a flat start, whatever the level, the dense Newton
    of the partition closure drives the toe cells below the bottom and its
    Jacobian solve fails; the control is a different problem from the reference
    one, so the warm start does not hand it the answer.
    """
    del timeout
    backend, suffix = _split_scenario(scenario)
    if backend not in BOUSSINESQ_BACKENDS:
        raise ValueError(f"{scenario!r} is not a Boussinesq scenario.")
    conductivity, recharge = boussinesq_scenario_forcing(scenario)
    metadata = load_case_metadata(CASE_DIR)
    config_files = dict(metadata["config_files"])
    substratum = float(dict(metadata["reference"])["substratum_elevation_m"])

    out_path = resolve_validation_results_dir(
        test_file=caller_file,
        run_name=f"{CASE_ID}_{scenario}",
    )
    flow_section = boussinesq_variant_flow_section(
        {
            "flow_regime": "steady",
            "sinks_sources": {
                "recharge": {"values": recharge, "first_clim": "mean", "units": "m/s"}
            },
        },
        flow_regime="steady",
    )

    start_head = None
    if backend == "boussinesq_local" and suffix == "_k_only":
        reference_model = _solve_steady(
            bundle_parent=out_path / "reference_start",
            flow_section=flow_section,
            config_name=str(config_files[backend]),
            solver=backend,
            conductivity=boussinesq_scenario_forcing(backend)[0],
            substratum=substratum,
        )
        start_head = np.asarray(reference_model.state.head_history_m, dtype=float)[-1]
    model = _solve_steady(
        bundle_parent=out_path,
        flow_section=flow_section,
        config_name=str(config_files[scenario]),
        solver=backend,
        conductivity=conductivity,
        substratum=substratum,
        start_head=start_head,
    )

    head = np.asarray(model.state.head_history_m, dtype=float)[-1]
    top = np.asarray(model.mesh.z_top_m, dtype=float)
    excess_m3_s = np.asarray(model.state.saturation_excess_history_m_s, dtype=float)[
        -1
    ] * np.asarray(model.mesh.cell_area_m2, dtype=float)
    col, row = _bin_indices(model)
    head_grid = _bin(head, col, row, total=False)
    top_grid = _bin(top, col, row, total=False)
    fields = {
        "watertable_elevation": {0: head_grid},
        "topography": {0: top_grid},
        # The canonical mask of a Boussinesq run comes from the surface-excess flux,
        # which the partition closure releases nearly everywhere: read the heads.
        "seepage_mask": {0: (head_grid >= top_grid - SEEPAGE_BAND_M).astype(float)},
        # The water that leaves through the surface, where a MODFLOW run has its drains.
        "drain": {0: -_bin(excess_m3_s, col, row, total=True)},
    }

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    store, sim_id = write_validation_fields_to_store(
        out_path=out_path,
        fields=fields,
        solver_name="boussinesq",
    )
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name=scenario,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=postprocess_dir / "_particles",
        run_returncode=0,
        run_stdout="",
        run_stderr="",
        store=store,
        sim_id=sim_id,
    )


__all__ = [
    "BOUSSINESQ_BACKENDS",
    "SCENARIO_FORCING",
    "boussinesq_scenario_forcing",
    "run_boussinesq_seepage_limit_case",
]
