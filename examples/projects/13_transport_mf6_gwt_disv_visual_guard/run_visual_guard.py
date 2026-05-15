from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.colors import LinearSegmentedColormap, PowerNorm, TwoSlopeNorm
from scipy.special import erfc, erfcx

EXAMPLE_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_DIR = EXAMPLE_ROOT / "cases"
DEFAULT_OUTPUT_DIR = EXAMPLE_ROOT / "outputs"

CONCENTRATION_CMAP = LinearSegmentedColormap.from_list(
    "concentration_white_zero",
    ["#ffffff", "#d8f3ff", "#73c8d2", "#2d8fbe", "#2f4b9a", "#7b1f86", "#c51b29"],
)


@dataclass(frozen=True)
class DomainConfig:
    length_m: float
    width_m: float
    nx: int
    ny: int
    perturbation_fraction: float
    seed: int
    max_area_ratio: float


@dataclass(frozen=True)
class FlowConfig:
    head_left_m: float
    head_right_m: float
    hydraulic_conductivity_m_per_day: float
    hydraulic_conductivity_pattern: str
    hydraulic_conductivity_factor: float
    hydraulic_conductivity_seed: int | None
    porosity: float


@dataclass(frozen=True)
class TransportConfig:
    duration_days: float
    n_snapshots: int
    source_concentration: float
    source_schedule: str
    pulse_end_day: float
    pulse_center_m: float | None
    pulse_width_m: float | None
    pulse_y_center_m: float | None
    pulse_y_width_m: float | None
    longitudinal_dispersivity_m: float
    transverse_dispersivity_m: float
    diffusion_m2_per_day: float


@dataclass(frozen=True)
class CaseConfig:
    name: str
    title: str
    description: str
    domain: DomainConfig
    flow: FlowConfig
    transport: TransportConfig
    source_path: Path


@dataclass(frozen=True)
class TriDisvMesh:
    vertices: np.ndarray
    faces: list[list[int]]
    centroids: np.ndarray
    areas: np.ndarray
    cell2d: list[tuple[Any, ...]]
    vertices_disv: list[tuple[int, float, float]]
    left_cells: np.ndarray
    right_cells: np.ndarray

    @property
    def n_cells(self) -> int:
        return len(self.faces)

    @property
    def area_ratio(self) -> float:
        return float(np.max(self.areas) / np.min(self.areas))


@dataclass(frozen=True)
class CaseResult:
    case: CaseConfig
    mode: str
    mesh: TriDisvMesh
    times_days: np.ndarray
    head: np.ndarray
    hydraulic_conductivity: np.ndarray
    flux_proxy: np.ndarray
    cell_peclet: np.ndarray
    concentration: np.ndarray
    signatures: dict[str, Any]


def load_case(path: Path) -> CaseConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    case = data["case"]
    domain = data["domain"]
    flow = data["flow"]
    transport = data["transport"]
    return CaseConfig(
        name=str(case["name"]),
        title=str(case["title"]),
        description=str(case["description"]),
        domain=DomainConfig(
            length_m=float(domain["length_m"]),
            width_m=float(domain["width_m"]),
            nx=int(domain["nx"]),
            ny=int(domain["ny"]),
            perturbation_fraction=float(domain["perturbation_fraction"]),
            seed=int(domain["seed"]),
            max_area_ratio=float(domain["max_area_ratio"]),
        ),
        flow=FlowConfig(
            head_left_m=float(flow["head_left_m"]),
            head_right_m=float(flow["head_right_m"]),
            hydraulic_conductivity_m_per_day=float(flow["hydraulic_conductivity_m_per_day"]),
            hydraulic_conductivity_pattern=str(
                flow.get("hydraulic_conductivity_pattern", "homogeneous")
            ),
            hydraulic_conductivity_factor=float(flow.get("hydraulic_conductivity_factor", 1.0)),
            hydraulic_conductivity_seed=(
                int(flow["hydraulic_conductivity_seed"])
                if "hydraulic_conductivity_seed" in flow
                else None
            ),
            porosity=float(flow["porosity"]),
        ),
        transport=TransportConfig(
            duration_days=float(transport["duration_days"]),
            n_snapshots=int(transport["n_snapshots"]),
            source_concentration=float(transport["source_concentration"]),
            source_schedule=str(transport["source_schedule"]),
            pulse_end_day=float(transport["pulse_end_day"]),
            pulse_center_m=(
                float(transport["pulse_center_m"]) if "pulse_center_m" in transport else None
            ),
            pulse_width_m=(
                float(transport["pulse_width_m"]) if "pulse_width_m" in transport else None
            ),
            pulse_y_center_m=(
                float(transport["pulse_y_center_m"]) if "pulse_y_center_m" in transport else None
            ),
            pulse_y_width_m=(
                float(transport["pulse_y_width_m"]) if "pulse_y_width_m" in transport else None
            ),
            longitudinal_dispersivity_m=float(transport["longitudinal_dispersivity_m"]),
            transverse_dispersivity_m=float(transport["transverse_dispersivity_m"]),
            diffusion_m2_per_day=float(transport["diffusion_m2_per_day"]),
        ),
        source_path=path,
    )


def load_cases(
    cases_dir: Path = DEFAULT_CASES_DIR, names: set[str] | None = None
) -> list[CaseConfig]:
    cases = [load_case(path) for path in sorted(cases_dir.glob("*.toml"))]
    if names is not None:
        cases = [case for case in cases if case.name in names]
    return cases


def build_triangular_disv_mesh(domain: DomainConfig) -> TriDisvMesh:
    nx = int(domain.nx)
    ny = int(domain.ny)
    length = float(domain.length_m)
    width = float(domain.width_m)
    dx = length / nx
    dy = width / ny

    x = np.linspace(0.0, length, nx + 1)
    y = np.linspace(0.0, width, ny + 1)
    xx, yy = np.meshgrid(x, y)
    vertices = np.column_stack([xx.ravel(), yy.ravel()])

    if domain.perturbation_fraction > 0.0:
        rng = np.random.default_rng(domain.seed)
        scale = float(domain.perturbation_fraction) * min(dx, dy)
        offsets = rng.uniform(-scale, scale, size=vertices.shape)
        boundary = (
            np.isclose(vertices[:, 0], 0.0)
            | np.isclose(vertices[:, 0], length)
            | np.isclose(vertices[:, 1], 0.0)
            | np.isclose(vertices[:, 1], width)
        )
        vertices[~boundary] += offsets[~boundary]

    def node(i: int, j: int) -> int:
        return j * (nx + 1) + i

    faces: list[list[int]] = []
    for j in range(ny):
        for i in range(nx):
            ll = node(i, j)
            lr = node(i + 1, j)
            ul = node(i, j + 1)
            ur = node(i + 1, j + 1)
            if (i + j) % 2 == 0:
                faces.extend([[ll, lr, ur], [ll, ur, ul]])
            else:
                faces.extend([[ll, lr, ul], [lr, ur, ul]])

    oriented_faces = [_clockwise_face(vertices, face) for face in faces]
    centroids = np.asarray([vertices[face].mean(axis=0) for face in oriented_faces])
    areas = np.asarray([abs(_signed_area(vertices[face])) for face in oriented_faces])

    vertices_disv = [(idx, float(xy[0]), float(xy[1])) for idx, xy in enumerate(vertices)]
    cell2d = []
    for idx, face in enumerate(oriented_faces):
        xc, yc = centroids[idx]
        cell2d.append((idx, float(xc), float(yc), len(face), *[int(v) for v in face]))

    left_cells = np.asarray(
        [
            idx
            for idx, face in enumerate(oriented_faces)
            if np.any(np.isclose(vertices[face, 0], 0.0))
        ],
        dtype=int,
    )
    right_cells = np.asarray(
        [
            idx
            for idx, face in enumerate(oriented_faces)
            if np.any(np.isclose(vertices[face, 0], length))
        ],
        dtype=int,
    )

    return TriDisvMesh(
        vertices=vertices,
        faces=oriented_faces,
        centroids=centroids,
        areas=areas,
        cell2d=cell2d,
        vertices_disv=vertices_disv,
        left_cells=left_cells,
        right_cells=right_cells,
    )


def run_synthetic_case(case: CaseConfig) -> CaseResult:
    mesh = build_triangular_disv_mesh(case.domain)
    times = np.linspace(0.0, case.transport.duration_days, int(case.transport.n_snapshots))
    k_field = hydraulic_conductivity_field(case, mesh)
    head = synthetic_head(case, mesh)
    flux = synthetic_flux_proxy(case, mesh, k_field)
    cell_peclet = cell_peclet_numbers(case, mesh, k_field)
    concentration = synthetic_concentration(case, mesh, times)
    signatures = build_signatures(case, "synthetic", mesh, times, head, flux, concentration)
    return CaseResult(
        case=case,
        mode="synthetic",
        mesh=mesh,
        times_days=times,
        head=head,
        hydraulic_conductivity=k_field,
        flux_proxy=flux,
        cell_peclet=cell_peclet,
        concentration=concentration,
        signatures=signatures,
    )


def run_mf6_case(case: CaseConfig, output_dir: Path, mf6_exe: str | None = None) -> CaseResult:
    mf6_path = mf6_exe or shutil.which("mf6")
    if mf6_path is None:
        raise RuntimeError("MF6 executable not found. Use --mf6-exe or run --mode synthetic.")

    import flopy

    mesh = build_triangular_disv_mesh(case.domain)
    k_field = hydraulic_conductivity_field(case, mesh)
    cell_peclet = cell_peclet_numbers(case, mesh, k_field)
    sim_dir = output_dir / "mf6_workspace"
    sim_dir.mkdir(parents=True, exist_ok=True)

    nper = max(int(case.transport.n_snapshots) - 1, 1)
    perlen = float(case.transport.duration_days) / nper
    perioddata = [(perlen, 5, 1.0) for _ in range(nper)]

    sim = flopy.mf6.MFSimulation(
        sim_name=case.name,
        sim_ws=str(sim_dir),
        exe_name=str(mf6_path),
        version="mf6",
    )
    flopy.mf6.ModflowTdis(sim, time_units="DAYS", nper=nper, perioddata=perioddata)

    gwf_name = "gwf"
    gwf = flopy.mf6.ModflowGwf(sim, modelname=gwf_name, save_flows=True)
    gwf_ims = flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwf_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
    )
    sim.register_ims_package(gwf_ims, [gwf_name])
    _add_disv(gwf, mesh, case)
    flopy.mf6.ModflowGwfic(gwf, strt=case.flow.head_left_m)
    flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=0,
        k=k_field.reshape(1, mesh.n_cells),
        save_specific_discharge=True,
    )
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=0,
        ss=0.0,
        sy=0.0,
        steady_state={k: True for k in range(nper)},
    )
    chd_spd = {
        k: [
            *[((0, int(cell)), case.flow.head_left_m) for cell in mesh.left_cells],
            *[((0, int(cell)), case.flow.head_right_m) for cell in mesh.right_cells],
        ]
        for k in range(nper)
    }
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd, pname="CHD-1")
    flopy.mf6.ModflowGwfoc(
        gwf,
        budget_filerecord=f"{gwf_name}.cbc",
        head_filerecord=f"{gwf_name}.hds",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )

    gwt_name = "gwt"
    gwt = flopy.mf6.ModflowGwt(sim, modelname=gwt_name, save_flows=True)
    gwt_ims = flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwt_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
        linear_acceleration="BICGSTAB",
    )
    sim.register_ims_package(gwt_ims, [gwt_name])
    _add_disv(gwt, mesh, case)
    if case.transport.source_schedule == "internal_pulse":
        strt = _internal_pulse_solution(
            case,
            mesh.centroids[:, 0],
            mesh.centroids[:, 1],
            0.0,
            pore_velocity_field(case, mesh, k_field),
            effective_dispersion(case),
        ).reshape(1, mesh.n_cells)
    else:
        strt = 0.0
    flopy.mf6.ModflowGwtic(gwt, strt=strt)
    flopy.mf6.ModflowGwtadv(gwt, scheme="TVD")
    flopy.mf6.ModflowGwtdsp(
        gwt,
        xt3d_off=True,
        alh=case.transport.longitudinal_dispersivity_m,
        ath1=case.transport.transverse_dispersivity_m,
        diffc=case.transport.diffusion_m2_per_day,
    )
    flopy.mf6.ModflowGwtmst(gwt, porosity=case.flow.porosity)
    cnc_spd = {}
    for k in range(nper):
        period_start = k * perlen
        source = _source_at_period_start(case, period_start)
        cnc_spd[k] = [((0, int(cell)), source) for cell in mesh.left_cells] if source > 0 else []
    if case.transport.source_schedule == "internal_pulse":
        cnc_spd = {k: [] for k in range(nper)}
    flopy.mf6.ModflowGwtcnc(gwt, stress_period_data=cnc_spd)
    flopy.mf6.ModflowGwtoc(
        gwt,
        budget_filerecord=f"{gwt_name}.cbc",
        concentration_filerecord=f"{gwt_name}.ucn",
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
    )
    flopy.mf6.ModflowGwfgwt(
        sim,
        exgtype="GWF6-GWT6",
        exgmnamea=gwf_name,
        exgmnameb=gwt_name,
    )

    sim.write_simulation(silent=True)
    success, buff = sim.run_simulation(silent=True)
    if not success:
        raise RuntimeError("MF6 run failed:\n" + "\n".join(buff[-20:]))

    head_file = flopy.utils.HeadFile(sim_dir / f"{gwf_name}.hds")
    conc_file = flopy.utils.HeadFile(sim_dir / f"{gwt_name}.ucn", text="CONCENTRATION")
    raw_times = np.asarray(conc_file.get_times(), dtype=float)
    target_times = np.linspace(0.0, case.transport.duration_days, case.transport.n_snapshots)
    head_final = np.asarray(head_file.get_data(totim=raw_times[-1]), dtype=float).reshape(-1)[
        : mesh.n_cells
    ]
    if case.transport.source_schedule == "internal_pulse":
        initial_conc = _internal_pulse_solution(
            case,
            mesh.centroids[:, 0],
            mesh.centroids[:, 1],
            0.0,
            pore_velocity_field(case, mesh, k_field),
            effective_dispersion(case),
        )
    else:
        initial_conc = np.zeros(mesh.n_cells, dtype=float)
    conc = [initial_conc]
    selected_times = [0.0]
    for requested in target_times[1:]:
        idx = int(np.argmin(np.abs(raw_times - requested)))
        selected_times.append(float(raw_times[idx]))
        conc.append(
            np.asarray(conc_file.get_data(totim=raw_times[idx]), dtype=float).reshape(-1)[
                : mesh.n_cells
            ]
        )

    times = np.asarray(selected_times, dtype=float)
    concentration = np.vstack(conc)
    flux = synthetic_flux_proxy(case, mesh, k_field)
    signatures = build_signatures(case, "mf6", mesh, times, head_final, flux, concentration)
    return CaseResult(
        case=case,
        mode="mf6",
        mesh=mesh,
        times_days=times,
        head=head_final,
        hydraulic_conductivity=k_field,
        flux_proxy=flux,
        cell_peclet=cell_peclet,
        concentration=concentration,
        signatures=signatures,
    )


def render_case_report(result: CaseResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    write_signatures(result, output_dir)
    plot_context(result, figures_dir / "domain_context.png")
    plot_mesh_overview(result, figures_dir / "mesh_overview.png")
    plot_cell_field(
        result.mesh,
        result.hydraulic_conductivity,
        "Hydraulic conductivity K (m/day)",
        figures_dir / "hydraulic_conductivity.png",
        cmap="viridis",
    )
    plot_cell_field(
        result.mesh,
        result.head,
        "Final head (m)",
        figures_dir / "head_final.png",
        cmap="Blues",
    )
    plot_cell_field(
        result.mesh,
        result.flux_proxy,
        "Eastward flux proxy (m/day)",
        figures_dir / "flux_proxy.png",
        cmap="PuOr",
    )
    plot_cell_field(
        result.mesh,
        result.cell_peclet,
        "Cell Peclet number",
        figures_dir / "cell_peclet.png",
        cmap="magma",
    )
    plot_concentration_snapshots(result, figures_dir / "concentration_snapshots.png")
    plot_concentration_profiles(result, figures_dir / "concentration_profiles.png")
    plot_probe_breakthrough(result, figures_dir / "probe_breakthrough.png")
    plot_plume_evolution(result, figures_dir / "plume_evolution.png")
    if analytical_reference_available(result.case):
        plot_analytical_profile_comparison(
            result, figures_dir / "analytical_profile_comparison.png"
        )
        plot_analytical_error_diagnostics(result, figures_dir / "analytical_error_diagnostics.png")
    write_html(result, output_dir)


def write_signatures(result: CaseResult, output_dir: Path) -> None:
    (output_dir / "signatures.json").write_text(
        json.dumps(result.signatures, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    rows = result.signatures["time_signatures"]
    with (output_dir / "signatures.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_signatures(
    case: CaseConfig,
    mode: str,
    mesh: TriDisvMesh,
    times: np.ndarray,
    head: np.ndarray,
    flux: np.ndarray,
    concentration: np.ndarray,
) -> dict[str, Any]:
    rows = []
    k_field = hydraulic_conductivity_field(case, mesh)
    numbers = transport_diagnostics(case, mesh, k_field)
    analytical = analytical_concentration(case, mesh, times)
    analytical_available = analytical is not None
    velocity = float(numbers["pore_velocity_m_per_day"])
    for idx, (time, conc) in enumerate(zip(times, concentration, strict=True)):
        conc = np.asarray(conc, dtype=float)
        mass, center_x, width_x = plume_moments(mesh, conc)
        analytic_row = _empty_analytical_time_row()
        if analytical_available:
            analytic_conc = analytical[idx]
            analytical_mass, analytical_center_x, analytical_width_x = plume_moments(
                mesh, analytic_conc
            )
            error = conc - analytic_conc
            analytic_row = {
                "analytical_c_rmse": _round(_weighted_rmse(mesh, error)),
                "analytical_c_linf": _round(np.max(np.abs(error))),
                "analytical_mass": _round(analytical_mass),
                "analytical_center_x_m": _round(analytical_center_x),
                "analytical_width_x_m": _round(analytical_width_x),
                "analytical_mass_relative_error": _round(
                    (mass - analytical_mass) / max(abs(analytical_mass), 1.0e-14)
                ),
                "analytical_center_error_m": _round(center_x - analytical_center_x),
                "analytical_width_error_m": _round(width_x - analytical_width_x),
            }
        rows.append(
            {
                "snapshot": idx,
                "time_days": _round(time),
                "c_min": _round(np.min(conc)),
                "c_p05": _round(np.quantile(conc, 0.05)),
                "c_mean": _round(np.mean(conc)),
                "c_p50": _round(np.quantile(conc, 0.50)),
                "c_p95": _round(np.quantile(conc, 0.95)),
                "c_max": _round(np.max(conc)),
                "area_weighted_mass": _round(mass),
                "center_x_m": _round(center_x),
                "width_x_m": _round(width_x),
                "advective_distance_m": _round(min(velocity * float(time), case.domain.length_m)),
                **analytic_row,
            }
        )

    finite_conc = bool(np.isfinite(concentration).all())
    c_min = float(np.nanmin(concentration))
    c_max = float(np.nanmax(concentration))
    source = float(case.transport.source_concentration)
    finite_centers = [
        row["center_x_m"]
        for row in rows
        if isinstance(row["center_x_m"], float) and math.isfinite(row["center_x_m"])
    ]
    front_moves_downstream = len(finite_centers) < 2 or finite_centers[-1] > finite_centers[0]

    analytical_comparison = analytical_comparison_summary(
        case, mesh, concentration, analytical, rows, mode
    )

    checks = {
        "mesh_area_ratio_ok": mesh.area_ratio <= case.domain.max_area_ratio,
        "concentration_finite": finite_conc,
        "concentration_lower_bound_ok": c_min >= -1.0e-8,
        "concentration_upper_bound_ok": c_max <= source * 1.05 + 1.0e-8,
        "front_moves_downstream": bool(front_moves_downstream),
        "cell_peclet_reasonable": numbers["peclet_min"] >= 8.0 and numbers["peclet_max"] <= 130.0,
        "simulation_time_shows_plume_motion": case.transport.duration_days
        >= 0.5 * numbers["advective_travel_time_days"],
    }
    if analytical_comparison["available"]:
        checks["analytical_reference_rmse_ok"] = bool(
            analytical_comparison["rmse"] <= analytical_comparison["rmse_tolerance"]
        )
    return {
        "schema": "hydromodpy.transport_visual_guard.v1",
        "case": case.name,
        "mode": mode,
        "mesh": {
            "n_vertices": int(mesh.vertices.shape[0]),
            "n_cells": int(mesh.n_cells),
            "area_min_m2": _round(np.min(mesh.areas)),
            "area_max_m2": _round(np.max(mesh.areas)),
            "area_ratio": _round(mesh.area_ratio),
            "left_boundary_cells": int(mesh.left_cells.size),
            "right_boundary_cells": int(mesh.right_cells.size),
        },
        "flow": {
            "head_min_m": _round(np.min(head)),
            "head_max_m": _round(np.max(head)),
            "hydraulic_conductivity_min_m_per_day": _round(np.min(k_field)),
            "hydraulic_conductivity_mean_m_per_day": _round(np.mean(k_field)),
            "hydraulic_conductivity_max_m_per_day": _round(np.max(k_field)),
            "flux_proxy_mean_m_per_day": _round(np.mean(flux)),
        },
        "transport_numbers": numbers,
        "analytical_comparison": analytical_comparison,
        "checks": checks,
        "time_signatures": rows,
    }


def plume_moments(mesh: TriDisvMesh, concentration: np.ndarray) -> tuple[float, float, float]:
    conc = np.asarray(concentration, dtype=float)
    mass = float(np.sum(conc * mesh.areas))
    if mass <= 1.0e-14:
        return mass, float("nan"), float("nan")
    center_x = float(np.sum(conc * mesh.areas * mesh.centroids[:, 0]) / mass)
    width_x = float(
        math.sqrt(np.sum(conc * mesh.areas * (mesh.centroids[:, 0] - center_x) ** 2) / mass)
    )
    return mass, center_x, width_x


def analytical_reference_available(case: CaseConfig) -> bool:
    return (
        case.flow.hydraulic_conductivity_pattern == "homogeneous"
        and case.transport.source_schedule in {"internal_pulse", "constant", "pulse"}
    )


def analytical_reference_reason(case: CaseConfig) -> str:
    if case.transport.source_schedule not in {"internal_pulse", "constant", "pulse"}:
        return (
            "not available: the implemented closed-form references cover internal "
            "Gaussian pulses, constant upstream sources, and finite upstream pulses."
        )
    if case.flow.hydraulic_conductivity_pattern != "homogeneous":
        return "not available: heterogeneous K breaks the uniform-velocity analytical assumption."
    if case.transport.source_schedule == "constant":
        return "Ogata-Banks semi-infinite 1D reference for a constant upstream source."
    if case.transport.source_schedule == "pulse":
        return (
            "finite upstream pulse reference built as the difference between two "
            "Ogata-Banks step solutions."
        )
    return (
        "2D infinite-domain Gaussian advection-diffusion reference for a compact "
        "internal pulse with homogeneous K and uniform velocity."
    )


def analytical_concentration(
    case: CaseConfig, mesh: TriDisvMesh, times: np.ndarray
) -> np.ndarray | None:
    if not analytical_reference_available(case):
        return None
    velocity = float(_pore_velocity(case))
    dispersion = effective_dispersion(case)
    x = mesh.centroids[:, 0]
    if case.transport.source_schedule == "constant":
        return np.vstack(
            [
                _front_solution(
                    x,
                    float(time),
                    velocity,
                    dispersion,
                    case.transport.source_concentration,
                )
                for time in times
            ]
        )
    if case.transport.source_schedule == "pulse":
        return np.vstack(
            [
                np.clip(
                    _front_solution(
                        x,
                        float(time),
                        velocity,
                        dispersion,
                        case.transport.source_concentration,
                    )
                    - _front_solution(
                        x,
                        float(time) - case.transport.pulse_end_day,
                        velocity,
                        dispersion,
                        case.transport.source_concentration,
                    ),
                    0.0,
                    case.transport.source_concentration,
                )
                for time in times
            ]
        )
    y = mesh.centroids[:, 1]
    velocity_field = np.full(mesh.n_cells, velocity, dtype=float)
    return np.vstack(
        [
            _internal_pulse_solution(case, x, y, float(time), velocity_field, dispersion)
            for time in times
        ]
    )


def analytical_comparison_summary(
    case: CaseConfig,
    mesh: TriDisvMesh,
    concentration: np.ndarray,
    analytical: np.ndarray | None,
    rows: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    if analytical is None:
        return {
            "available": False,
            "reason": analytical_reference_reason(case),
        }
    error = np.asarray(concentration, dtype=float) - np.asarray(analytical, dtype=float)
    rmse = _weighted_space_time_rmse(mesh, error)
    linf = float(np.max(np.abs(error)))
    tolerance = 1.0e-10 if mode == "synthetic" else 8.0e-2
    final = rows[-1]
    return {
        "available": True,
        "reference": _analytical_reference_name(case),
        "reason": analytical_reference_reason(case),
        "rmse": _round(rmse),
        "linf": _round(linf),
        "rmse_tolerance": tolerance,
        "final_mass_relative_error": final["analytical_mass_relative_error"],
        "final_center_error_m": final["analytical_center_error_m"],
        "final_width_error_m": final["analytical_width_error_m"],
    }


def _analytical_reference_name(case: CaseConfig) -> str:
    if case.transport.source_schedule == "constant":
        return "ogata_banks_constant_upstream_source"
    if case.transport.source_schedule == "pulse":
        return "ogata_banks_finite_upstream_pulse"
    return "2d_infinite_domain_gaussian_internal_pulse"


def _empty_analytical_time_row() -> dict[str, None]:
    return {
        "analytical_c_rmse": None,
        "analytical_c_linf": None,
        "analytical_mass": None,
        "analytical_center_x_m": None,
        "analytical_width_x_m": None,
        "analytical_mass_relative_error": None,
        "analytical_center_error_m": None,
        "analytical_width_error_m": None,
    }


def _weighted_rmse(mesh: TriDisvMesh, values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    return float(math.sqrt(np.sum((arr**2) * mesh.areas) / np.sum(mesh.areas)))


def _weighted_space_time_rmse(mesh: TriDisvMesh, values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    return float(
        math.sqrt(np.sum((arr**2) * mesh.areas[None, :]) / (np.sum(mesh.areas) * arr.shape[0]))
    )


def synthetic_head(case: CaseConfig, mesh: TriDisvMesh) -> np.ndarray:
    x = mesh.centroids[:, 0]
    frac = x / float(case.domain.length_m)
    return case.flow.head_left_m + frac * (case.flow.head_right_m - case.flow.head_left_m)


def synthetic_flux_proxy(
    case: CaseConfig, mesh: TriDisvMesh, k_field: np.ndarray | None = None
) -> np.ndarray:
    if k_field is None:
        k_field = hydraulic_conductivity_field(case, mesh)
    gradient = (case.flow.head_left_m - case.flow.head_right_m) / case.domain.length_m
    return np.asarray(k_field, dtype=float) * gradient


def hydraulic_conductivity_field(case: CaseConfig, mesh: TriDisvMesh) -> np.ndarray:
    x = mesh.centroids[:, 0]
    y = mesh.centroids[:, 1]
    return hydraulic_conductivity_at(case, x, y)


def hydraulic_conductivity_at(case: CaseConfig, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    base = float(case.flow.hydraulic_conductivity_m_per_day)
    factor = max(float(case.flow.hydraulic_conductivity_factor), 1.0)
    pattern = case.flow.hydraulic_conductivity_pattern
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    k = np.full(np.broadcast_shapes(x.shape, y.shape), base, dtype=float)

    if pattern == "homogeneous":
        return k
    if pattern == "longitudinal_channel":
        y0 = case.domain.width_m / 3.0
        y1 = 2.0 * case.domain.width_m / 3.0
        return np.where((y >= y0) & (y <= y1), base * factor, base)
    if pattern == "transverse_bands":
        bands = np.floor(4.0 * x / case.domain.length_m).astype(int)
        return np.where((bands % 2) == 1, base * factor, base)
    if pattern == "random_blocks":
        seed = case.flow.hydraulic_conductivity_seed
        if seed is None:
            seed = case.domain.seed
        nx_blocks = 12
        ny_blocks = 4
        rng = np.random.default_rng(seed)
        block_values = np.exp(
            rng.uniform(math.log(base), math.log(base * factor), size=(ny_blocks, nx_blocks))
        )
        ix = np.clip((x / case.domain.length_m * nx_blocks).astype(int), 0, nx_blocks - 1)
        iy = np.clip((y / case.domain.width_m * ny_blocks).astype(int), 0, ny_blocks - 1)
        return block_values[iy, ix]
    raise ValueError(f"Unknown hydraulic_conductivity_pattern: {pattern}")


def pore_velocity_field(
    case: CaseConfig, mesh: TriDisvMesh, k_field: np.ndarray | None = None
) -> np.ndarray:
    if k_field is None:
        k_field = hydraulic_conductivity_field(case, mesh)
    gradient = (case.flow.head_left_m - case.flow.head_right_m) / case.domain.length_m
    darcy_flux = np.asarray(k_field, dtype=float) * gradient
    return darcy_flux / max(case.flow.porosity, 1.0e-12)


def cell_peclet_numbers(
    case: CaseConfig, mesh: TriDisvMesh, k_field: np.ndarray | None = None
) -> np.ndarray:
    velocity = np.abs(pore_velocity_field(case, mesh, k_field))
    dispersion = effective_dispersion(case)
    characteristic_lengths = np.sqrt(np.asarray(mesh.areas, dtype=float))
    return velocity * characteristic_lengths / dispersion


def transport_diagnostics(
    case: CaseConfig, mesh: TriDisvMesh, k_field: np.ndarray | None = None
) -> dict[str, float]:
    if k_field is None:
        k_field = hydraulic_conductivity_field(case, mesh)
    gradient = (case.flow.head_left_m - case.flow.head_right_m) / case.domain.length_m
    darcy_flux = np.asarray(k_field, dtype=float) * gradient
    pore_velocity = darcy_flux / max(case.flow.porosity, 1.0e-12)
    dispersion = effective_dispersion(case)
    characteristic_lengths = np.sqrt(np.asarray(mesh.areas, dtype=float))
    peclet = np.abs(pore_velocity) * characteristic_lengths / dispersion
    mean_velocity = float(np.mean(pore_velocity))
    travel_time = case.domain.length_m / max(abs(mean_velocity), 1.0e-12)
    return {
        "hydraulic_gradient": _round(gradient),
        "hydraulic_conductivity_min_m_per_day": _round(np.min(k_field)),
        "hydraulic_conductivity_mean_m_per_day": _round(np.mean(k_field)),
        "hydraulic_conductivity_max_m_per_day": _round(np.max(k_field)),
        "darcy_flux_min_m_per_day": _round(np.min(darcy_flux)),
        "darcy_flux_m_per_day": _round(np.mean(darcy_flux)),
        "darcy_flux_max_m_per_day": _round(np.max(darcy_flux)),
        "pore_velocity_min_m_per_day": _round(np.min(pore_velocity)),
        "pore_velocity_m_per_day": _round(mean_velocity),
        "pore_velocity_max_m_per_day": _round(np.max(pore_velocity)),
        "dispersion_m2_per_day": _round(dispersion),
        "cell_length_mean_m": _round(np.mean(characteristic_lengths)),
        "peclet_min": _round(np.min(peclet)),
        "peclet_mean": _round(np.mean(peclet)),
        "peclet_max": _round(np.max(peclet)),
        "advective_travel_time_days": _round(travel_time),
        "simulated_travel_fraction": _round(case.transport.duration_days / travel_time),
    }


def effective_dispersion(case: CaseConfig) -> float:
    return max(
        case.transport.diffusion_m2_per_day,
        1.0e-12,
    )


def synthetic_concentration(case: CaseConfig, mesh: TriDisvMesh, times: np.ndarray) -> np.ndarray:
    x = mesh.centroids[:, 0]
    y = mesh.centroids[:, 1]
    velocity = pore_velocity_field(case, mesh)
    dispersion = effective_dispersion(case)
    values = []
    for time in times:
        if case.transport.source_schedule == "internal_pulse":
            values.append(_internal_pulse_solution(case, x, y, time, velocity, dispersion))
        elif case.transport.source_schedule == "pulse":
            conc = _front_solution(
                x, time, velocity, dispersion, case.transport.source_concentration
            )
            delayed = _front_solution(
                x,
                time - case.transport.pulse_end_day,
                velocity,
                dispersion,
                case.transport.source_concentration,
            )
            values.append(np.clip(conc - delayed, 0.0, case.transport.source_concentration))
        else:
            values.append(
                _front_solution(
                    x,
                    time,
                    velocity,
                    dispersion,
                    case.transport.source_concentration,
                )
            )
    return np.vstack(values)


def _internal_pulse_solution(
    case: CaseConfig,
    x: np.ndarray,
    y: np.ndarray,
    time: float,
    velocity: np.ndarray,
    dispersion: float,
) -> np.ndarray:
    center0 = case.transport.pulse_center_m
    if center0 is None:
        center0 = 40.0
    width0 = case.transport.pulse_width_m
    if width0 is None:
        width0 = 1.2
    y_center = case.transport.pulse_y_center_m
    if y_center is None:
        y_center = 0.5 * case.domain.width_m
    y_width = case.transport.pulse_y_width_m
    if y_width is None:
        y_width = 0.18 * case.domain.width_m
    elapsed = max(time, 0.0)
    variance_x = width0 * width0 + 2.0 * dispersion * elapsed
    variance_y = y_width * y_width + 2.0 * dispersion * elapsed
    center = center0 + np.asarray(velocity, dtype=float) * elapsed
    amplitude = (
        case.transport.source_concentration
        * width0
        / math.sqrt(variance_x)
        * y_width
        / math.sqrt(variance_y)
    )
    main = amplitude * np.exp(
        -0.5 * ((x - center) ** 2) / variance_x - 0.5 * ((y - y_center) ** 2) / variance_y
    )
    return np.clip(main, 0.0, case.transport.source_concentration)


def plot_context(result: CaseResult, path: Path) -> None:
    case = result.case
    numbers = result.signatures["transport_numbers"]
    fig, (ax, info_ax) = plt.subplots(
        1,
        2,
        figsize=(13.5, 4.4),
        gridspec_kw={"width_ratios": [2.4, 1.0]},
        constrained_layout=True,
    )
    polygons = [result.mesh.vertices[face] for face in result.mesh.faces]
    collection = PolyCollection(
        polygons,
        facecolors="#f7fbff",
        edgecolors="#9fb3c8",
        linewidths=0.28,
    )
    ax.add_collection(collection)
    ax.autoscale()
    ax.set_aspect("equal")
    ax.set_title("Domain, boundary conditions and plume probes")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")

    ymin = 0.0
    ymax = case.domain.width_m
    ax.plot([0.0, 0.0], [ymin, ymax], color="#1f78b4", linewidth=4)
    ax.plot(
        [case.domain.length_m, case.domain.length_m], [ymin, ymax], color="#d95f02", linewidth=4
    )
    left_transport = (
        "no solute source" if case.transport.source_schedule == "internal_pulse" else "C source"
    )
    ax.text(
        1.5,
        ymax * 0.92,
        f"left CHD\nh={case.flow.head_left_m:g} m\n{left_transport}",
        color="#1f78b4",
    )
    ax.text(
        case.domain.length_m - 18.0,
        ymax * 0.92,
        f"right CHD\nh={case.flow.head_right_m:g} m",
        color="#d95f02",
    )
    ax.text(
        case.domain.length_m - 18.0,
        ymax * 0.13,
        "transport outlet\nabsorbing/open",
        color="#d95f02",
    )
    if case.transport.source_schedule == "internal_pulse":
        center = case.transport.pulse_center_m or 10.0
        width = case.transport.pulse_width_m or 2.5
        xs = np.linspace(max(0.0, center - 4.0 * width), center + 4.0 * width, 120)
        ys = ymax * (0.18 + 0.22 * np.exp(-0.5 * ((xs - center) / width) ** 2))
        ax.fill_between(xs, ymax * 0.18, ys, color="#c51b29", alpha=0.35)
        ax.plot(xs, ys, color="#c51b29", linewidth=2.0)
        ax.text(
            center, ymax * 0.46, f"initial pulse\nx0={center:g} m", ha="center", color="#991b1b"
        )
    ax.annotate(
        "flow and transport direction",
        xy=(case.domain.length_m * 0.72, ymax * 0.50),
        xytext=(case.domain.length_m * 0.24, ymax * 0.50),
        arrowprops={"arrowstyle": "->", "lw": 2.5, "color": "#34495e"},
        ha="center",
        va="center",
        color="#34495e",
    )
    for frac in _probe_fractions():
        x = case.domain.length_m * frac
        ax.axvline(x, color="#4b5563", linestyle=":", linewidth=1.2)
        ax.text(x, ymax * 0.04, f"{frac:.0%} L", ha="center", va="bottom", fontsize=8)

    info_ax.axis("off")
    k_range = (
        f"{numbers['hydraulic_conductivity_min_m_per_day']:.3g}"
        f"-{numbers['hydraulic_conductivity_max_m_per_day']:.3g} m/day"
    )
    pe_range = f"{numbers['peclet_min']:.2g}-{numbers['peclet_max']:.2g}"
    info_lines = [
        ("K pattern", case.flow.hydraulic_conductivity_pattern),
        ("K range", k_range),
        ("porosity", f"{case.flow.porosity:g}"),
        ("gradient", f"{numbers['hydraulic_gradient']:.4g}"),
        ("Darcy flux mean", f"{numbers['darcy_flux_m_per_day']:.4g} m/day"),
        ("pore velocity mean", f"{numbers['pore_velocity_m_per_day']:.4g} m/day"),
        ("D", f"{numbers['dispersion_m2_per_day']:.4g} m2/day"),
        ("cell Peclet mean", f"{numbers['peclet_mean']:.3g}"),
        ("cell Peclet range", pe_range),
        ("travel time L/v", f"{numbers['advective_travel_time_days']:.0f} days"),
        ("simulated L fraction", f"{numbers['simulated_travel_fraction']:.2g}"),
    ]
    y = 0.98
    info_ax.text(0.0, y, "Key parameters", fontsize=13, fontweight="bold", va="top")
    y -= 0.10
    for label, value in info_lines:
        info_ax.text(0.0, y, label, fontweight="bold", va="top")
        info_ax.text(0.46, y, value, va="top")
        y -= 0.075

    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_mesh_overview(result: CaseResult, path: Path) -> None:
    mesh = result.mesh
    fig, ax = plt.subplots(figsize=(13.5, 4.4), constrained_layout=True)
    polygons = [mesh.vertices[face] for face in mesh.faces]
    collection = PolyCollection(
        polygons,
        facecolors="#ffffff",
        edgecolors="#263238",
        linewidths=0.32,
    )
    ax.add_collection(collection)
    ax.scatter(
        mesh.centroids[:, 0],
        mesh.centroids[:, 1],
        s=2.5,
        color="#607d8b",
        alpha=0.55,
        label="cell centroids",
    )
    ax.scatter(
        mesh.centroids[mesh.left_cells, 0],
        mesh.centroids[mesh.left_cells, 1],
        s=18,
        color="#1f78b4",
        label="left boundary cells",
    )
    ax.scatter(
        mesh.centroids[mesh.right_cells, 0],
        mesh.centroids[mesh.right_cells, 1],
        s=18,
        color="#d95f02",
        label="right boundary cells",
    )
    ax.autoscale()
    ax.set_aspect("equal")
    ax.set_title(f"Triangular DISV mesh ({mesh.n_cells} cells, area ratio {mesh.area_ratio:.2f})")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_cell_field(
    mesh: TriDisvMesh,
    values: np.ndarray,
    title: str,
    path: Path,
    *,
    cmap: str,
) -> None:
    polygons = [mesh.vertices[face] for face in mesh.faces]
    fig, ax = plt.subplots(figsize=(12.5, 4.0), constrained_layout=True)
    collection = PolyCollection(
        polygons,
        array=np.asarray(values, dtype=float),
        cmap=cmap,
        edgecolors="#222222",
        linewidths=0.25,
    )
    ax.add_collection(collection)
    ax.autoscale()
    ax.set_aspect("equal")
    ax.set_title(title)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    cbar = fig.colorbar(collection, ax=ax, shrink=0.82)
    cbar.ax.tick_params(labelsize=11)
    _decorate_boundary_axis(ax, mesh)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_concentration_snapshots(result: CaseResult, path: Path) -> None:
    polygons = [result.mesh.vertices[face] for face in result.mesh.faces]
    selected = _selected_snapshot_indices(len(result.times_days), max_count=10)
    n = len(selected)
    ncols = min(2, n)
    nrows = int(math.ceil(n / ncols))
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(8.3 * ncols, 2.9 * nrows),
        constrained_layout=True,
        squeeze=False,
    )
    vmax = max(float(result.case.transport.source_concentration), 1.0e-12)
    norm = PowerNorm(gamma=0.55, vmin=0.0, vmax=vmax)
    last_collection = None
    for plot_idx, ax in enumerate(axes.ravel()):
        if plot_idx >= n:
            ax.axis("off")
            continue
        idx = selected[plot_idx]
        collection = PolyCollection(
            polygons,
            array=result.concentration[idx],
            cmap=CONCENTRATION_CMAP,
            norm=norm,
            edgecolors="#222222",
            linewidths=0.08,
        )
        ax.add_collection(collection)
        ax.autoscale()
        ax.set_aspect("equal")
        row = result.signatures["time_signatures"][idx]
        center = row["center_x_m"]
        if isinstance(center, float) and math.isfinite(center):
            ax.axvline(center, color="#111827", linestyle="--", linewidth=0.8)
        ax.set_title(
            f"t = {result.times_days[idx]:.0f} d | center x = {center:.1f} m"
            if isinstance(center, float) and math.isfinite(center)
            else f"t = {result.times_days[idx]:.0f} d"
        )
        ax.set_xticks([])
        ax.set_yticks([])
        _decorate_boundary_axis(ax, result.mesh)
        last_collection = collection
    if last_collection is not None:
        cbar = fig.colorbar(last_collection, ax=axes.ravel().tolist(), shrink=0.78)
        cbar.set_label("concentration (zero maps to white)", fontsize=13)
        cbar.ax.tick_params(labelsize=12)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_concentration_profiles(result: CaseResult, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 4.8), constrained_layout=True)
    bins = np.linspace(0.0, result.case.domain.length_m, 70)
    centers = 0.5 * (bins[:-1] + bins[1:])
    x = result.mesh.centroids[:, 0]
    y_mask = _profile_y_mask(result)
    selected = _selected_snapshot_indices(len(result.times_days), max_count=6)
    colors = plt.cm.viridis(np.linspace(0.08, 0.95, len(selected)))
    for color, idx in zip(colors, selected, strict=True):
        time = result.times_days[idx]
        conc = result.concentration[idx]
        profile = []
        for lo, hi in zip(bins[:-1], bins[1:], strict=True):
            mask = (x >= lo) & (x < hi) & y_mask
            if not np.any(mask):
                profile.append(np.nan)
                continue
            weights = result.mesh.areas[mask]
            profile.append(float(np.average(conc[mask], weights=weights)))
        ax.plot(centers, profile, label=f"{time:.0f} d", color=color, linewidth=1.7)
    for frac in _probe_fractions():
        ax.axvline(
            result.case.domain.length_m * frac, color="#9aa5b1", linestyle=":", linewidth=1.0
        )
    ax.set_xlabel("x (m)")
    ax.set_ylabel("section-averaged concentration")
    ax.set_title("Longitudinal concentration profiles at selected times")
    ax.set_ylim(-0.05, result.case.transport.source_concentration * 1.08)
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=5, fontsize=11, title="time", title_fontsize=12)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_probe_breakthrough(result: CaseResult, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 4.8), constrained_layout=True)
    x = result.mesh.centroids[:, 0]
    y_mask = _profile_y_mask(result)
    band_half_width = max(result.case.domain.length_m / result.case.domain.nx, 1.0)
    markevery = max(len(result.times_days) // 14, 1)
    for frac in _probe_fractions():
        probe_x = result.case.domain.length_m * frac
        mask = (np.abs(x - probe_x) <= band_half_width) & y_mask
        if not np.any(mask):
            mask = np.abs(x - probe_x) == np.min(np.abs(x - probe_x))
        series = []
        for conc in result.concentration:
            series.append(float(np.average(conc[mask], weights=result.mesh.areas[mask])))
        ax.plot(
            result.times_days,
            series,
            marker="o",
            markevery=markevery,
            linewidth=1.8,
            label=f"x = {frac:.0%} L",
        )
    ax.set_title("Breakthrough curves at fixed longitudinal probes")
    ax.set_xlabel("time (days)")
    ax.set_ylabel("local section-averaged concentration")
    ax.set_ylim(-0.05, result.case.transport.source_concentration * 1.08)
    ax.grid(True, alpha=0.25)
    ax.legend(title="probe", fontsize=11, title_fontsize=12)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_plume_evolution(result: CaseResult, path: Path) -> None:
    rows = result.signatures["time_signatures"]
    times = [row["time_days"] for row in rows]
    mass = [row["area_weighted_mass"] for row in rows]
    center = np.asarray(
        [np.nan if row["center_x_m"] is None else row["center_x_m"] for row in rows]
    )
    width = np.asarray([np.nan if row["width_x_m"] is None else row["width_x_m"] for row in rows])
    advective = [row["advective_distance_m"] for row in rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10.5, 7.2), constrained_layout=True)
    ax1.plot(times, mass, marker="o", color="#1f77b4", label="area-weighted mass")
    ax1.set_ylabel("area-weighted mass", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.grid(True, alpha=0.25)
    ax1.set_title("Plume mass and longitudinal position")

    ax1b = ax1.twinx()
    ax1b.plot(times, center, marker="s", color="#d62728", label="concentration center")
    ax1b.plot(times, advective, color="#6b7280", linestyle="--", label="v * t")
    ax1b.set_ylabel("x (m)", color="#d62728")
    ax1b.tick_params(axis="y", labelcolor="#d62728")
    ax1b.legend(loc="lower right", fontsize=11)

    ax2.plot(times, center, marker="s", color="#d62728", label="center x")
    ax2.fill_between(
        times,
        center - width,
        center + width,
        color="#fca5a5",
        alpha=0.32,
        label="center +/- one weighted std",
    )
    ax2.set_xlabel("time (days)")
    ax2.set_ylabel("x (m)")
    ax2.set_ylim(0.0, result.case.domain.length_m)
    ax2.grid(True, alpha=0.25)
    ax2.legend(loc="upper left", fontsize=11)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_analytical_profile_comparison(result: CaseResult, path: Path) -> None:
    analytical = analytical_concentration(result.case, result.mesh, result.times_days)
    if analytical is None:
        return

    fig, ax = plt.subplots(figsize=(12.0, 5.0), constrained_layout=True)
    bins = np.linspace(0.0, result.case.domain.length_m, 80)
    centers = 0.5 * (bins[:-1] + bins[1:])
    y_mask = _profile_y_mask(result)
    selected = _selected_snapshot_indices(len(result.times_days), max_count=6)
    colors = plt.cm.viridis(np.linspace(0.08, 0.95, len(selected)))
    for color, idx in zip(colors, selected, strict=True):
        model_profile = _longitudinal_profile(result.mesh, result.concentration[idx], bins, y_mask)
        analytical_profile = _longitudinal_profile(result.mesh, analytical[idx], bins, y_mask)
        time = result.times_days[idx]
        ax.plot(centers, model_profile, color=color, linewidth=2.0, label=f"{time:.0f} d model")
        ax.plot(
            centers,
            analytical_profile,
            color=color,
            linewidth=1.8,
            linestyle="--",
            label=f"{time:.0f} d analytical",
        )
    for frac in _probe_fractions():
        ax.axvline(
            result.case.domain.length_m * frac, color="#9aa5b1", linestyle=":", linewidth=1.0
        )
    ax.set_title("Longitudinal profiles: model versus analytical reference")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("section-averaged concentration")
    ax.set_ylim(-0.05, result.case.transport.source_concentration * 1.08)
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=3, fontsize=9, title="time and source", title_fontsize=10)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_analytical_error_diagnostics(result: CaseResult, path: Path) -> None:
    analytical = analytical_concentration(result.case, result.mesh, result.times_days)
    if analytical is None:
        return

    polygons = [result.mesh.vertices[face] for face in result.mesh.faces]
    final_model = result.concentration[-1]
    final_analytical = analytical[-1]
    final_error = final_model - final_analytical
    vmax = max(float(result.case.transport.source_concentration), 1.0e-12)
    conc_norm = PowerNorm(gamma=0.55, vmin=0.0, vmax=vmax)
    err_abs = max(float(np.max(np.abs(final_error))), 1.0e-12)
    err_norm = TwoSlopeNorm(vmin=-err_abs, vcenter=0.0, vmax=err_abs)

    fig, axes = plt.subplot_mosaic(
        [["model", "analytical"], ["error", "metrics"]],
        figsize=(14.0, 7.2),
        constrained_layout=True,
    )

    for key, values, title in (
        ("model", final_model, "Model concentration, final time"),
        ("analytical", final_analytical, "Analytical concentration, final time"),
    ):
        collection = PolyCollection(
            polygons,
            array=np.asarray(values, dtype=float),
            cmap=CONCENTRATION_CMAP,
            norm=conc_norm,
            edgecolors="#222222",
            linewidths=0.08,
        )
        ax = axes[key]
        ax.add_collection(collection)
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
        _decorate_boundary_axis(ax, result.mesh)

    error_collection = PolyCollection(
        polygons,
        array=final_error,
        cmap="RdBu_r",
        norm=err_norm,
        edgecolors="#222222",
        linewidths=0.08,
    )
    ax_error = axes["error"]
    ax_error.add_collection(error_collection)
    ax_error.autoscale()
    ax_error.set_aspect("equal")
    ax_error.set_title("Signed error, final time")
    ax_error.set_xticks([])
    ax_error.set_yticks([])
    _decorate_boundary_axis(ax_error, result.mesh)

    cbar = fig.colorbar(error_collection, ax=ax_error, shrink=0.82)
    cbar.set_label("model - analytical", fontsize=11)
    cbar.ax.tick_params(labelsize=10)

    rows = result.signatures["time_signatures"]
    times = [row["time_days"] for row in rows]
    rmse = [row["analytical_c_rmse"] for row in rows]
    linf = [row["analytical_c_linf"] for row in rows]
    center_error = [row["analytical_center_error_m"] for row in rows]
    ax_metrics = axes["metrics"]
    ax_metrics.plot(times, rmse, marker="o", markevery=max(len(times) // 14, 1), label="RMSE")
    ax_metrics.plot(times, linf, marker="s", markevery=max(len(times) // 14, 1), label="Linf")
    ax_metrics.set_xlabel("time (days)")
    ax_metrics.set_ylabel("concentration error")
    ax_metrics.grid(True, alpha=0.25)
    ax_metrics.set_title("Error metrics against analytical reference")
    ax_metrics_b = ax_metrics.twinx()
    ax_metrics_b.plot(times, center_error, color="#d62728", linestyle="--", label="center error")
    ax_metrics_b.set_ylabel("center error (m)", color="#d62728")
    ax_metrics_b.tick_params(axis="y", labelcolor="#d62728")
    ax_metrics.legend(loc="upper left", fontsize=10)
    ax_metrics_b.legend(loc="upper right", fontsize=10)

    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_html(result: CaseResult, output_dir: Path) -> None:
    parameter_cards = "\n".join(
        f"<div class='metric-card'><div class='metric-label'>{html.escape(label)}</div>"
        f"<div class='metric-value'>{html.escape(value)}</div>"
        f"<div class='metric-note'>{html.escape(note)}</div></div>"
        for label, value, note in _parameter_cards(result)
    )
    runtime_rows = "\n".join(
        f"<tr><td>{html.escape(key)}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in result.signatures.get("runtime", {}).items()
    )
    transport_bc = _transport_boundary_description(result.case)
    analytical_section = _analytical_section_html(result)
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(result.case.title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2933; background: #f7f9fb; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    h2 {{ margin-top: 2rem; border-bottom: 2px solid #d9e2ec; padding-bottom: 0.35rem; }}
    .muted {{ color: #52606d; }}
    .panel {{ background: white; border: 1px solid #d9e2ec; padding: 18px; margin: 16px 0 24px; }}
    table {{ border-collapse: collapse; margin: 12px 0 24px; width: 100%; background: white; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 6px 8px; font-size: 13px; vertical-align: top; }}
    th {{ background: #f0f4f8; text-align: left; }}
    img {{ max-width: 100%; border: 1px solid #d9e2ec; margin: 8px 0 22px; background: white; }}
    .wide img {{ width: 100%; }}
    .ok {{ color: #0b6b3a; font-weight: 700; }}
    .fail {{ color: #9b1c1c; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 18px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; }}
    .metric-card {{ background: white; border: 1px solid #d9e2ec; padding: 14px; }}
    .metric-label {{ color: #52606d; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .metric-value {{ font-size: 24px; font-weight: 700; margin: 6px 0; }}
    .metric-note {{ color: #52606d; font-size: 12px; line-height: 1.35; }}
  </style>
</head>
<body>
  <h1>{html.escape(result.case.title)}</h1>
  <p class="muted">{html.escape(result.case.description)}</p>
  <p><b>Mode:</b> {html.escape(result.mode)} | <b>Case:</b> {html.escape(result.case.name)}</p>

  <h2>Context</h2>
  <div class="panel">
    <p>
      This page is a visual guard, not a full validation proof. It shows the
      triangular DISV domain, boundary conditions, flow direction and transport
      parameters before plotting the concentration plume.
    </p>
    <p><b>Transport boundary conditions:</b> {html.escape(transport_bc)}</p>
    <img src="figures/domain_context.png" alt="Domain and boundary conditions">
  </div>

  <h2>Key Parameters</h2>
  <div class="metric-grid">
    {parameter_cards}
  </div>

  <h2>Run Time</h2>
  <table><tbody>{runtime_rows}</tbody></table>

  <h2>Mesh</h2>
  <div class="wide">
    <img src="figures/mesh_overview.png" alt="Mesh overview">
  </div>

  <h2>Flow</h2>
  <div class="grid">
    <div><h3>Hydraulic conductivity</h3><img src="figures/hydraulic_conductivity.png" alt="Hydraulic conductivity"></div>
    <div><h3>Head</h3><img src="figures/head_final.png" alt="Head"></div>
    <div><h3>Flux proxy</h3><img src="figures/flux_proxy.png" alt="Flux proxy"></div>
    <div><h3>Cell Peclet</h3><img src="figures/cell_peclet.png" alt="Cell Peclet"></div>
  </div>

  <h2>Transport</h2>
  <p class="muted">
    Concentration maps use a white-zero color scale and a power normalization so
    low concentrations stay visible while zero-concentration cells remain white.
  </p>
  <img src="figures/concentration_snapshots.png" alt="Concentration snapshots">
  <img src="figures/concentration_profiles.png" alt="Concentration profiles">
  <img src="figures/probe_breakthrough.png" alt="Probe breakthrough curves">
  <img src="figures/plume_evolution.png" alt="Plume evolution">

  {analytical_section}
</body>
</html>
"""
    (output_dir / "index.html").write_text(body, encoding="utf-8")


def _analytical_section_html(result: CaseResult) -> str:
    comparison = result.signatures.get("analytical_comparison", {})
    if not comparison.get("available", False):
        reason = str(comparison.get("reason", analytical_reference_reason(result.case)))
        return (
            "<h2>Analytical Reference</h2>"
            "<div class='panel'>"
            "<p class='muted'>"
            f"{html.escape(reason)}"
            "</p>"
            "</div>"
        )

    rows = "\n".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(value)}</td></tr>"
        for label, value in (
            ("Reference", str(comparison["reference"])),
            ("RMSE", str(comparison["rmse"])),
            ("Linf", str(comparison["linf"])),
            ("RMSE tolerance", str(comparison["rmse_tolerance"])),
            ("Final mass relative error", str(comparison["final_mass_relative_error"])),
            ("Final center error", f"{comparison['final_center_error_m']} m"),
            ("Final width error", f"{comparison['final_width_error_m']} m"),
        )
    )
    reason = html.escape(str(comparison["reason"]))
    return f"""
  <h2>Analytical Reference</h2>
  <div class="panel">
    <p>{reason}</p>
    <table><tbody>{rows}</tbody></table>
    <img src="figures/analytical_profile_comparison.png" alt="Analytical profile comparison">
    <img src="figures/analytical_error_diagnostics.png" alt="Analytical error diagnostics">
  </div>
"""


def _decorate_boundary_axis(ax: Any, mesh: TriDisvMesh) -> None:
    ymin = float(np.min(mesh.vertices[:, 1]))
    ymax = float(np.max(mesh.vertices[:, 1]))
    xmin = float(np.min(mesh.vertices[:, 0]))
    xmax = float(np.max(mesh.vertices[:, 0]))
    ax.plot([xmin, xmin], [ymin, ymax], color="#1f78b4", linewidth=2.0)
    ax.plot([xmax, xmax], [ymin, ymax], color="#d95f02", linewidth=2.0)


def _selected_snapshot_indices(count: int, *, max_count: int) -> list[int]:
    if count <= max_count:
        return list(range(count))
    values = np.linspace(0, count - 1, max_count)
    return sorted({int(round(value)) for value in values})


def _profile_y_mask(result: CaseResult) -> np.ndarray:
    if result.case.transport.source_schedule != "internal_pulse":
        return np.ones(result.mesh.n_cells, dtype=bool)
    center = result.case.transport.pulse_y_center_m
    if center is None:
        center = 0.5 * result.case.domain.width_m
    width = result.case.transport.pulse_y_width_m
    if width is None:
        width = 0.18 * result.case.domain.width_m
    band_half_width = max(2.0 * width, result.case.domain.width_m / result.case.domain.ny)
    return np.abs(result.mesh.centroids[:, 1] - center) <= band_half_width


def _longitudinal_profile(
    mesh: TriDisvMesh, concentration: np.ndarray, bins: np.ndarray, y_mask: np.ndarray
) -> list[float]:
    x = mesh.centroids[:, 0]
    profile = []
    for lo, hi in zip(bins[:-1], bins[1:], strict=True):
        mask = (x >= lo) & (x < hi) & y_mask
        if not np.any(mask):
            profile.append(np.nan)
            continue
        profile.append(float(np.average(concentration[mask], weights=mesh.areas[mask])))
    return profile


def _probe_fractions() -> tuple[float, ...]:
    return (0.25, 0.50, 0.75)


def _add_disv(model: Any, mesh: TriDisvMesh, case: CaseConfig) -> None:
    import flopy

    package_factory = (
        flopy.mf6.ModflowGwfdisv
        if model.__class__.__name__.lower().endswith("gwf")
        else flopy.mf6.ModflowGwtdisv
    )
    package_factory(
        model,
        nlay=1,
        ncpl=mesh.n_cells,
        nvert=len(mesh.vertices_disv),
        vertices=mesh.vertices_disv,
        cell2d=mesh.cell2d,
        top=1.0,
        botm=[0.0],
        idomain=np.ones((1, mesh.n_cells), dtype=int),
        length_units="METERS",
    )


def _source_at_period_start(case: CaseConfig, period_start: float) -> float:
    if case.transport.source_schedule == "internal_pulse":
        return 0.0
    if case.transport.source_schedule == "pulse":
        return (
            case.transport.source_concentration
            if period_start < case.transport.pulse_end_day
            else 0.0
        )
    return case.transport.source_concentration


def _front_solution(
    x: np.ndarray,
    time: float,
    velocity: float,
    dispersion: float,
    source: float,
) -> np.ndarray:
    if time <= 0.0:
        return np.zeros_like(x, dtype=float)
    x = np.asarray(x, dtype=float)
    velocity = np.asarray(velocity, dtype=float)
    dt = max(float(dispersion) * float(time), 1.0e-30)
    sqrt_dt = math.sqrt(dt)
    z1 = (x - velocity * time) / (2.0 * sqrt_dt)
    z2 = (x + velocity * time) / (2.0 * sqrt_dt)
    first = 0.5 * erfc(z1)
    # Stable form of exp(v*x/D) * erfc((x + v*t) / (2*sqrt(D*t))).
    second = 0.5 * np.exp(-((x - velocity * time) ** 2) / (4.0 * dt)) * erfcx(z2)
    return np.clip(source * (first + second), 0.0, source)


def _pore_velocity(case: CaseConfig) -> float:
    gradient = (case.flow.head_left_m - case.flow.head_right_m) / case.domain.length_m
    darcy = case.flow.hydraulic_conductivity_m_per_day * gradient
    return darcy / max(case.flow.porosity, 1.0e-12)


def _signed_area(points: np.ndarray) -> float:
    x = points[:, 0]
    y = points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _clockwise_face(vertices: np.ndarray, face: list[int]) -> list[int]:
    points = vertices[face]
    return list(reversed(face)) if _signed_area(points) > 0.0 else list(face)


def _round(value: Any, ndigits: int = 8) -> float | None:
    value = float(value)
    if not math.isfinite(value):
        return None
    return round(value, ndigits)


def _check_class(value: bool) -> str:
    return "ok" if bool(value) else "fail"


def _parameter_cards(result: CaseResult) -> list[tuple[str, str, str]]:
    case = result.case
    mesh = result.mesh
    numbers = result.signatures["transport_numbers"]
    runtime = result.signatures.get("runtime", {})
    source_note = (
        f"internal pulse centered at x={case.transport.pulse_center_m:g} m"
        if case.transport.source_schedule == "internal_pulse"
        and case.transport.pulse_center_m is not None
        else f"{case.transport.source_schedule} upstream source"
    )
    return [
        (
            "Cells",
            f"{mesh.n_cells}",
            f"triangular DISV, area ratio {mesh.area_ratio:.2f}",
        ),
        (
            "K range",
            (
                f"{numbers['hydraulic_conductivity_min_m_per_day']:.3g}"
                f"-{numbers['hydraulic_conductivity_max_m_per_day']:.3g} m/day"
            ),
            case.flow.hydraulic_conductivity_pattern.replace("_", " "),
        ),
        (
            "Heads",
            f"{case.flow.head_left_m:g} -> {case.flow.head_right_m:g} m",
            "left to right hydraulic gradient",
        ),
        (
            "Pore velocity",
            f"{numbers['pore_velocity_m_per_day']:.3g} m/day",
            (
                f"range {numbers['pore_velocity_min_m_per_day']:.3g}"
                f"-{numbers['pore_velocity_max_m_per_day']:.3g} m/day"
            ),
        ),
        (
            "Cell Peclet",
            f"{numbers['peclet_mean']:.1f}",
            f"range {numbers['peclet_min']:.1f}-{numbers['peclet_max']:.1f}; homogeneous target is about 20",
        ),
        (
            "Diffusion",
            f"{numbers['dispersion_m2_per_day']:.4g} m2/day",
            "effective longitudinal dispersion coefficient",
        ),
        (
            "Duration",
            f"{case.transport.duration_days:.0f} days",
            f"{numbers['simulated_travel_fraction']:.2g} advective travel time",
        ),
        (
            "Source",
            f"C={case.transport.source_concentration:g}",
            source_note,
        ),
        (
            "Generated in",
            f"{runtime.get('total_seconds', 'n/a')} s",
            f"{result.mode} backend plus report rendering",
        ),
    ]


def _transport_boundary_description(case: CaseConfig) -> str:
    if case.transport.source_schedule == "internal_pulse":
        center = case.transport.pulse_center_m or 10.0
        return (
            f"the pulse is initialized inside the domain at x={center:g} m. "
            "The upstream side has no solute injection in this case; the downstream "
            "side is open/absorbing."
        )
    return (
        "the upstream side is a concentration source imposed on the left boundary; "
        "the downstream side is open/absorbing."
    )


def _check_descriptions() -> dict[str, str]:
    return {
        "mesh_area_ratio_ok": "Keeps the synthetic DISV mesh close to quasi-uniform so transport artifacts are not dominated by cell-size contrast.",
        "concentration_finite": "Detects NaN/Inf values before any visual interpretation.",
        "concentration_lower_bound_ok": "Flags negative concentrations beyond a small numerical tolerance.",
        "concentration_upper_bound_ok": "Flags concentrations above the imposed source concentration.",
        "front_moves_downstream": "Checks that the concentration center moves in the expected hydraulic direction.",
        "cell_peclet_reasonable": "Keeps the homogeneous mean cell Peclet number near 20 while allowing heterogeneous K cases to vary spatially.",
        "simulation_time_shows_plume_motion": "Checks that the simulated duration is long enough relative to L / pore velocity.",
    }


def _flatten_config(case: CaseConfig) -> dict[str, Any]:
    return {
        "case.name": case.name,
        "domain.length_m": case.domain.length_m,
        "domain.width_m": case.domain.width_m,
        "domain.nx": case.domain.nx,
        "domain.ny": case.domain.ny,
        "domain.perturbation_fraction": case.domain.perturbation_fraction,
        "domain.seed": case.domain.seed,
        "domain.max_area_ratio": case.domain.max_area_ratio,
        "flow.head_left_m": case.flow.head_left_m,
        "flow.head_right_m": case.flow.head_right_m,
        "flow.hydraulic_conductivity_m_per_day": case.flow.hydraulic_conductivity_m_per_day,
        "flow.hydraulic_conductivity_pattern": case.flow.hydraulic_conductivity_pattern,
        "flow.hydraulic_conductivity_factor": case.flow.hydraulic_conductivity_factor,
        "flow.hydraulic_conductivity_seed": case.flow.hydraulic_conductivity_seed,
        "flow.porosity": case.flow.porosity,
        "transport.duration_days": case.transport.duration_days,
        "transport.n_snapshots": case.transport.n_snapshots,
        "transport.source_concentration": case.transport.source_concentration,
        "transport.source_schedule": case.transport.source_schedule,
        "transport.pulse_end_day": case.transport.pulse_end_day,
        "transport.pulse_center_m": case.transport.pulse_center_m,
        "transport.pulse_width_m": case.transport.pulse_width_m,
        "transport.pulse_y_center_m": case.transport.pulse_y_center_m,
        "transport.pulse_y_width_m": case.transport.pulse_y_width_m,
        "transport.longitudinal_dispersivity_m": case.transport.longitudinal_dispersivity_m,
        "transport.transverse_dispersivity_m": case.transport.transverse_dispersivity_m,
        "transport.diffusion_m2_per_day": case.transport.diffusion_m2_per_day,
    }


def run_cases(
    *,
    mode: str,
    output_dir: Path,
    cases_dir: Path = DEFAULT_CASES_DIR,
    case_names: set[str] | None = None,
    mf6_exe: str | None = None,
) -> list[CaseResult]:
    results = []
    cases = load_cases(cases_dir, case_names)
    if not cases:
        raise ValueError("No cases selected.")
    for case in cases:
        case_output = output_dir / case.name
        total_start = perf_counter()
        backend_start = perf_counter()
        if mode == "mf6":
            result = run_mf6_case(case, case_output, mf6_exe=mf6_exe)
        elif mode == "synthetic":
            result = run_synthetic_case(case)
        else:
            raise ValueError(f"Unknown mode: {mode}")
        backend_seconds = perf_counter() - backend_start
        report_start = perf_counter()
        result.signatures["runtime"] = {
            "backend_seconds": _round(backend_seconds, ndigits=3),
        }
        render_case_report(result, case_output)
        report_seconds = perf_counter() - report_start
        total_seconds = perf_counter() - total_start
        result.signatures["runtime"].update(
            {
                "report_seconds": _round(report_seconds, ndigits=3),
                "total_seconds": _round(total_seconds, ndigits=3),
            }
        )
        # Rewrite once after render timing is known.
        write_signatures(result, case_output)
        write_html(result, case_output)
        results.append(result)
    write_index(results, output_dir)
    return results


def write_index(results: list[CaseResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        "<tr>"
        f"<td><a href='{html.escape(result.case.name)}/index.html'>{html.escape(result.case.name)}</a></td>"
        f"<td>{html.escape(result.mode)}</td>"
        f"<td>{html.escape(result.case.flow.hydraulic_conductivity_pattern)}</td>"
        f"<td>{result.signatures['mesh']['n_cells']}</td>"
        f"<td>{result.signatures['mesh']['area_ratio']}</td>"
        f"<td>{result.signatures['transport_numbers']['peclet_min']} / "
        f"{result.signatures['transport_numbers']['peclet_mean']} / "
        f"{result.signatures['transport_numbers']['peclet_max']}</td>"
        f"<td>{_index_analytical_label(result)}</td>"
        f"<td>{result.signatures.get('runtime', {}).get('total_seconds', 'n/a')} s</td>"
        "</tr>"
        for result in results
    )
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Transport MF6 GWT DISV Visual Guard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 7px 9px; }}
    th {{ background: #f0f4f8; text-align: left; }}
  </style>
</head>
<body>
  <h1>Transport MF6 GWT DISV Visual Guard</h1>
  <table>
    <thead><tr><th>Case</th><th>Mode</th><th>K pattern</th><th>Cells</th><th>Area ratio</th><th>Pe min / mean / max</th><th>Analytical</th><th>Generated in</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""
    (output_dir / "index.html").write_text(body, encoding="utf-8")


def _index_analytical_label(result: CaseResult) -> str:
    comparison = result.signatures.get("analytical_comparison", {})
    if not comparison.get("available", False):
        return "n/a"
    return html.escape(f"RMSE {comparison['rmse']}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("synthetic", "mf6"),
        default="synthetic",
        help="Backend to run. Synthetic is deterministic and does not require mf6.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="Case name to run. Can be supplied multiple times. Default: all cases.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for reports.",
    )
    parser.add_argument(
        "--mf6-exe",
        default=None,
        help="Path to mf6 executable for --mode mf6. Defaults to PATH lookup.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    case_names = set(args.cases) if args.cases else None
    results = run_cases(
        mode=args.mode,
        output_dir=args.output_dir,
        case_names=case_names,
        mf6_exe=args.mf6_exe,
    )
    print(f"Wrote {len(results)} visual guard case(s) to {args.output_dir}")
    print(f"Open {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
