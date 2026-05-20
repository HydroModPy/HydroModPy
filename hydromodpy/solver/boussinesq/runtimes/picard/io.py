"""Diagnostic JSON/CSV writers for the Picard/L-scheme runtimes."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import saturated_thickness_from_head
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
)
from hydromodpy.solver.boussinesq.runtimes import petsc_vi_obstacle
from hydromodpy.solver.boussinesq.runtimes.picard.diagnostics import (
    PicardIterationRecord,
    PicardLschemeOptions,
    PicardViCycleOptions,
    PicardViCycleRecord,
    active_state,
    cell_coord,
    cell_id,
    jsonable,
    neighbor_counts,
    physical_bounds,
    prescribed_head_cells,
)
from hydromodpy.solver.boussinesq.runtimes.picard.lscheme import picard_summary
from hydromodpy.solver.boussinesq.runtimes.picard.picard import assemble_strict_steady_residual

PICARD_LSCHEME_SUMMARY_JSON = "picard_lscheme_summary.json"
PICARD_LSCHEME_ITERATIONS_CSV = "picard_lscheme_iterations.csv"
PICARD_LSCHEME_FINAL_CELLS_CSV = "picard_lscheme_final_cells.csv"
PICARD_VI_CYCLE_SUMMARY_JSON = "picard_vi_cycle_summary.json"
PICARD_VI_CYCLES_CSV = "picard_vi_cycles.csv"


def final_cell_fieldnames() -> list[str]:
    """Return ordered CSV fieldnames for the final-cells diagnostic."""
    return [
        "cell_id",
        "x",
        "y",
        "area",
        "K",
        "z_bottom",
        "z_top",
        "h",
        "h_minus_z_top",
        "h_minus_z_bottom",
        "physical_saturated_thickness",
        "transmissivity",
        "residual",
        "projected_residual",
        "active_state",
        "drainage_rate",
        "n_neighbors",
    ]


def final_cell_rows(
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    top_n: int,
    inputs: SteadySolveInputs | None,
) -> list[dict[str, Any]]:
    """Build the per-cell diagnostic rows sorted by projected residual magnitude."""
    head = np.asarray(result.head_m, dtype=float).reshape(-1)
    prescribed = (
        prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
        if inputs is not None
        else prescribed_head_cells(None, n_cells=mesh.n_cells)
    )
    lower, upper, prescribed_mask = physical_bounds(mesh, prescribed)
    raw = (
        assemble_strict_steady_residual(
            mesh,
            head,
            recharge_rate_m_s=None if inputs is None else inputs.recharge_rate_m_s,
            well_flux_m3_s=None if inputs is None else inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed,
            drainage_conductance_m2_s=None if inputs is None else inputs.drainage_conductance_m2_s,
        )
        if inputs is not None
        else result.assembly
    )
    tol_h = 1.0e-9
    projected = petsc_vi_obstacle._projected_vi_residual(
        residual=np.asarray(raw.solver_residual, dtype=float),
        head_m=head,
        lower_m=lower,
        upper_m=upper,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    residual = np.asarray(raw.flow_residual_m3_s, dtype=float).reshape(-1)
    thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float) * thickness
    drainage = np.asarray(raw.drainage_flux_m3_s, dtype=float).reshape(-1)
    order = np.argsort(-np.abs(projected))
    if int(top_n) > 0:
        order = order[: int(top_n)]
    neighbor_count = neighbor_counts(mesh)
    rows: list[dict[str, Any]] = []
    for index in order:
        i = int(index)
        rows.append(
            {
                "cell_id": cell_id(mesh, i),
                "x": cell_coord(mesh, i, ("cell_centroid_x_m", "cell_x_m", "x")),
                "y": cell_coord(mesh, i, ("cell_centroid_y_m", "cell_y_m", "y")),
                "area": float(mesh.cell_area_m2[i]),
                "K": float(mesh.hydraulic_conductivity_m_s[i]),
                "z_bottom": float(mesh.z_bottom_m[i]),
                "z_top": float(mesh.z_top_m[i]),
                "h": float(head[i]),
                "h_minus_z_top": float(head[i] - mesh.z_top_m[i]),
                "h_minus_z_bottom": float(head[i] - mesh.z_bottom_m[i]),
                "physical_saturated_thickness": float(thickness[i]),
                "transmissivity": float(transmissivity[i]),
                "residual": float(residual[i]),
                "projected_residual": float(projected[i]),
                "active_state": active_state(
                    head=float(head[i]),
                    lower=float(lower[i]),
                    upper=float(upper[i]),
                    prescribed=bool(prescribed_mask[i]),
                    tol_h=tol_h,
                ),
                "drainage_rate": float(drainage[i]),
                "n_neighbors": int(neighbor_count[i]),
            }
        )
    return rows


def write_picard_lscheme_diagnostics(
    diagnostics_dir: str | Path,
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    options: PicardLschemeOptions,
    records: list[PicardIterationRecord],
    case_id: str,
    summary: dict[str, Any] | None = None,
    inputs: SteadySolveInputs | None = None,
) -> None:
    """Persist Picard JSON/CSV diagnostics."""
    out = Path(diagnostics_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = summary or picard_summary(
        mesh=mesh,
        result=result,
        options=options,
        records=records,
        case_id=case_id,
        stop_reason=str((result.diagnostics or {}).get("picard_stop_reason", "")),
        usable_as_initial_guess=bool(
            (result.diagnostics or {}).get("usable_as_initial_guess", result.converged)
        ),
        initial_residual=float((result.diagnostics or {}).get("residual_initial", math.nan)),
        Lstab_final=float((result.diagnostics or {}).get("Lstab", math.nan)),
        omega_final=float((result.diagnostics or {}).get("omega_final", math.nan)),
        runtime_seconds=float((result.diagnostics or {}).get("runtime_seconds", math.nan)),
        final_vi_result=None,
        final_vi_error=None,
    )
    (out / PICARD_LSCHEME_SUMMARY_JSON).write_text(
        json.dumps(jsonable(payload), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    with (out / PICARD_LSCHEME_ITERATIONS_CSV).open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(PicardIterationRecord.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(jsonable(record.__dict__))

    rows = final_cell_rows(
        mesh=mesh,
        result=result,
        top_n=int(options.picard_top_n_cells),
        inputs=inputs,
    )
    fieldnames = list(rows[0].keys()) if rows else final_cell_fieldnames()
    with (out / PICARD_LSCHEME_FINAL_CELLS_CSV).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_picard_vi_cycle_diagnostics(
    diagnostics_dir: str | Path,
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    options: PicardViCycleOptions,
    records: list[PicardViCycleRecord],
    summary: dict[str, Any],
    inputs: SteadySolveInputs,
) -> None:
    """Persist Picard/VI cycle JSON/CSV diagnostics."""
    out = Path(diagnostics_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / PICARD_VI_CYCLE_SUMMARY_JSON).write_text(
        json.dumps(jsonable(summary), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    with (out / PICARD_VI_CYCLES_CSV).open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(PicardViCycleRecord.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(jsonable(record.__dict__))
    rows = final_cell_rows(
        mesh=mesh,
        result=result,
        top_n=int(options.picard_options.picard_top_n_cells),
        inputs=inputs,
    )
    fieldnames = list(rows[0].keys()) if rows else final_cell_fieldnames()
    with (out / PICARD_LSCHEME_FINAL_CELLS_CSV).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
