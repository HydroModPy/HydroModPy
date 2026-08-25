"""A network output, from the TOML declaration down to the scored pair.

The trial context is faked but everything it feeds is real: the mesh comes
from the V-valley bench, the mapped network is a geometry read off disk and
projected by the same helper the rest of the package uses, and the criterion is
the one a calibration runs.
"""

from __future__ import annotations

import tomllib
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibOutputNetwork,
    CalibrationConfig,
    validate_calib_output,
)
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.downslope_network import SeepageDistanceResult
from hydromodpy.calibration.metrics.solver_extract import (
    extract_outputs,
    observable_request_for_output,
)
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.core.stream_geometry import (
    build_network_geometry,
    reference_length,
    resolve_outlet,
)
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
    rows, cols = np.divmod(np.arange(N_CELLS), N_COLS)
    centroids = np.column_stack([(cols + 0.5) * CELL_SIZE, (rows + 0.5) * CELL_SIZE])
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        botm=np.zeros((1, N_CELLS)),
        inactive_mask=np.zeros((1, N_CELLS), dtype=bool),
        planar_mesh=planar_mesh,
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        # The points the top was sampled at, which the criterion routes on.
        cell_centroids=lambda: centroids,
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

    def __init__(self, threshold: float, units: str = "m3 s-1") -> None:
        self.threshold = threshold
        self.units = units
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
                units=self.units,
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

    def test_it_declares_no_reducer_at_all(self, stream_file) -> None:
        # Nothing ever read it: extract_outputs branches on support == "network"
        # before slice_time, the only reader of a reducer.
        assert "reducer" not in CalibOutputNetwork.model_fields
        with pytest.raises(ValidationError, match="reducer"):
            _network_output(stream_file, reducer="sum")

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


def _extract(monkeypatch, bench, stream_file, threshold, units="m3 s-1", **overrides):
    """Drive one output through the real extraction, with a faked adapter."""
    adapter = _Adapter(threshold, units=units)
    run_ctx = _fake_run_ctx(bench)
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))
    outputs = {"net": _network_output(stream_file, **overrides)}
    return extract_outputs(run_ctx, outputs)


class TestEndToEnd:
    def _extract(self, monkeypatch, bench, stream_file, threshold, **overrides):
        return _extract(monkeypatch, bench, stream_file, threshold, **overrides)

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
        with pytest.raises(ObjectiveError, match="exceeds the validity bound"):
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


class TestTheRefusalOfAnUnreachableSupport:
    """The refusal has to name the quantity that was compared to the bound.

    The guard was narrowed to ``D_so`` alone; a message still naming both, and
    still offering a retracted simulated network as a cause, sends the reader
    after something the guard cannot have seen.
    """

    def _fail(self, monkeypatch, bench, stream_file):
        failed = SeepageDistanceResult(
            signed_gap=float("nan"),
            status="failed",
            components={
                "frac_unreachable_so": 0.42,
                "frac_unreachable_os": 0.11,
                "D_os": 0.0,
                "roptim": 0.0,
            },
        )
        monkeypatch.setattr(_solver_extract, "seepage_distance_cost", lambda **kwargs: failed)
        with pytest.raises(ObjectiveError) as excinfo:
            _extract(monkeypatch, bench, stream_file, 200.0)
        return str(excinfo.value)

    def test_it_reports_the_share_that_was_bounded(self, monkeypatch, bench, stream_file) -> None:
        message = self._fail(monkeypatch, bench, stream_file)
        assert "frac_unreachable_so" in message
        assert "42.0%" in message
        assert "5%" in message

    def test_it_names_the_other_share_as_an_unbounded_diagnostic(
        self, monkeypatch, bench, stream_file
    ) -> None:
        message = self._fail(monkeypatch, bench, stream_file)
        head, _, tail = message.partition("frac_unreachable_os")
        assert tail, "the reciprocal share is not named at all"
        assert "not bounded" in tail
        # The cause the narrowed guard cannot have detected must be gone: the
        # target of D_so is fixed for the whole search.
        assert "too small" not in head + tail


class TestTheUnitTheReleaseFieldArrivesIn:
    """The seepage threshold is a recharge in m/s times a cell area.

    It is therefore a volumetric flow in m3/s, and the field it is compared to
    has to be one too. The same array is fed in under four unit strings here,
    so what separates the cases is the declared unit alone.
    """

    def _extract(self, monkeypatch, bench, stream_file, units):
        return _extract(monkeypatch, bench, stream_file, 200.0, units=units)

    @pytest.mark.parametrize("units", ["m3 s-1", "m3/s", "m3.s-1"])
    def test_the_spellings_the_adapters_write_are_accepted(
        self, monkeypatch, bench, stream_file, units
    ) -> None:
        # modflow_common and boussinesq write the CF form, the GR4J extractor
        # the solidus one. Both name the same unit.
        simulated, _ = self._extract(monkeypatch, bench, stream_file, units)
        assert np.isfinite(simulated["net"][0])

    @pytest.mark.parametrize("units", ["L/s", "m3/day"])
    def test_a_flow_in_another_unit_is_refused_by_name(
        self, monkeypatch, bench, stream_file, units
    ) -> None:
        # Dimensionally a flow, numerically off by a constant factor: the
        # simulated network would follow the unit and not the hydrogeology.
        with pytest.raises(ObjectiveError) as excinfo:
            self._extract(monkeypatch, bench, stream_file, units)
        message = str(excinfo.value)
        assert "'net'" in message
        assert repr(units) in message
        assert "m3/s" in message

    @pytest.mark.parametrize("units", ["m", ""])
    def test_a_field_that_is_no_flow_at_all_is_refused_by_name(
        self, monkeypatch, bench, stream_file, units
    ) -> None:
        # 'm' is a head served by mistake; '' is what the GR4J adapter used to
        # declare for every series it produced.
        with pytest.raises(ObjectiveError) as excinfo:
            self._extract(monkeypatch, bench, stream_file, units)
        assert "'net'" in str(excinfo.value)
        assert repr(units) in str(excinfo.value)


class TestTheGuardOnAnUnpairedNetworkOutput:
    """A declared network output that nothing scores is a silent wrong answer.

    The single-metric route reads neither ``stream_geometry_path`` nor the
    thresholds, so a configuration slipping through it reports a head/NSE
    number while the user believes the stream network was calibrated on.
    """

    def _config(self, stream_file, **overrides):
        return CalibrationConfig.model_validate(
            {
                "method": "grid",
                "outputs": {"net": _network_output(stream_file).model_dump()},
                **overrides,
            }
        )

    def test_a_network_output_with_no_block_at_all_is_refused(self, stream_file) -> None:
        with pytest.raises(ValueError, match="distance_gap"):
            self._config(stream_file)

    def test_the_message_names_the_output(self, stream_file) -> None:
        with pytest.raises(ValueError, match="'net'"):
            self._config(stream_file)

    def test_a_head_block_does_not_pair_it(self, stream_file) -> None:
        with pytest.raises(ValueError, match="distance_mean"):
            self._config(
                stream_file,
                outputs={
                    "net": _network_output(stream_file).model_dump(),
                    "piezo": {"support": "point", "x": 0.0, "y": 0.0, "variable": "head"},
                },
                objective_blocks=[{"name": "heads", "metric": "rmse", "uses_outputs": ["piezo"]}],
            )

    def test_a_distance_block_pairs_it(self, stream_file) -> None:
        cfg = self._config(
            stream_file,
            objective_blocks=[{"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]}],
        )
        assert cfg.objective_blocks[0].metric == "distance_gap"

    def test_the_implicit_block_pairs_it_too(self, stream_file) -> None:
        # (objective, variable) builds the block the composite route needs, so
        # the guard must read the config after that block exists.
        cfg = self._config(stream_file, objective="distance_gap", variable="net")
        assert [block.metric for block in cfg.objective_blocks] == ["distance_gap"]

    def test_a_config_with_no_network_output_is_left_alone(self) -> None:
        # A single-metric phase sub-configuration has zero outputs and zero
        # blocks; there is nothing to guard there.
        cfg = CalibrationConfig.model_validate(
            {"method": "grid", "variable": "discharge", "objective": "nse_log"}
        )
        assert cfg.objective_blocks == []


class TestTheMappedNetworkIsRequired:
    def test_a_network_output_without_a_geometry_is_refused(self) -> None:
        # observations/observed_network.py has no fallback: it raises.
        with pytest.raises(ValueError, match="stream_geometry_path"):
            validate_calib_output({"support": "network"})


class TestADeletedFieldIsRefusedInATomlToo:
    """``extra="forbid"`` has to make the deletion visible where users write.

    A field silently accepted and then ignored is worse than one that never
    existed: the run answers, and the answer does not depend on what was
    declared.
    """

    def _config_from_toml(self, stream_file, extra_line: str) -> CalibrationConfig:
        payload = tomllib.loads(
            "method = 'grid'\n"
            "[outputs.net]\n"
            "support = 'network'\n"
            f"stream_geometry_path = {str(stream_file)!r}\n"
            f"{extra_line}\n"
            "[[objective_blocks]]\n"
            "name = 'abherve'\n"
            "metric = 'distance_gap'\n"
            "uses_outputs = ['net']\n"
        )
        return CalibrationConfig.model_validate(payload)

    def test_a_toml_declaring_a_reducer_is_refused(self, stream_file) -> None:
        with pytest.raises(ValidationError, match="reducer"):
            self._config_from_toml(stream_file, "reducer = 'sum'")

    def test_the_same_toml_without_it_is_accepted(self, stream_file) -> None:
        # The control: only the deleted key separates the two cases.
        cfg = self._config_from_toml(stream_file, "weighting = 'cell'")
        assert cfg.outputs["net"].support == "network"
