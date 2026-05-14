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
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection
from scipy.special import erfc

EXAMPLE_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_DIR = EXAMPLE_ROOT / "cases"
DEFAULT_OUTPUT_DIR = EXAMPLE_ROOT / "outputs"


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
    porosity: float


@dataclass(frozen=True)
class TransportConfig:
    duration_days: float
    n_snapshots: int
    source_concentration: float
    source_schedule: str
    pulse_end_day: float
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
    flux_proxy: np.ndarray
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
            hydraulic_conductivity_m_per_day=float(
                flow["hydraulic_conductivity_m_per_day"]
            ),
            porosity=float(flow["porosity"]),
        ),
        transport=TransportConfig(
            duration_days=float(transport["duration_days"]),
            n_snapshots=int(transport["n_snapshots"]),
            source_concentration=float(transport["source_concentration"]),
            source_schedule=str(transport["source_schedule"]),
            pulse_end_day=float(transport["pulse_end_day"]),
            longitudinal_dispersivity_m=float(
                transport["longitudinal_dispersivity_m"]
            ),
            transverse_dispersivity_m=float(transport["transverse_dispersivity_m"]),
            diffusion_m2_per_day=float(transport["diffusion_m2_per_day"]),
        ),
        source_path=path,
    )


def load_cases(cases_dir: Path = DEFAULT_CASES_DIR, names: set[str] | None = None) -> list[CaseConfig]:
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

    vertices_disv = [
        (idx, float(xy[0]), float(xy[1])) for idx, xy in enumerate(vertices)
    ]
    cell2d = []
    for idx, face in enumerate(oriented_faces):
        xc, yc = centroids[idx]
        cell2d.append((idx, float(xc), float(yc), len(face), *[int(v) for v in face]))

    left_cells = np.asarray(
        [idx for idx, face in enumerate(oriented_faces) if np.any(np.isclose(vertices[face, 0], 0.0))],
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
    times = np.linspace(
        0.0, case.transport.duration_days, int(case.transport.n_snapshots)
    )
    head = synthetic_head(case, mesh)
    flux = synthetic_flux_proxy(case, mesh)
    concentration = synthetic_concentration(case, mesh, times)
    signatures = build_signatures(case, "synthetic", mesh, times, head, flux, concentration)
    return CaseResult(
        case=case,
        mode="synthetic",
        mesh=mesh,
        times_days=times,
        head=head,
        flux_proxy=flux,
        concentration=concentration,
        signatures=signatures,
    )


def run_mf6_case(case: CaseConfig, output_dir: Path, mf6_exe: str | None = None) -> CaseResult:
    mf6_path = mf6_exe or shutil.which("mf6")
    if mf6_path is None:
        raise RuntimeError("MF6 executable not found. Use --mf6-exe or run --mode synthetic.")

    import flopy

    mesh = build_triangular_disv_mesh(case.domain)
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
        k=case.flow.hydraulic_conductivity_m_per_day,
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
    flopy.mf6.ModflowGwtic(gwt, strt=0.0)
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
    conc = [np.zeros(mesh.n_cells, dtype=float)]
    selected_times = [0.0]
    for requested in target_times[1:]:
        idx = int(np.argmin(np.abs(raw_times - requested)))
        selected_times.append(float(raw_times[idx]))
        conc.append(np.asarray(conc_file.get_data(totim=raw_times[idx]), dtype=float).reshape(-1)[: mesh.n_cells])

    times = np.asarray(selected_times, dtype=float)
    concentration = np.vstack(conc)
    flux = synthetic_flux_proxy(case, mesh)
    signatures = build_signatures(case, "mf6", mesh, times, head_final, flux, concentration)
    return CaseResult(
        case=case,
        mode="mf6",
        mesh=mesh,
        times_days=times,
        head=head_final,
        flux_proxy=flux,
        concentration=concentration,
        signatures=signatures,
    )


def render_case_report(result: CaseResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    write_signatures(result, output_dir)
    plot_cell_field(
        result.mesh,
        result.mesh.areas,
        "Cell area (m2)",
        figures_dir / "mesh_area.png",
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
    plot_concentration_snapshots(result, figures_dir / "concentration_snapshots.png")
    plot_concentration_profiles(result, figures_dir / "concentration_profiles.png")
    plot_mass_front(result, figures_dir / "mass_front.png")
    write_html(result, output_dir)


def write_signatures(result: CaseResult, output_dir: Path) -> None:
    (output_dir / "signatures.json").write_text(
        json.dumps(result.signatures, indent=2, sort_keys=True) + "\n",
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
    for idx, (time, conc) in enumerate(zip(times, concentration, strict=True)):
        conc = np.asarray(conc, dtype=float)
        mass = float(np.sum(conc * mesh.areas))
        center_x = (
            float(np.sum(conc * mesh.areas * mesh.centroids[:, 0]) / mass)
            if mass > 1.0e-14
            else float("nan")
        )
        width_x = (
            float(
                math.sqrt(
                    np.sum(conc * mesh.areas * (mesh.centroids[:, 0] - center_x) ** 2)
                    / mass
                )
            )
            if mass > 1.0e-14
            else float("nan")
        )
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
            }
        )

    finite_conc = bool(np.isfinite(concentration).all())
    c_min = float(np.nanmin(concentration))
    c_max = float(np.nanmax(concentration))
    source = float(case.transport.source_concentration)
    finite_centers = [
        row["center_x_m"] for row in rows if isinstance(row["center_x_m"], float) and math.isfinite(row["center_x_m"])
    ]
    front_moves_downstream = len(finite_centers) < 2 or finite_centers[-1] > finite_centers[0]

    checks = {
        "mesh_area_ratio_ok": mesh.area_ratio <= case.domain.max_area_ratio,
        "concentration_finite": finite_conc,
        "concentration_lower_bound_ok": c_min >= -1.0e-8,
        "concentration_upper_bound_ok": c_max <= source * 1.05 + 1.0e-8,
        "front_moves_downstream": bool(front_moves_downstream),
    }
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
            "flux_proxy_mean_m_per_day": _round(np.mean(flux)),
        },
        "checks": checks,
        "time_signatures": rows,
    }


def synthetic_head(case: CaseConfig, mesh: TriDisvMesh) -> np.ndarray:
    x = mesh.centroids[:, 0]
    frac = x / float(case.domain.length_m)
    return case.flow.head_left_m + frac * (case.flow.head_right_m - case.flow.head_left_m)


def synthetic_flux_proxy(case: CaseConfig, mesh: TriDisvMesh) -> np.ndarray:
    gradient = (case.flow.head_left_m - case.flow.head_right_m) / case.domain.length_m
    flux = case.flow.hydraulic_conductivity_m_per_day * gradient
    return np.full(mesh.n_cells, flux, dtype=float)


def synthetic_concentration(
    case: CaseConfig, mesh: TriDisvMesh, times: np.ndarray
) -> np.ndarray:
    x = mesh.centroids[:, 0]
    velocity = _pore_velocity(case)
    dispersion = max(
        case.transport.longitudinal_dispersivity_m * velocity
        + case.transport.diffusion_m2_per_day,
        1.0e-12,
    )
    values = []
    for time in times:
        if case.transport.source_schedule == "pulse":
            conc = _front_solution(x, time, velocity, dispersion, case.transport.source_concentration)
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


def plot_cell_field(
    mesh: TriDisvMesh,
    values: np.ndarray,
    title: str,
    path: Path,
    *,
    cmap: str,
) -> None:
    polygons = [mesh.vertices[face] for face in mesh.faces]
    fig, ax = plt.subplots(figsize=(8, 3.2), constrained_layout=True)
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
    fig.colorbar(collection, ax=ax, shrink=0.82)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_concentration_snapshots(result: CaseResult, path: Path) -> None:
    polygons = [result.mesh.vertices[face] for face in result.mesh.faces]
    n = len(result.times_days)
    ncols = min(3, n)
    nrows = int(math.ceil(n / ncols))
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(4.2 * ncols, 2.8 * nrows),
        constrained_layout=True,
        squeeze=False,
    )
    vmax = max(float(result.case.transport.source_concentration), 1.0e-12)
    last_collection = None
    for idx, ax in enumerate(axes.ravel()):
        if idx >= n:
            ax.axis("off")
            continue
        collection = PolyCollection(
            polygons,
            array=result.concentration[idx],
            cmap="magma",
            edgecolors="#222222",
            linewidths=0.18,
        )
        collection.set_clim(0.0, vmax)
        ax.add_collection(collection)
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(f"t = {result.times_days[idx]:.1f} d")
        ax.set_xticks([])
        ax.set_yticks([])
        last_collection = collection
    if last_collection is not None:
        fig.colorbar(last_collection, ax=axes.ravel().tolist(), shrink=0.78)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_concentration_profiles(result: CaseResult, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
    bins = np.linspace(0.0, result.case.domain.length_m, 36)
    centers = 0.5 * (bins[:-1] + bins[1:])
    x = result.mesh.centroids[:, 0]
    for time, conc in zip(result.times_days, result.concentration, strict=True):
        profile = []
        for lo, hi in zip(bins[:-1], bins[1:], strict=True):
            mask = (x >= lo) & (x < hi)
            if not np.any(mask):
                profile.append(np.nan)
                continue
            weights = result.mesh.areas[mask]
            profile.append(float(np.average(conc[mask], weights=weights)))
        ax.plot(centers, profile, label=f"{time:.1f} d")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("area-weighted concentration")
    ax.set_ylim(-0.05, result.case.transport.source_concentration * 1.08)
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_mass_front(result: CaseResult, path: Path) -> None:
    rows = result.signatures["time_signatures"]
    times = [row["time_days"] for row in rows]
    mass = [row["area_weighted_mass"] for row in rows]
    center = [row["center_x_m"] for row in rows]

    fig, ax1 = plt.subplots(figsize=(8, 4), constrained_layout=True)
    ax1.plot(times, mass, marker="o", color="#1f77b4", label="area-weighted mass")
    ax1.set_xlabel("time (days)")
    ax1.set_ylabel("area-weighted mass", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.grid(True, alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(times, center, marker="s", color="#d62728", label="center x")
    ax2.set_ylabel("center x (m)", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_html(result: CaseResult, output_dir: Path) -> None:
    checks = result.signatures["checks"]
    check_rows = "\n".join(
        f"<tr><td>{html.escape(name)}</td><td class='{_check_class(value)}'>{value}</td></tr>"
        for name, value in checks.items()
    )
    config_rows = "\n".join(
        f"<tr><td>{html.escape(key)}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in _flatten_config(result.case).items()
    )
    time_rows = "\n".join(
        "<tr>"
        + "".join(f"<td>{html.escape(str(row[col]))}</td>" for col in row)
        + "</tr>"
        for row in result.signatures["time_signatures"]
    )
    time_header = "".join(
        f"<th>{html.escape(col)}</th>"
        for col in result.signatures["time_signatures"][0]
    )
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(result.case.title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2933; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    .muted {{ color: #52606d; }}
    table {{ border-collapse: collapse; margin: 12px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 6px 8px; font-size: 13px; }}
    th {{ background: #f0f4f8; text-align: left; }}
    img {{ max-width: 100%; border: 1px solid #d9e2ec; margin: 8px 0 22px; }}
    .ok {{ color: #0b6b3a; font-weight: 700; }}
    .fail {{ color: #9b1c1c; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; }}
  </style>
</head>
<body>
  <h1>{html.escape(result.case.title)}</h1>
  <p class="muted">{html.escape(result.case.description)}</p>
  <p><b>Mode:</b> {html.escape(result.mode)} | <b>Case:</b> {html.escape(result.case.name)}</p>

  <h2>Configuration</h2>
  <table><tbody>{config_rows}</tbody></table>

  <h2>Checks</h2>
  <table><tbody>{check_rows}</tbody></table>

  <h2>Mesh And Flow</h2>
  <div class="grid">
    <div><h3>Cell area</h3><img src="figures/mesh_area.png" alt="Cell area"></div>
    <div><h3>Head</h3><img src="figures/head_final.png" alt="Head"></div>
    <div><h3>Flux proxy</h3><img src="figures/flux_proxy.png" alt="Flux proxy"></div>
  </div>

  <h2>Transport</h2>
  <img src="figures/concentration_snapshots.png" alt="Concentration snapshots">
  <img src="figures/concentration_profiles.png" alt="Concentration profiles">
  <img src="figures/mass_front.png" alt="Mass and front">

  <h2>Time Signatures</h2>
  <table><thead><tr>{time_header}</tr></thead><tbody>{time_rows}</tbody></table>
</body>
</html>
"""
    (output_dir / "index.html").write_text(body, encoding="utf-8")


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
    denom = 2.0 * math.sqrt(dispersion * time)
    return np.clip(0.5 * source * erfc((x - velocity * time) / denom), 0.0, source)


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


def _round(value: Any, ndigits: int = 8) -> float:
    value = float(value)
    if not math.isfinite(value):
        return value
    return round(value, ndigits)


def _check_class(value: bool) -> str:
    return "ok" if bool(value) else "fail"


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
        "flow.porosity": case.flow.porosity,
        "transport.duration_days": case.transport.duration_days,
        "transport.n_snapshots": case.transport.n_snapshots,
        "transport.source_concentration": case.transport.source_concentration,
        "transport.source_schedule": case.transport.source_schedule,
        "transport.pulse_end_day": case.transport.pulse_end_day,
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
        if mode == "mf6":
            result = run_mf6_case(case, case_output, mf6_exe=mf6_exe)
        elif mode == "synthetic":
            result = run_synthetic_case(case)
        else:
            raise ValueError(f"Unknown mode: {mode}")
        render_case_report(result, case_output)
        results.append(result)
    write_index(results, output_dir)
    return results


def write_index(results: list[CaseResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        "<tr>"
        f"<td><a href='{html.escape(result.case.name)}/index.html'>{html.escape(result.case.name)}</a></td>"
        f"<td>{html.escape(result.mode)}</td>"
        f"<td>{result.signatures['mesh']['n_cells']}</td>"
        f"<td>{result.signatures['mesh']['area_ratio']}</td>"
        f"<td>{all(result.signatures['checks'].values())}</td>"
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
    <thead><tr><th>Case</th><th>Mode</th><th>Cells</th><th>Area ratio</th><th>Checks</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""
    (output_dir / "index.html").write_text(body, encoding="utf-8")


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
