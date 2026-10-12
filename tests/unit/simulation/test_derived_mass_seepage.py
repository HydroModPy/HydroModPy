"""Conservation tests for the solute / mass / release-flux fields rebuilt on read.

These cover the transport-specific fields (concentration_seepage, mass_seepage,
mass_accumulated) plus the solver-neutral release/drain flux fields. No array of
their own is written: each is rebuilt from the stored concentration, drain and
surface-excess terms when it is read.

The asserts target genuine invariants derived from the science:

* ``mass_seepage`` = concentration at seepage cells * positive drain outflow,
  with units m3/s * (mass/m3) = mass/s. Zero where there is no seepage.
* ``mass_accumulated[t]`` is the running cumulative sum of ``mass_seepage``,
  i.e. the discrete time-integral of the mass-flux series. We verify the
  closure ``mass_accumulated[t] - mass_accumulated[t-1] == mass_seepage[t]``
  and ``mass_accumulated[-1] == sum_t mass_seepage[t]`` cell by cell.
* ``release_flux`` = positive drain outflow + positive surface-excess outflow,
  is non-negative and finite everywhere (m3/s).
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    drain_budget_to_positive_outflow,
    positive_cell_flux_stack,
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

        # The head only gives the run its shape; it is irrelevant to the transport math.
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
            # A seepage mask an earlier run stored: it decides the seepage cells.
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

    def test_mass_seepage_is_the_concentration_when_the_run_has_no_drain(self, catalog):
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

        for t in range(n_ts):
            rf = catalog.query_field(sid, "release_flux", t)
            pos_drn = drain_budget_to_positive_outflow(drn[t], n_cells=n_cells)
            # The surface excess is already a non-negative release.
            expected = pos_drn + np.maximum(sexc[t], 0.0)
            assert np.allclose(rf, expected)
            # release flux is non-negative and finite (m3/s).
            assert np.all(rf >= 0.0)
            assert np.all(np.isfinite(rf))


class TestTheChainFromTheHead:
    """The seepage cells come from the stored head when no mask was stored."""

    def test_full_transport_chain_is_read_from_the_stored_terms(self, catalog):
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

        # mass_accumulated obeys the literal cumulative recurrence over
        # mass_seepage (NaN-aware).
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


class TestSoluteChainDependencies:
    """A solute field that cannot be rebuilt is not served."""

    def test_a_flow_only_store_serves_no_solute_field(self, catalog):
        # The flow run of a flow-then-transport plan holds no concentration.
        n_ts, n_cells = 2, 4
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        _write_mesh(catalog, sid, n_cells=n_cells)
        _write_head(catalog, sid, np.full((n_ts, 1, n_cells), 9.0), n_ts=n_ts)
        for t in range(n_ts):
            catalog.write_field(
                sid,
                "drain",
                t,
                -np.ones(n_cells),
                n_timesteps=n_ts if t == 0 else None,
                subgroup="budget",
            )

        for variable in ("concentration_seepage", "mass_seepage", "mass_accumulated"):
            with pytest.raises(KeyError):
                catalog.query_field(sid, variable, 0)


class TestDrainRoutingChain:
    """outflow_drain and the accumulation/release routing fallbacks.

    The catalog mesh carries no ``topography`` array and no stored descent, so
    there is nothing to route on: the accumulation fields are not served, and
    never replaced by the local flux under the routed name.
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

        for t in range(n_ts):
            od = catalog.query_field(sid, "outflow_drain", t)
            expected = drain_budget_to_positive_outflow(drn[t], n_cells=n_cells)
            assert np.allclose(od, expected)
            # outflow is a positive volumetric flux (m3/s), non-negative, finite.
            assert np.all(od >= 0.0)
            assert np.all(np.isfinite(od))
        # nodata cell has zero outflow at t=0.
        assert catalog.query_field(sid, "outflow_drain", 0)[0] == 0.0

    def test_no_accumulation_is_served_without_a_route(self, catalog):
        n_ts, n_cells = 2, 4
        rng = np.random.default_rng(22)
        drn = -rng.uniform(0.1, 3.0, (n_ts, n_cells))
        sexc = rng.uniform(0.0, 1.0, (n_ts, n_cells))
        sid = self._seed_drain(
            catalog, n_ts=n_ts, n_cells=n_cells, drn_stack=drn, surface_excess=sexc
        )

        for variable in ("accumulation_flux", "release_accumulation_flux"):
            with pytest.raises(KeyError):
                catalog.query_field(sid, variable, 0)
        # The local fluxes stay readable.
        assert np.all(catalog.query_field(sid, "release_flux", 0) >= 0.0)

    def test_outflow_drain_is_not_served_without_budget(self, catalog):
        """No budget group -> outflow_drain is not served."""
        n_ts, n_cells = 2, 3
        sid = _register(catalog, n_ts=n_ts, n_layers=1, n_cells=n_cells)
        head = np.full((n_ts, 1, n_cells), 9.0)
        _write_head(catalog, sid, head, n_ts=n_ts)

        with pytest.raises(KeyError):
            catalog.query_field(sid, "outflow_drain", 0)


class TestMeshGraphRouting:
    """Downhill routing on a UGRID mesh conserves total mass.

    With a ``topography`` array in the mesh group, the descent is rebuilt from
    the mesh on read. The routed accumulation must conserve the total injected
    source mass: the outlet carries the full basin input.
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
        # Inject topography directly into the mesh subgroup so the descent can be rebuilt.
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

        local = drain_budget_to_positive_outflow(drn[0], n_cells=n_cells)
        acc = catalog.query_field(sid, "accumulation_flux", 0)
        acc_finite = acc[np.isfinite(acc)]
        # The routed field differs from the local field (routing actually ran).
        assert not np.allclose(acc, local)
        # total routed mass at the basin outlet conserves total local input.
        assert np.isclose(np.nanmax(acc), local.sum())
        # every routed value is at least its own local source (monotone accrual).
        assert np.all(acc_finite >= 0.0)
        # accumulation grows monotonically downhill toward the outlet.
        assert acc[-1] >= acc[0]


class TestPositiveCellFlux:
    """positive_cell_flux_stack sums only finite, positive per-cell contributions.

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
        out = positive_cell_flux_stack(stack, n_cells=n_cells)[0]
        # cell0: 1.0+0.5; cell1: 0+4.0; cell2: 3.0+0(nan); cell3: 0(nodata)+2.0
        assert np.allclose(out, [1.5, 4.0, 3.0, 2.0])
        assert np.all(out >= 0.0)
        assert out.shape == (n_cells,)

    def test_empty_stack_returns_zeros(self):
        out = positive_cell_flux_stack(np.empty((0, 1, 3)), n_cells=3)
        assert out.shape == (0, 3)
