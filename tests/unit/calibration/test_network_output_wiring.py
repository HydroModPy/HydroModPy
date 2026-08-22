"""A network output, from the TOML declaration down to the scored pair.

The trial context is faked but everything it feeds is real: the mesh comes
from the V-valley bench, the mapped network is a geometry read off disk and
projected by the same helper the rest of the package uses, and the criterion is
the one a calibration runs.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibrationConfig, validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.solver_extract import (
    extract_outputs,
    observable_request_for_output,
)
from hydromodpy.calibration.observations.network_geometry import (
    build_network_geometry,
    reference_length,
    resolve_outlet,
)
from hydromodpy.core.contracts.observables import ObservableResult
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    cell_id,
    observed_network,
    simulated_network,
)

gpd = pytest.importorskip("geopandas")
shapely = pytest.importorskip("shapely")

CRS = "EPSG:2154"


@pytest.fixture(scope="module")
def bench():
    return build_bench()


@pytest.fixture(scope="module")
def stream_file(tmp_path_factory):
    """Write the valley axis as a mapped stream network."""
    from shapely.geometry import LineString

    line = LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(FIRST_OBSERVED_ROW, N_ROWS)
        ]
    )
    path = tmp_path_factory.mktemp("network") / "streams.gpkg"
    gpd.GeoDataFrame(geometry=[line], crs=CRS).to_file(path, driver="GPKG")
    return path


def _fake_run_ctx(bench, *, lake_cells=()):
    """A trial context exposing exactly what the criterion reads."""
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    planar_mesh = SimpleNamespace(
        vertices=vertices,
        flat_connectivity=connectivity,
        n_cells=N_CELLS,
    )
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        botm=np.zeros((1, N_CELLS)),
        inactive_mask=np.zeros((1, N_CELLS), dtype=bool),
        planar_mesh=planar_mesh,
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
    )
    model = SimpleNamespace(
        solver_mesh=solver_mesh,
        recharge=1.0e-8,
        lake_cell_ids_by_lake={"lac": list(lake_cells)} if lake_cells else {},
    )
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(
            execution=SimpleNamespace(models_by_run_id={"r1": model}),
            setup=SimpleNamespace(geographic=SimpleNamespace(crs_project=CRS)),
        ),
    )


class _Adapter:
    """Returns the bench pattern as a per-cell release flux."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self.seen: list = []

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store, time_index
        self.seen = list(requests)
        bench = build_bench()
        pattern = simulated_network(bench, self.threshold)
        return {
            request.id: ObservableResult(
                request_id=request.id,
                values=np.where(pattern, 1.0e-6, 0.0),
                units="m3 s-1",
            )
            for request in requests
        }


def _network_output(stream_file, **overrides):
    return validate_calib_output(
        {
            "support": "network",
            "stream_geometry_path": str(stream_file),
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            **overrides,
        }
    )


class TestSchema:
    def test_a_network_output_needs_no_observed_values(self, stream_file) -> None:
        out = _network_output(stream_file)
        # The criterion balances two simulated quantities, so the pair of zeros
        # is structural rather than something the user is asked for.
        assert out.observed_values == [0.0, 0.0]
        assert out.time == "last"

    def test_the_pair_must_hold_two_entries(self, stream_file) -> None:
        with pytest.raises(ValueError, match="must hold two entries"):
            _network_output(stream_file, observed_values=[0.0])

    def test_it_becomes_a_whole_field_request(self, stream_file) -> None:
        request = observable_request_for_output("net", _network_output(stream_file), None)
        assert (request.support, request.name, request.times) == ("cells", "release_flux", "last")

    def test_a_config_can_declare_the_gap_as_its_metric(self, stream_file) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {"net": _network_output(stream_file).model_dump()},
                "objective_blocks": [
                    {"name": "abherve", "metric": "distance_gap", "uses_outputs": ["net"]}
                ],
            }
        )
        assert cfg.objective_blocks[0].metric == "distance_gap"


class TestGeometry:
    def test_the_outlet_is_the_largest_drained_area(self, bench) -> None:
        assert resolve_outlet(bench.metric) == cell_id(N_ROWS - 1, AXIS_COL)

    def test_the_reference_length_is_the_median_cell_size(self) -> None:
        areas = np.array([100.0, 100.0, 10000.0])
        support = np.ones(3, dtype=bool)
        # The median, not the mean: one large buffer cell must not set the scale.
        assert reference_length(areas, support) == pytest.approx(10.0)

    def test_the_data_diagnostics_are_reported(self, bench) -> None:
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        geometry = build_network_geometry(
            topography=bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=1e-8,
            tau_specific_ratio=1e-4,
            diagonal_neighbors=True,
        )
        # A network sitting exactly on the talwegs has an alpha of one and
        # nothing unreachable: that is what says the surface was pre-treated.
        assert geometry.alpha_obs_closure == pytest.approx(1.0)
        assert geometry.frac_reachable_obs_raw == pytest.approx(1.0)
        assert geometry.diagnostics["n_outlet_sealed"] == 0.0
        assert geometry.length_scale_m == pytest.approx(CELL_SIZE)

    def test_a_declared_accuracy_raises_the_reference_length(self, bench) -> None:
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        geometry = build_network_geometry(
            topography=bench.elevation,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed_network("aligned"),
            cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
            mean_recharge_m_s=1e-8,
            tau_specific_ratio=1e-4,
            diagonal_neighbors=True,
            observed_position_accuracy_m=75.0,
        )
        # The error floor comes from the network's own precision, which a finer
        # mesh does not improve.
        assert geometry.length_scale_m == pytest.approx(75.0)

    def test_an_empty_projection_is_refused(self, bench) -> None:
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
        with pytest.raises(ValueError, match="projects onto no active cell"):
            build_network_geometry(
                topography=bench.elevation,
                face_node_connectivity=connectivity,
                vertices=vertices,
                observed=np.zeros(N_CELLS, dtype=bool),
                cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
                mean_recharge_m_s=1e-8,
                tau_specific_ratio=1e-4,
            )


class TestEndToEnd:
    def _extract(self, monkeypatch, bench, stream_file, threshold, **overrides):
        adapter = _Adapter(threshold)
        run_ctx = _fake_run_ctx(bench)
        monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))
        outputs = {"net": _network_output(stream_file, **overrides)}
        return extract_outputs(run_ctx, outputs)

    def test_the_output_produces_the_pair_and_its_diagnostics(
        self, monkeypatch, bench, stream_file
    ) -> None:
        simulated, diagnostics = self._extract(monkeypatch, bench, stream_file, 200.0)

        d_so, d_os = simulated["net"]
        assert np.isfinite(d_so) and np.isfinite(d_os)
        # The pair reproduces the residual the bracket reads, always.
        assert d_so - d_os == pytest.approx(diagnostics["net.J_signed"])
        assert diagnostics["net.J"] == pytest.approx(abs(d_so - d_os))

    def test_the_thirty_diagnostics_travel_with_it(self, monkeypatch, bench, stream_file) -> None:
        _, diagnostics = self._extract(monkeypatch, bench, stream_file, 200.0)
        for key in (
            "net.D_so",
            "net.D_os",
            "net.Doptim",
            "net.roptim",
            "net.n_valid",
            "net.n_excess",
            "net.n_missing",
            "net.frac_unreachable_so",
            "net.beta_sim_continuity",
            "net.zero_fraction_os",
            "net.alpha_obs_closure",
            "net.frac_reachable_obs_raw",
            "net.L_ref",
            "net.L_cap",
        ):
            assert key in diagnostics, key
            assert isinstance(diagnostics[key], float)

    def test_the_residual_changes_sign_across_the_sweep(
        self, monkeypatch, bench, stream_file
    ) -> None:
        low = self._extract(monkeypatch, bench, stream_file, 20.0)[1]["net.J_signed"]
        high = self._extract(monkeypatch, bench, stream_file, 900.0)[1]["net.J_signed"]
        assert low > 0.0 > high

    def test_a_violation_of_the_validity_bound_can_be_made_fatal(
        self, monkeypatch, bench, stream_file
    ) -> None:
        with pytest.raises(ValueError, match="exceeds the validity bound"):
            self._extract(
                monkeypatch,
                bench,
                stream_file,
                200.0,
                roptim_max=1e-6,
                on_roptim_violation="error",
            )

    def test_a_violation_only_warns_by_default(
        self, monkeypatch, bench, stream_file, caplog
    ) -> None:
        # A calibration is asked for a number: a coarse agreement qualifies the
        # result, it does not withhold it.
        simulated, _ = self._extract(monkeypatch, bench, stream_file, 200.0, roptim_max=1e-6)
        assert np.isfinite(simulated["net"][0])
        assert "validity bound" in caplog.text
