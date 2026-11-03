"""Ogata-Banks (1961) 1D advection-dispersion benchmark against MODFLOW 6 GWT.

Compared with: the Ogata-Banks (1961) concentration profile of 1D advection and dispersion from a constant-concentration inlet.

A semi-infinite column is initially solute-free and subjected to a
constant-concentration injection ``c0`` at ``x = 0`` under steady uniform
flow of pore velocity ``v`` with longitudinal dispersion coefficient
``D``. The analytical solution is the Ogata-Banks profile::

    c(x, t) = c0 / 2 * [ erfc((x - v t) / (2 sqrt(D t)))
                        + exp(v x / D) * erfc((x + v t) / (2 sqrt(D t))) ]

The reference is a 1D MF6 GWF + GWT model: flow is driven by a constant
injection flux on the left and a CHD sink on the right producing a
uniform pore velocity ``v``; transport is solved with a constant
concentration ``c0`` at the inlet and an open boundary at the outlet.
Numerical and analytical concentrations are compared at probe points
along the column at three times.

Three grids run the same column. ``modflow6`` is the rectilinear DIS column
above. ``modflow6_irregular_tri`` and ``modflow6_voronoi`` are DISV strips three
cells wide of jittered triangles and Voronoi polygons
(``tests/validation/helpers/disv_meshes.py``), the topology HydroModPy always
gives GWT. There the end cells hold the exact linear head ``h(x) = i (L - x)`` at
their centers (pore velocity ``v`` for any consistent flux), the inlet cells hold
the concentration ``c0``, and the closed form starts at the mean center of those
cells. A probe averages the cells whose center lies within half a cell of ``x``,
and the closed form is averaged over the same centers. Dispersion keeps MODFLOW 6's
default XT3D, as HydroModPy's GWT does. The flow follows HydroModPy's XT3D rule
(``DisvMesh.xt3d_reason``): the triangle strip has a p95 connection
non-orthogonality of 34 deg, above the 30 deg trigger, so XT3D is on; the Voronoi
strip is orthogonal and runs with the two-point flux. Control run on the triangles
with the two-point flux: 10.2 % instead of 2.7 %.

Tolerance rationale - ``tests/TOLERANCES.md`` row 7: NSE > 0.95 across
all (x, t) probes with a maximum pointwise relative error below 2.5 %
(measured 2.2 % at the production grid). The DISV strips measured 2.52 %
(Voronoi, NSE 0.99979) and 2.71 % (triangles, NSE 0.99976) at the same cell size
of 0.1 m, so they carry their own limits (``DISV_BASE_LIMITS``). The gap is the
scheme's truncation error (TVD limiter and backward Euler at a Courant number of
0.5), not a mesh defect: the refinement test cuts it by a factor of about 4 on every grid
(rectilinear 2.2 to 0.49 %, Voronoi 2.52 to 0.62 %, triangles 2.71 to 0.70 %).
A second test refines dt by 4 and dx by 2 and requires the error to fall below that
of the production run.

Scope - ``solver_sanity``:
   The coupled GWF + GWT column with inlet auxiliary concentration is
   built directly on the flopy SDK because hydromodpy's transport
   plumbing does not yet expose MF6 GWT through the launcher TOML. The
   test therefore validates **MODFLOW 6 GWT against the Ogata-Banks
   analytical solution**, not the hydromodpy pipeline.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.special import erfc

from tests.regression.golden_utils import (
    assert_required_executables,
    resolve_bundled_executable,
)
from tests.validation.helpers import assert_metric_above, assert_metric_below
from tests.validation.helpers.disv_meshes import DisvMesh, strip_mesh

NOT_APPLICABLE = {
    "modflow_nwt": (
        "MODFLOW-NWT has no GWT. HydroModPy transports on NWT with MT3DMS, whose adapter sets "
        "ICBUND to 1 and feeds solute from recharge only, so it cannot hold the constant inlet "
        "concentration this file needs."
    ),
    "boussinesq": (
        "The Boussinesq solver has no transport: the registry holds no transport adapter for it "
        "and the solver page lists its transport as refused. This file runs MODFLOW 6 GWT."
    ),
    "boussinesq_local": (
        "The Boussinesq solver has no transport: the registry holds no transport adapter for it "
        "and the solver page lists its transport as refused. This file runs MODFLOW 6 GWT."
    ),
}

COLUMN_LENGTH_M = 50.0
N_CELLS = 500
POROSITY = 0.3

PORE_VELOCITY_M_PER_DAY = 0.1
DISPERSION_M2_PER_DAY = 0.01

INLET_CONCENTRATION = 1.0
INITIAL_CONCENTRATION = 0.0

DURATION_D = 100.0
N_TRANSPORT_STEPS = 200  # dt = 0.5 day, Courant ~ 0.5 for v=0.1, dx=0.1

# DISV strips: rows of cells across the column and the matrix column of each mesh kind.
DISV_ROWS = 3
# A long thin strip (cells 0.1 to 0.05 m, 50 m long) is stiff: the default 50 inner iterations and
# the COMPLEX preset's ILUT (5 levels, 1e-4 drop) stall on the XT3D matrix of 6000 triangles at
# 1e-6 m. A deeper ILUT converges in under a second to 2e-7 m of the linear head.
DISV_INNER_MAXIMUM = 5000
DISV_FLOW_PRECONDITIONER = {"preconditioner_levels": 10, "preconditioner_drop_tolerance": 1e-10}
DISV_KIND = {"modflow6_irregular_tri": "triangle", "modflow6_voronoi": "voronoi"}

# (NSE floor, max relative error) of the production run on a DISV strip: the NSE floor is twice
# the measured 1 - NSE (2.1e-4 Voronoi, 2.4e-4 triangles) and the error limit 1.1 times the
# measured 2.52 % (Voronoi) and 2.71 % (triangles). The rectilinear column keeps (0.95, 0.025).
DISV_BASE_LIMITS: dict[str, tuple[float, float]] = {
    "modflow6_irregular_tri": (0.9995, 0.030),
    "modflow6_voronoi": (0.9995, 0.0277),
}

OBSERVATION_X_M = (1.0, 5.0, 10.0, 20.0)
OBSERVATION_TIMES_D = (20.0, 60.0, 100.0)


def _ogata_banks_concentration(x_m: float, t_d: float) -> float:
    """Return ``c(x, t)`` for the Ogata-Banks semi-infinite column solution."""
    v = PORE_VELOCITY_M_PER_DAY
    d = DISPERSION_M2_PER_DAY
    denom = 2.0 * math.sqrt(d * t_d)
    term1 = erfc((x_m - v * t_d) / denom)
    # ``exp(v x / D)`` can overflow float64 when v x / D is large; in that
    # regime ``erfc((x + v t) / denom)`` is vanishingly small and the product
    # is well-defined as zero. We compute the log-product to avoid issues.
    exp_arg = v * x_m / d
    erfc_arg = (x_m + v * t_d) / denom
    if exp_arg > 700.0:  # beyond float64 range for plain exp
        # log(erfc(y)) ~ -y^2 - log(y sqrt(pi)) for large y
        if erfc_arg > 0.0:
            log_erfc = -erfc_arg * erfc_arg - math.log(erfc_arg * math.sqrt(math.pi))
        else:
            log_erfc = math.log(erfc(erfc_arg))
        log_product = exp_arg + log_erfc
        term2 = math.exp(log_product) if log_product < 700.0 else float("inf")
    else:
        term2 = math.exp(exp_arg) * erfc(erfc_arg)
    return float(INLET_CONCENTRATION * 0.5 * (term1 + term2))


def _build_and_run_ogata_banks_model(
    workspace: Path,
    n_steps: int = N_TRANSPORT_STEPS,
    n_cells: int = N_CELLS,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the coupled GWF + GWT model and return ``(numerical, analytical)`` grids.

    The returned arrays are shaped ``(len(times), len(x_probes))``.
    """
    import flopy

    mf6_exe = resolve_bundled_executable("mf6")

    cell_size = COLUMN_LENGTH_M / n_cells

    # Aquifer geometry - unit cross-section, uniform cells.
    aquifer_top = 1.0
    aquifer_bot = 0.0
    aquifer_thickness = aquifer_top - aquifer_bot
    hydraulic_conductivity = 1.0  # m/day - chosen with the head gradient so v matches

    # For pore velocity v = K * i / n  ⇒  head gradient i = v n / K.
    head_gradient = PORE_VELOCITY_M_PER_DAY * POROSITY / hydraulic_conductivity
    head_left = head_gradient * COLUMN_LENGTH_M
    head_right = 0.0

    sim = flopy.mf6.MFSimulation(
        sim_name="ogatabanks",
        sim_ws=str(workspace),
        exe_name=str(mf6_exe),
        version="mf6",
    )
    flopy.mf6.ModflowTdis(
        sim,
        time_units="DAYS",
        nper=1,
        perioddata=[(DURATION_D, n_steps, 1.0)],
    )

    # ----- Flow model ------------------------------------------------------
    gwf_name = "gwf1d"
    gwf = flopy.mf6.ModflowGwf(sim, modelname=gwf_name, save_flows=True)
    flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwf_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
        linear_acceleration="CG",
    )
    sim.register_ims_package(sim.get_package(f"{gwf_name}.ims"), [gwf_name])

    flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=1,
        nrow=1,
        ncol=n_cells,
        delr=cell_size,
        delc=1.0,
        top=aquifer_top,
        botm=aquifer_bot,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwfic(gwf, strt=head_left)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=hydraulic_conductivity)
    flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=0,
        ss=0.0,
        sy=0.0,
        steady_state={0: True},
    )
    # Carry a CONCENTRATION auxiliary on CHD so the GWT SSM package can
    # assign entering-water concentration; exiting water uses the local
    # cell concentration automatically.
    flopy.mf6.ModflowGwfchd(
        gwf,
        auxiliary=["CONCENTRATION"],
        stress_period_data={
            0: [
                ((0, 0, 0), head_left, 0.0),
                ((0, 0, n_cells - 1), head_right, 0.0),
            ]
        },
        pname="CHD-1",
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        budget_filerecord=f"{gwf_name}.cbc",
        head_filerecord=f"{gwf_name}.hds",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "ALL")],
    )

    # ----- Transport model -------------------------------------------------
    gwt_name = "gwt1d"
    gwt = flopy.mf6.ModflowGwt(sim, modelname=gwt_name, save_flows=True)
    flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwt_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
        linear_acceleration="BICGSTAB",
    )
    sim.register_ims_package(sim.get_package(f"{gwt_name}.ims"), [gwt_name])

    flopy.mf6.ModflowGwtdis(
        gwt,
        nlay=1,
        nrow=1,
        ncol=n_cells,
        delr=cell_size,
        delc=1.0,
        top=aquifer_top,
        botm=aquifer_bot,
        length_units="METERS",
    )
    flopy.mf6.ModflowGwtic(gwt, strt=INITIAL_CONCENTRATION)
    flopy.mf6.ModflowGwtadv(gwt, scheme="TVD")
    # Longitudinal dispersion only (1D column). The DSP package expects
    # the longitudinal dispersivity alpha_L; with zero molecular diffusion
    # the effective coefficient is alpha_L * |v|. So alpha_L = D / v.
    alpha_l = DISPERSION_M2_PER_DAY / PORE_VELOCITY_M_PER_DAY
    flopy.mf6.ModflowGwtdsp(gwt, xt3d_off=True, alh=alpha_l, ath1=alpha_l, diffc=0.0)
    flopy.mf6.ModflowGwtmst(gwt, porosity=POROSITY)
    flopy.mf6.ModflowGwtssm(gwt, sources=[["CHD-1", "AUX", "CONCENTRATION"]])
    flopy.mf6.ModflowGwtcnc(
        gwt,
        stress_period_data={0: [((0, 0, 0), INLET_CONCENTRATION)]},
    )
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
    success, _buff = sim.run_simulation(silent=True)
    assert success, "MF6 Ogata-Banks simulation did not converge"

    conc_file = flopy.utils.HeadFile(
        workspace / f"{gwt_name}.ucn",
        text="CONCENTRATION",
    )
    times = np.asarray(conc_file.get_times())

    x_centers = np.arange(n_cells) * cell_size + 0.5 * cell_size
    # The CNC fixes the concentration at the center of cell 0, not at the
    # column edge, so the inlet of the reference sits at x_centers[0].
    inlet_x = float(x_centers[0])

    numerical = np.zeros((len(OBSERVATION_TIMES_D), len(OBSERVATION_X_M)))
    analytical = np.zeros_like(numerical)
    for ti, requested_time in enumerate(OBSERVATION_TIMES_D):
        time_idx = int(np.argmin(np.abs(times - requested_time)))
        snapshot = conc_file.get_data(totim=times[time_idx])[0, 0, :]
        for xi, probe_x in enumerate(OBSERVATION_X_M):
            cell_idx = int(np.argmin(np.abs(x_centers - probe_x)))
            numerical[ti, xi] = float(snapshot[cell_idx])
            analytical[ti, xi] = _ogata_banks_concentration(
                float(x_centers[cell_idx]) - inlet_x, float(times[time_idx])
            )

    return numerical, analytical


def _build_and_run_ogata_banks_model_disv(
    workspace: Path,
    solver: str,
    n_steps: int = N_TRANSPORT_STEPS,
    n_cells: int = N_CELLS,
    force_xt3d: bool | None = None,
) -> tuple[np.ndarray, np.ndarray, DisvMesh]:
    """Run the coupled GWF + GWT strip on a triangle or Voronoi DISV mesh.

    The strip is ``DISV_ROWS`` cells wide and ``n_cells`` cells long, jittered
    (``disv_meshes.strip_mesh``). The end cells hold the exact linear head
    ``h(x) = i (L - x)`` at their centers, so the pore velocity is ``v`` for any
    consistent flux, and the inlet cells hold the concentration ``c0``. The inlet of
    the closed form sits at the mean center of those cells. A probe averages the
    cells whose center is within half a cell of ``x``, and the closed form is
    averaged over the same centers. Dispersion keeps MODFLOW 6's default XT3D, as
    HydroModPy's GWT does; the flow follows HydroModPy's XT3D rule.
    ``force_xt3d`` overrides that rule for the flow (control runs).

    The returned arrays are shaped ``(len(times), len(x_probes))``.
    """
    import flopy

    cell_size = COLUMN_LENGTH_M / n_cells
    mesh = strip_mesh(
        DISV_KIND[solver],
        length=COLUMN_LENGTH_M,
        width=DISV_ROWS * cell_size,
        spacing=cell_size,
        top=1.0,
        botm=[0.0],
    )
    use_xt3d = mesh.xt3d if force_xt3d is None else force_xt3d
    xc = mesh.centers[:, 0]
    head_gradient = PORE_VELOCITY_M_PER_DAY * POROSITY / 1.0  # K = 1 m/day
    inlet_cells = mesh.cells_on_side("x", 0.0)
    outlet_cells = mesh.cells_on_side("x", COLUMN_LENGTH_M)
    chd = [
        ((0, ic), head_gradient * (COLUMN_LENGTH_M - float(xc[ic])), 0.0)
        for ic in inlet_cells + outlet_cells
    ]

    sim = flopy.mf6.MFSimulation(
        sim_name="ogatabanks",
        sim_ws=str(workspace),
        exe_name=str(resolve_bundled_executable("mf6")),
        version="mf6",
    )
    flopy.mf6.ModflowTdis(sim, time_units="DAYS", nper=1, perioddata=[(DURATION_D, n_steps, 1.0)])

    gwf_name = "gwf1d"
    gwf = flopy.mf6.ModflowGwf(sim, modelname=gwf_name, save_flows=True)
    flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwf_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
        inner_maximum=DISV_INNER_MAXIMUM,
        linear_acceleration="BICGSTAB",
        **DISV_FLOW_PRECONDITIONER,
    )
    sim.register_ims_package(sim.get_package(f"{gwf_name}.ims"), [gwf_name])
    flopy.mf6.ModflowGwfdisv(gwf, length_units="METERS", **mesh.disv_kwargs())
    flopy.mf6.ModflowGwfic(gwf, strt=head_gradient * COLUMN_LENGTH_M)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0, xt3doptions=["XT3D"] if use_xt3d else None)
    flopy.mf6.ModflowGwfsto(gwf, iconvert=0, ss=0.0, sy=0.0, steady_state={0: True})
    flopy.mf6.ModflowGwfchd(
        gwf, auxiliary=["CONCENTRATION"], stress_period_data={0: chd}, pname="CHD-1"
    )
    flopy.mf6.ModflowGwfoc(
        gwf,
        budget_filerecord=f"{gwf_name}.cbc",
        head_filerecord=f"{gwf_name}.hds",
        saverecord=[("HEAD", "LAST"), ("BUDGET", "ALL")],
    )

    gwt_name = "gwt1d"
    gwt = flopy.mf6.ModflowGwt(sim, modelname=gwt_name, save_flows=True)
    flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwt_name}.ims",
        print_option="SUMMARY",
        complexity="SIMPLE",
        outer_dvclose=1e-8,
        inner_dvclose=1e-10,
        inner_maximum=DISV_INNER_MAXIMUM,
        linear_acceleration="BICGSTAB",
    )
    sim.register_ims_package(sim.get_package(f"{gwt_name}.ims"), [gwt_name])
    flopy.mf6.ModflowGwtdisv(gwt, length_units="METERS", **mesh.disv_kwargs())
    flopy.mf6.ModflowGwtic(gwt, strt=INITIAL_CONCENTRATION)
    flopy.mf6.ModflowGwtadv(gwt, scheme="TVD")
    alpha_l = DISPERSION_M2_PER_DAY / PORE_VELOCITY_M_PER_DAY
    flopy.mf6.ModflowGwtdsp(gwt, alh=alpha_l, ath1=alpha_l, diffc=0.0)
    flopy.mf6.ModflowGwtmst(gwt, porosity=POROSITY)
    flopy.mf6.ModflowGwtssm(gwt, sources=[["CHD-1", "AUX", "CONCENTRATION"]])
    flopy.mf6.ModflowGwtcnc(
        gwt,
        stress_period_data={0: [((0, ic), INLET_CONCENTRATION) for ic in inlet_cells]},
    )
    flopy.mf6.ModflowGwtoc(
        gwt,
        budget_filerecord=f"{gwt_name}.cbc",
        concentration_filerecord=f"{gwt_name}.ucn",
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
    )
    flopy.mf6.ModflowGwfgwt(sim, exgtype="GWF6-GWT6", exgmnamea=gwf_name, exgmnameb=gwt_name)

    sim.write_simulation(silent=True)
    success, _buff = sim.run_simulation(silent=True)
    assert success, "MF6 Ogata-Banks simulation on a DISV mesh did not converge"

    conc_file = flopy.utils.HeadFile(workspace / f"{gwt_name}.ucn", text="CONCENTRATION")
    times = np.asarray(conc_file.get_times())
    inlet_x = float(np.mean(xc[inlet_cells]))

    numerical = np.zeros((len(OBSERVATION_TIMES_D), len(OBSERVATION_X_M)))
    analytical = np.zeros_like(numerical)
    for ti, requested_time in enumerate(OBSERVATION_TIMES_D):
        time_idx = int(np.argmin(np.abs(times - requested_time)))
        snapshot = conc_file.get_data(totim=times[time_idx])[0, 0, :]
        for xi, probe_x in enumerate(OBSERVATION_X_M):
            cells = np.flatnonzero(np.abs(xc - probe_x) <= 0.5 * cell_size)
            numerical[ti, xi] = float(np.mean(snapshot[cells]))
            analytical[ti, xi] = float(
                np.mean(
                    [
                        _ogata_banks_concentration(float(xc[c]) - inlet_x, float(times[time_idx]))
                        for c in cells
                    ]
                )
            )

    return numerical, analytical, mesh


def _score(numerical: np.ndarray, analytical: np.ndarray) -> tuple[float, float]:
    """Return ``(nse, max relative error where c > 1e-3 c0)`` over all probes."""
    num = numerical.ravel()
    ana = analytical.ravel()
    nse = 1.0 - float(np.sum((num - ana) ** 2)) / float(np.sum((ana - ana.mean()) ** 2))
    mask = ana > 1e-3
    max_rel = float((np.abs(num[mask] - ana[mask]) / ana[mask]).max())
    return nse, max_rel


def _require_mf6() -> None:
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )


def _run_column(
    workspace: Path, solver: str, n_steps: int = N_TRANSPORT_STEPS, n_cells: int = N_CELLS
) -> tuple[np.ndarray, np.ndarray]:
    """Run the column on the grid of ``solver`` and return ``(numerical, analytical)``."""
    if solver == "modflow6":
        return _build_and_run_ogata_banks_model(workspace, n_steps=n_steps, n_cells=n_cells)
    numerical, analytical, _mesh = _build_and_run_ogata_banks_model_disv(
        workspace, solver, n_steps=n_steps, n_cells=n_cells
    )
    return numerical, analytical


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.solver_sanity
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow6", marks=pytest.mark.slow),
        pytest.param("modflow6_irregular_tri", marks=pytest.mark.slow),
        pytest.param("modflow6_voronoi", marks=pytest.mark.fast),
    ],
)
def test_ogata_banks_1d_transport_matches_analytical_reference(solver: str, tmp_path: Path) -> None:
    """Run the MF6 GWF+GWT column and compare ``c(x, t)`` to the Ogata-Banks profile."""
    _require_mf6()
    nse, max_rel = _score(*_run_column(tmp_path, solver))
    nse_min, max_rel_limit = DISV_BASE_LIMITS.get(solver, (0.95, 0.025))
    assert_metric_above("Nash-Sutcliffe efficiency of the concentration", nse, nse_min, ideal=1.0)
    assert_metric_below(
        "Largest relative concentration error where c > 1e-3 c0", max_rel, max_rel_limit
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.slow
@pytest.mark.solver_sanity
@pytest.mark.parametrize("solver", ["modflow6", "modflow6_irregular_tri", "modflow6_voronoi"])
def test_ogata_banks_error_shrinks_under_refinement(solver: str, tmp_path: Path) -> None:
    """Refining dt by 4 and dx by 2 must reduce the error, so no compensation hides.

    Measured: 2.2 % at the production grid, 0.5 % refined. Refining dt alone
    is not monotone (spatial TVD error dominates and has the opposite sign to
    the implicit Euler error), hence the joint refinement. The DISV strips go
    from 2.5 % (Voronoi) and 2.7 % (triangles) to 0.62 % and 0.70 %.
    """
    _require_mf6()
    _, base_err = _score(*_run_column(tmp_path / "base", solver))
    nse, refined_err = _score(
        *_run_column(
            tmp_path / "refined", solver, n_steps=4 * N_TRANSPORT_STEPS, n_cells=2 * N_CELLS
        )
    )
    assert_metric_above("Refined-grid Nash-Sutcliffe efficiency", nse, 0.99, ideal=1.0)
    assert_metric_below("Refined-grid largest relative concentration error", refined_err, 0.01)
    assert_metric_below("Refined error over production error", refined_err / base_err, 0.5)
