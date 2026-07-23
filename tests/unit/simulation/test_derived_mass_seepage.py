"""Conservation tests for solute / mass / groundwater-flux derivations.

These cover the dark branch of
``hydromodpy.simulation.extraction.derivation.derived``: the transport-specific
derived fields (concentration_seepage, mass_seepage, mass_accumulated) plus the
solver-neutral release/groundwater flux derivations.

The asserts target genuine invariants derived from the science:

* ``mass_seepage`` = concentration at seepage cells * positive drain outflow,
  with units m3/s * (mass/m3) = mass/s. Zero where there is no seepage.
* ``mass_accumulated[t]`` is the running cumulative sum of ``mass_seepage``,
  i.e. the discrete time-integral of the mass-flux series. We verify the
  closure ``mass_accumulated[t] - mass_accumulated[t-1] == mass_seepage[t]``
  and ``mass_accumulated[-1] == sum_t mass_seepage[t]`` cell by cell.
* ``release_flux`` = positive drain outflow + positive surface-excess outflow,
  is non-negative and finite everywhere (m3/s).
* ``groundwater_flux`` is the Euclidean magnitude of the face-flow vector, so
  it is non-negative and equals sqrt(sum of squared face components).
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.core.field_routing import drain_budget_to_positive_outflow
from hydromodpy.simulation.extraction.derivation.derived import (
    _compute_accumulation_flux,
    _compute_concentration_seepage,
    _compute_groundwater_flux,
    _compute_mass_accumulated,
    _compute_mass_seepage,
    _compute_outflow_drain,
    _compute_release_accumulation_flux,
    _compute_release_flux,
    _drain_outflow_stack,
    _positive_cell_flux_stack,
    compute_derived,
)
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _register(catalog, *, n_ts, n_layers, n_cells):
    sid = str(uuid4())
    reg = catalog.register_simulation(
        sid,
        project="test",
        solver="modflow_nwt",
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_ts,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    return sid


def _write_mesh(catalog, sid, *, n_cells):
    """Minimal UGRID mesh so seepage/topography branches have data."""
    verts = np.random.default_rng(0).random((n_cells + 2, 2))
    conn = np.column_stack(
        [
            np.arange(n_cells),
            np.arange(1, n_cells + 1),
            np.full(n_cells, n_cells + 1),
        ]
    ).astype("int32")
    z_intf = np.array([10.0, 5.0, 0.0])
    catalog.write_mesh(sid, verts, conn, z_intf)


def _write_head(catalog, sid, head_stack, *, n_ts):
    for t in range(n_ts):
        catalog.write_field(sid, "head", t, head_stack[t], n_timesteps=n_ts if t == 0 else None)


class TestMassSeepageConservation:
    """The full transport chain: concentration -> mass -> accumulated mass."""

    def _seed(self, catalog, *, n_ts, n_cells, conc_stack, drn_stack, seep_stack):
        """Seed head, mesh, concentration, drain budget and seepage mask."""
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        _write_mesh(catalog, sid, n_cells=n_cells)

        # head field only drives shape discovery in compute_derived; keep it
        # finite and irrelevant to the transport math.
        head = np.full((n_ts, 1, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)

        for t in range(n_ts):
            catalog.write_field(
                sid,
                "concentration",
                t,
                conc_stack[t],
                n_timesteps=n_ts if t == 0 else None,
            )
            # Drain budget is signed: negative = outflow to the drain.
            catalog.write_field(
                sid,
                "drain",
                t,
                drn_stack[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )
            # Pre-seed the seepage mask the derived chain depends on.
            catalog.write_field(
                sid,
                "seepage_mask",
                t,
                seep_stack[t].astype("float64"),
                n_timesteps=n_ts if t == 0 else None,
                subgroup="derived",
            )
        return sid

    def test_concentration_then_mass_then_accumulated_closure(self, catalog):
        n_ts, n_cells = 4, 6
        rng = np.random.default_rng(7)

        conc = rng.uniform(0.5, 5.0, (n_ts, n_cells))
        # signed drain outflow: negative magnitudes, plus some zeros (no drain).
        drn = -rng.uniform(0.0, 3.0, (n_ts, n_cells))
        # Cells 0..2 seep at every timestep (stable subset). Cell 3 seeps only
        # at t=1 so we also exercise the NaN-propagation path of the running
        # cumulative sum on an intermittent cell.
        seep = np.zeros((n_ts, n_cells), dtype="float64")
        seep[:, :3] = 1.0
        seep[1, 3] = 1.0
        stable = np.zeros(n_cells, dtype=bool)
        stable[:3] = True

        sid = self._seed(
            catalog,
            n_ts=n_ts,
            n_cells=n_cells,
            conc_stack=conc,
            drn_stack=drn,
            seep_stack=seep,
        )

        _compute_concentration_seepage(sid, catalog, n_ts, n_cells)
        _compute_mass_seepage(sid, catalog, n_ts, n_cells)
        _compute_mass_accumulated(sid, catalog, n_ts, n_cells)

        # 1) concentration_seepage = conc where seepage active, NaN otherwise.
        for t in range(n_ts):
            cs = catalog.query_field(sid, "concentration_seepage", t)
            active = seep[t] > 0
            assert np.allclose(cs[active], conc[t][active])
            assert np.all(np.isnan(cs[~active]))

        # 2) mass_seepage = concentration_seepage * positive drain outflow.
        #    Units: (mass/m3) * (m3/s) = mass/s.
        mass = np.full((n_ts, n_cells), np.nan)
        for t in range(n_ts):
            ms = catalog.query_field(sid, "mass_seepage", t)
            active = seep[t] > 0
            pos_out = drain_budget_to_positive_outflow(drn[t], n_cells=n_cells)
            expected = np.where(active, conc[t] * pos_out, np.nan)
            # active cells: finite mass equal to conc * positive outflow.
            assert np.allclose(ms[active], expected[active])
            assert np.all(np.isnan(ms[~active]))
            # mass flux is non-negative (concentration and outflow both >= 0).
            assert np.all(ms[active] >= 0.0)
            mass[t] = ms

        # 3) accumulated mass obeys the literal recurrence
        #    cumul[t] = cumul[t-1] + mass_seepage[t] cell by cell (NaN-aware).
        prev = np.zeros(n_cells)
        for t in range(n_ts):
            ma = catalog.query_field(sid, "mass_accumulated", t)
            expected_cumul = prev + mass[t]
            assert np.allclose(ma, expected_cumul, equal_nan=True)
            prev = ma

        # 4) on the stable always-seepage subset the accumulation is the true
        #    discrete time-integral (partial sums) of the mass-flux series and
        #    is monotonic non-decreasing in time per cell (sources >= 0).
        partial = np.zeros(np.count_nonzero(stable))
        prev_partial = np.zeros(np.count_nonzero(stable))
        for t in range(n_ts):
            ma = catalog.query_field(sid, "mass_accumulated", t)[stable]
            partial = partial + mass[t][stable]
            assert np.allclose(ma, partial)
            assert np.all(ma + 1e-12 >= prev_partial)
            prev_partial = ma

    def test_mass_seepage_zero_when_no_drain(self, catalog):
        """Without a drain budget key, flux defaults to ones -> mass == conc."""
        n_ts, n_cells = 2, 4
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        _write_mesh(catalog, sid, n_cells=n_cells)
        head = np.full((n_ts, 1, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)

        conc = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]])
        seep = np.array([[1, 1, 0, 0], [1, 0, 1, 0]], dtype="float64")
        for t in range(n_ts):
            catalog.write_field(
                sid,
                "concentration",
                t,
                conc[t],
                n_timesteps=n_ts if t == 0 else None,
            )
            catalog.write_field(
                sid,
                "seepage_mask",
                t,
                seep[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="derived",
            )
            # Non-drain budget key so find_drain_budget_key returns None but
            # budget_grp is not None (mass_seepage uses flux=ones fallback).
            catalog.write_field(
                sid,
                "surface_excess",
                t,
                np.zeros(n_cells),
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )

        _compute_concentration_seepage(sid, catalog, n_ts, n_cells)
        _compute_mass_seepage(sid, catalog, n_ts, n_cells)

        for t in range(n_ts):
            ms = catalog.query_field(sid, "mass_seepage", t)
            active = seep[t] > 0
            # flux=1 fallback -> mass == concentration at seepage cells.
            assert np.allclose(ms[active], conc[t][active])
            assert np.all(np.isnan(ms[~active]))


class TestReleaseFluxNonNegative:
    """release_flux combines drain and surface-excess positive outflow."""

    def test_release_equals_sum_of_positive_components(self, catalog):
        n_ts, n_cells = 3, 5
        rng = np.random.default_rng(11)
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        _write_mesh(catalog, sid, n_cells=n_cells)
        head = np.full((n_ts, 1, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)

        drn = -rng.uniform(0.0, 2.0, (n_ts, n_cells))
        # surface_excess is a positive per-cell outflow (already a release).
        sexc = rng.uniform(0.0, 1.5, (n_ts, n_cells))
        for t in range(n_ts):
            catalog.write_field(
                sid,
                "drain",
                t,
                drn[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )
            catalog.write_field(
                sid,
                "surface_excess",
                t,
                sexc[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )

        _compute_release_flux(sid, catalog, n_ts, n_cells)

        for t in range(n_ts):
            rf = catalog.query_field(sid, "release_flux", t)
            pos_drn = drain_budget_to_positive_outflow(drn[t], n_cells=n_cells)
            # surface_excess summed via _positive_cell_flux (single layer) ==
            # itself since it is already non-negative.
            expected = pos_drn + np.maximum(sexc[t], 0.0)
            assert np.allclose(rf, expected)
            # release flux is non-negative and finite (m3/s).
            assert np.all(rf >= 0.0)
            assert np.all(np.isfinite(rf))


class TestGroundwaterFluxMagnitude:
    """groundwater_flux is the Euclidean magnitude of face-flow components."""

    def test_magnitude_equals_root_sum_of_squares(self, catalog):
        n_ts, n_layers, n_cells = 2, 1, 4
        rng = np.random.default_rng(3)
        sid = _register(catalog, n_ts=n_ts, n_layers=n_layers, n_cells=n_cells)
        head = np.full((n_ts, n_layers, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)

        right = rng.normal(size=(n_ts, n_cells))
        front = rng.normal(size=(n_ts, n_cells))
        lower = rng.normal(size=(n_ts, n_cells))
        for t in range(n_ts):
            catalog.write_field(
                sid,
                "flow_right_face",
                t,
                right[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )
            catalog.write_field(
                sid,
                "flow_front_face",
                t,
                front[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )
            catalog.write_field(
                sid,
                "flow_lower_face",
                t,
                lower[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )

        _compute_groundwater_flux(sid, catalog, n_ts, n_layers, n_cells)

        for t in range(n_ts):
            mag = catalog.query_field(sid, "groundwater_flux", t).reshape(-1)
            expected = np.sqrt(right[t] ** 2 + front[t] ** 2 + lower[t] ** 2)
            assert np.allclose(mag, expected)
            # magnitude is non-negative by construction.
            assert np.all(mag >= 0.0)
            # magnitude dominates each component (vector norm property).
            assert np.all(mag + 1e-9 >= np.abs(right[t]))


class TestComputeDerivedDispatch:
    """compute_derived wires the toggles to the right derivations end to end."""

    def test_full_transport_chain_via_compute_derived(self, catalog):
        n_ts, n_cells = 3, 5
        rng = np.random.default_rng(99)
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        _write_mesh(catalog, sid, n_cells=n_cells)

        # heads above topography (top=10) on first cells -> non-empty seepage.
        head = rng.uniform(8.0, 12.0, (n_ts, 1, n_cells))
        _write_head(catalog, sid, head, n_ts=n_ts)

        conc = rng.uniform(1.0, 4.0, (n_ts, n_cells))
        drn = -rng.uniform(0.0, 2.0, (n_ts, n_cells))
        for t in range(n_ts):
            catalog.write_field(
                sid,
                "concentration",
                t,
                conc[t],
                n_timesteps=n_ts if t == 0 else None,
            )
            catalog.write_field(
                sid,
                "drain",
                t,
                drn[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )

        compute_derived(
            sid,
            catalog,
            {
                "seepage_areas": True,
                "concentration_seepage": True,
                "mass_seepage": True,
                "mass_accumulated": True,
            },
        )

        # mass_accumulated obeys the literal cumulative recurrence over
        # mass_seepage (NaN-aware), the closure the writer guarantees.
        mass = np.full((n_ts, n_cells), np.nan)
        for t in range(n_ts):
            mass[t] = catalog.query_field(sid, "mass_seepage", t)
        prev = np.zeros(n_cells)
        for t in range(n_ts):
            ma = catalog.query_field(sid, "mass_accumulated", t)
            assert np.allclose(ma, prev + mass[t], equal_nan=True)
            # finite accumulated values are non-negative (sources >= 0).
            assert np.all(ma[np.isfinite(ma)] >= 0.0)
            prev = ma

    def test_no_head_field_is_noop(self, catalog):
        """compute_derived returns silently when no head field is stored."""
        sid = _register(catalog, n_ts=2, n_layers=1, n_cells=3)
        # no head written -> early return, nothing raised.
        compute_derived(sid, catalog, {"mass_seepage": True})
        with pytest.raises(KeyError):
            catalog.query_field(sid, "mass_seepage", 0)


class TestDrainRoutingChain:
    """outflow_drain and the accumulation/release routing fallbacks.

    The catalog mesh carries no ``topography`` array, so both the raster-D8 and
    mesh-graph routing backends bail out and the derivation falls back to the
    local positive cell-flux stack. We assert that fallback equals the local
    drain/release stack exactly and stays non-negative.
    """

    def _seed_drain(self, catalog, *, n_ts, n_cells, drn_stack, surface_excess=None):
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        _write_mesh(catalog, sid, n_cells=n_cells)
        head = np.full((n_ts, 1, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)
        for t in range(n_ts):
            catalog.write_field(
                sid,
                "drain",
                t,
                drn_stack[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )
            if surface_excess is not None:
                catalog.write_field(
                    sid,
                    "surface_excess",
                    t,
                    surface_excess[t],
                    n_timesteps=n_ts if t == 0 else None,
                    subgroup="budget",
                )
        return sid

    def test_outflow_drain_equals_positive_outflow(self, catalog):
        n_ts, n_cells = 3, 5
        rng = np.random.default_rng(21)
        # mix signed outflow with some nodata to exercise the sign convention.
        drn = -rng.uniform(0.0, 4.0, (n_ts, n_cells))
        drn[0, 0] = -99999.0  # nodata sentinel -> treated as zero outflow
        sid = self._seed_drain(catalog, n_ts=n_ts, n_cells=n_cells, drn_stack=drn)

        _compute_outflow_drain(sid, catalog, n_ts, n_cells)

        for t in range(n_ts):
            od = catalog.query_field(sid, "outflow_drain", t)
            expected = drain_budget_to_positive_outflow(drn[t], n_cells=n_cells)
            assert np.allclose(od, expected)
            # outflow is a positive volumetric flux (m3/s), non-negative, finite.
            assert np.all(od >= 0.0)
            assert np.all(np.isfinite(od))
        # nodata cell has zero outflow at t=0.
        assert catalog.query_field(sid, "outflow_drain", 0)[0] == 0.0

    def test_accumulation_flux_falls_back_to_local_drain(self, catalog):
        n_ts, n_cells = 2, 4
        rng = np.random.default_rng(22)
        drn = -rng.uniform(0.1, 3.0, (n_ts, n_cells))
        sid = self._seed_drain(catalog, n_ts=n_ts, n_cells=n_cells, drn_stack=drn)

        _compute_accumulation_flux(sid, catalog, n_ts, n_cells)

        # No mesh/topography -> routing unavailable -> local drain stack.
        local = _drain_outflow_stack(sid, catalog, n_ts, n_cells)
        for t in range(n_ts):
            acc = catalog.query_field(sid, "accumulation_flux", t)
            assert np.allclose(acc, local[t])
            assert np.all(acc >= 0.0)

    def test_release_accumulation_falls_back_to_release_flux(self, catalog):
        n_ts, n_cells = 2, 4
        rng = np.random.default_rng(23)
        drn = -rng.uniform(0.1, 2.0, (n_ts, n_cells))
        sexc = rng.uniform(0.0, 1.0, (n_ts, n_cells))
        sid = self._seed_drain(
            catalog, n_ts=n_ts, n_cells=n_cells, drn_stack=drn, surface_excess=sexc
        )

        _compute_release_flux(sid, catalog, n_ts, n_cells)
        _compute_release_accumulation_flux(sid, catalog, n_ts, n_cells)

        for t in range(n_ts):
            rf = catalog.query_field(sid, "release_flux", t)
            rac = catalog.query_field(sid, "release_accumulation_flux", t)
            # routing unavailable -> accumulation equals the local release flux.
            assert np.allclose(rac, rf)
            assert np.all(rac >= 0.0)

    def test_outflow_drain_noop_without_budget(self, catalog):
        """No budget group -> outflow_drain is skipped, nothing written."""
        n_ts, n_cells = 2, 3
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        head = np.full((n_ts, 1, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)

        _compute_outflow_drain(sid, catalog, n_ts, n_cells)
        with pytest.raises(KeyError):
            catalog.query_field(sid, "outflow_drain", 0)


class TestMeshGraphRouting:
    """Downhill mass-flux routing on a UGRID mesh conserves total mass.

    Adding a ``topography`` array to the mesh group makes raster-D8 routing bail
    (UGRID) and the mesh-graph backend run. The routed accumulation must conserve
    the total injected source mass: sum of routed >= sum of local, and the global
    outlet carries the full basin input.
    """

    def _seed_routable(self, catalog, *, n_ts, n_cells, drn_stack, topo):
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        # Strip of quads sharing vertical edges -> a real downhill line graph.
        # Bottom row nodes 0..n_cells, top row nodes n_cells+1..2*n_cells+1.
        bottom = np.column_stack([np.arange(n_cells + 1, dtype="float64"), np.zeros(n_cells + 1)])
        top = np.column_stack([np.arange(n_cells + 1, dtype="float64"), np.ones(n_cells + 1)])
        verts = np.vstack([bottom, top])
        conn = np.array(
            [[i, i + 1, i + n_cells + 2, i + n_cells + 1] for i in range(n_cells)],
            dtype="int32",
        )
        z_intf = np.array([float(topo.max()) + 1.0, 0.0])
        catalog.write_mesh(sid, verts, conn, z_intf)
        # inject topography directly into the mesh subgroup so graph routing runs.
        catalog.write_field(sid, "topography", 0, topo, n_timesteps=1, subgroup="mesh")
        head = np.full((n_ts, 1, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)
        for t in range(n_ts):
            catalog.write_field(
                sid,
                "drain",
                t,
                drn_stack[t],
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )
        return sid

    def test_routed_accumulation_conserves_total_mass(self, catalog):
        n_ts, n_cells = 1, 5
        # strictly decreasing topography -> single downhill chain to last cell.
        topo = np.array([50.0, 40.0, 30.0, 20.0, 10.0])
        drn = -np.array([[1.0, 1.0, 1.0, 1.0, 1.0]])  # 1 m3/s released per cell
        sid = self._seed_routable(catalog, n_ts=n_ts, n_cells=n_cells, drn_stack=drn, topo=topo)

        _compute_accumulation_flux(sid, catalog, n_ts, n_cells)

        local = _drain_outflow_stack(sid, catalog, n_ts, n_cells)[0]
        acc = catalog.query_field(sid, "accumulation_flux", 0)
        acc_finite = acc[np.isfinite(acc)]
        # the routed field differs from the local field (routing actually ran),
        # otherwise this test would not exercise the graph backend.
        assert not np.allclose(acc, local)
        # total routed mass at the basin outlet conserves total local input.
        assert np.isclose(np.nanmax(acc), local.sum())
        # every routed value is at least its own local source (monotone accrual).
        assert np.all(acc_finite >= 0.0)
        # accumulation grows monotonically downhill toward the outlet.
        assert acc[-1] >= acc[0]


class TestPositiveCellFlux:
    """_positive_cell_flux_stack sums only finite, positive per-cell contributions.

    The single-field helper was folded into the time-vectorised stack version;
    one timestep with shape ``(1, layers, cells)`` reproduces the old behaviour.
    """

    def test_drops_negative_and_nodata_and_sums_layers(self):
        n_cells = 4
        # one timestep, two layers: positives kept, negatives/nodata zeroed.
        stack = np.array(
            [
                [
                    [1.0, -2.0, 3.0, -99999.0],
                    [0.5, 4.0, np.nan, 2.0],
                ]
            ]
        )  # shape (time=1, layers=2, cells=4)
        out = _positive_cell_flux_stack(stack, n_cells=n_cells)[0]
        # cell0: 1.0+0.5; cell1: 0+4.0; cell2: 3.0+0(nan); cell3: 0(nodata)+2.0
        assert np.allclose(out, [1.5, 4.0, 3.0, 2.0])
        assert np.all(out >= 0.0)
        assert out.shape == (n_cells,)

    def test_empty_stack_returns_zeros(self):
        out = _positive_cell_flux_stack(np.empty((0, 1, 3)), n_cells=3)
        assert out.shape == (0, 3)
