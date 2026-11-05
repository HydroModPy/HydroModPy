"""The persistence helpers of the prepare-solver step."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.workflow.steps.data_description import (
    SCHEMA_VERSION,
    changed_sources,
    describe_loaded_data,
    description_path,
    iter_loaded_records,
    read_data_description,
    source_digests,
    write_data_description,
)
from hydromodpy.workflow.steps.prepare_solver import facts as facts_module
from hydromodpy.workflow.steps.prepare_solver import prepare as prepare_module
from hydromodpy.workflow.steps.prepare_solver.prepare import (
    step_persist_params,
    step_write_provenance,
)
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.run_stores import open_run_store
from tests.unit.workflow.steps._helpers import FakeLoadResult, FakeRecord
from tests.unit.workflow.steps.prepare_solver._helpers import square_and_pentagon

# --- test_the_run_records_its_inputs ---
# The provenance walk fills ``inputs.json``: provider, request, path, digest, licence.
#
# A loaded record of a known provider takes its licence from the registry of
# sources; a user file takes it from its sidecar. The path is written relative
# to the workspace, the digest is the one the load computed, and the entry
# reaches the seal through the facts of the run.


@dataclass
class _Loaded:
    hydrometry: object | None = None
    recharge: object | None = None


def _series_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=3, freq="D"), "value": [1.0, 2.0, 3.0]}
    )
    frame.to_csv(path, index=False)
    return path


def _record(path: Path, *, source: str, station: str, variable: str) -> PointRecord:
    frame = pd.read_csv(path, parse_dates=["datetime"])
    return PointRecord(
        station_id=station,
        variable=variable,
        source=source,
        unit="m3/s",
        frequency="D",
        data=frame,
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 3),
        file_path=path,
    )


def _ctx(sim_id: str, loaded: _Loaded, workspace_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        sim_id=sim_id,
        loaded_data=loaded,
        run_dir=None,
        setup=SimpleNamespace(workspace=SimpleNamespace(root=workspace_root)),
    )


def test_a_loaded_record_lands_in_the_inputs_with_its_provider_and_licence(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    csv = _series_file(workspace / "data" / "hydrometry" / "hubeau_J0014010.csv")
    custom = _series_file(workspace / "data" / "custom" / "recharge.csv")
    custom.with_name(custom.name + ".json").write_text(
        json.dumps({"source": "custom", "license": "CC-BY-4.0"}), encoding="utf-8"
    )
    loaded = _Loaded(
        hydrometry=LoadResult(
            points=[_record(csv, source="hubeau", station="J0014010", variable="discharge")]
        ),
        recharge=LoadResult(
            points=[_record(custom, source="custom", station="basin", variable="recharge")]
        ),
    )

    with open_run_store(workspace / "projects" / "demo", "run", n_cells=4) as store:
        step_write_provenance(_ctx(store.sim_id, loaded, workspace), store=store)
        inputs = {entry.provider: entry for entry in store.facts.inputs}

    assert set(inputs) == {"hubeau", "custom"}
    gauge = inputs["hubeau"]
    assert gauge.variable == "hydrometry:discharge"
    assert gauge.path == "data/hydrometry/hubeau_J0014010.csv"
    assert gauge.sha256 == hashlib.sha256(csv.read_bytes()).hexdigest()
    assert gauge.bytes == csv.stat().st_size
    assert gauge.license == "etalab-2.0"
    assert gauge.fetched_at is not None
    assert gauge.request["station"] == "J0014010"
    assert gauge.request["period"] == ["2020-01-01T00:00:00", "2020-01-03T00:00:00"]
    assert inputs["custom"].license == "CC-BY-4.0"
    assert inputs["custom"].path == "data/custom/recharge.csv"


def test_the_inputs_reach_the_seal(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    csv = _series_file(workspace / "data" / "hydrometry" / "hubeau_J0014010.csv")
    loaded = _Loaded(
        hydrometry=LoadResult(
            points=[_record(csv, source="hubeau", station="J0014010", variable="discharge")]
        )
    )
    store = open_run_store(workspace / "projects" / "demo", "run", n_cells=4)
    (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\n", encoding="utf-8")
    step_write_provenance(_ctx(store.sim_id, loaded, workspace), store=store)

    record = seal_completed(store)

    assert [entry.provider for entry in record.inputs] == ["hubeau"]
    assert RunRecord.read(store.run_dir).inputs == record.inputs


def test_a_record_written_twice_is_one_input(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    csv = _series_file(workspace / "data" / "hydrometry" / "hubeau_J0014010.csv")
    record = _record(csv, source="hubeau", station="J0014010", variable="discharge")
    loaded = _Loaded(hydrometry=LoadResult(points=[record]))

    with open_run_store(workspace / "projects" / "demo", "run", n_cells=4) as store:
        step_write_provenance(_ctx(store.sim_id, loaded, workspace), store=store)
        step_write_provenance(_ctx(store.sim_id, loaded, workspace), store=store)
        assert len(store.facts.inputs) == 1


def test_a_product_of_the_run_scratch_is_no_input(tmp_path: Path, monkeypatch) -> None:
    from hydromodpy.core.state.scratch import SCRATCH_ROOT_ENV

    workspace = tmp_path / "ws"
    project = workspace / "projects" / "demo"
    monkeypatch.setenv(SCRATCH_ROOT_ENV, str(tmp_path / "scratch"))
    csv = _series_file(workspace / "data" / "hydrometry" / "hubeau_J0014010.csv")
    product = _series_file(
        tmp_path / "scratch" / "demo" / "run.p1" / "_preprocessing" / "streams.csv"
    )
    loaded = _Loaded(
        hydrometry=LoadResult(
            points=[_record(csv, source="hubeau", station="J0014010", variable="discharge")]
        ),
        recharge=LoadResult(
            points=[_record(product, source="hydrography", station="basin", variable="streams")]
        ),
    )
    ctx = _ctx("", loaded, workspace)
    ctx.setup.workspace.project_root = project

    with open_run_store(project, "run", n_cells=4) as store:
        ctx.sim_id = store.sim_id
        step_write_provenance(ctx, store=store)
        providers = [entry.provider for entry in store.facts.inputs]

    assert providers == ["hubeau"]


def test_a_network_read_from_its_sources_names_them_with_their_provider(
    tmp_path: Path, monkeypatch
) -> None:
    import xarray as xr

    from hydromodpy.core.state.scratch import SCRATCH_ROOT_ENV
    from hydromodpy.data.contracts.spatial_field import INPUT_FILES_KEY, FieldRecord

    workspace = tmp_path / "ws"
    project = workspace / "projects" / "demo"
    monkeypatch.setenv(SCRATCH_ROOT_ENV, str(tmp_path / "scratch"))
    delivered = workspace / "data" / "hydrography" / "hydrography_bdtopage_5347fa22.gpkg"
    delivered.parent.mkdir(parents=True)
    delivered.write_bytes(b"the BD Topage answer")
    raster = tmp_path / "scratch" / "demo" / "run.p1" / "_preprocessing" / "streams.tif"
    raster.parent.mkdir(parents=True)
    raster.write_bytes(b"rasterised in the scratch")
    network = FieldRecord(
        variable="hydrographic_network_reference_raster",
        source="hydrography",
        unit="",
        data=xr.Dataset({"streams": (("y", "x"), [[1.0]])}),
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
        metadata={
            "raster_path": str(raster),
            INPUT_FILES_KEY: [{"provider": "bdtopage", "path": str(delivered)}],
        },
    )
    loaded = _Loaded(hydrometry=LoadResult(fields=[network]))
    ctx = _ctx("", loaded, workspace)
    ctx.setup.workspace.project_root = project

    with open_run_store(project, "run", n_cells=4) as store:
        ctx.sim_id = store.sim_id
        step_write_provenance(ctx, store=store)
        (entry,) = store.facts.inputs

    assert entry.provider == "bdtopage"
    assert entry.path == "data/hydrography/hydrography_bdtopage_5347fa22.gpkg"
    assert entry.sha256 == hashlib.sha256(b"the BD Topage answer").hexdigest()
    assert entry.license == "etalab-2.0"


# --- test_the_run_records_its_aquifer_thickness ---
# A run writes the aquifer thickness it solved into its parameters table.
#
# The thickness is calibrable, so a trial that moved it has to say which value
# it ran with. ``Domain`` keeps its depth model under ``config``; reading
# ``domain.depth_model`` found nothing and the row was never written.


class _Store:
    def __init__(self) -> None:
        self.written: list[dict] = []

    def write_parameters(self, sim_id: str, params: list[dict]) -> None:
        del sim_id
        self.written.extend(params)


def _persist(config: DomainConfig) -> list[dict]:
    store = _Store()
    step_persist_params(
        store,
        "sim",
        SimpleNamespace(parameters={}),
        domain=SimpleNamespace(config=config),
    )
    return store.written


def test_a_constant_thickness_reaches_the_parameters_table() -> None:
    rows = _persist(DomainConfig.with_thickness(30.0))

    assert rows == [
        {
            "param_name": "thickness",
            "zone_id": None,
            "value": 30.0,
            "unit": "m",
            "parameterization": "homogeneous",
        }
    ]


def test_a_flat_substratum_writes_no_thickness() -> None:
    config = DomainConfig.model_validate(
        {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 0.0}}
    )

    assert _persist(config) == []


# --- test_data_description ---
# The document ``load_data`` writes, read back and compared.
#
# Two properties matter beyond the round-trip. A source that is a file carries the
# digest of that file, so the document says which bytes the run consumed; and two
# documents of the same run can be compared to name the variables whose source
# moved, which is how a resume reports that it did not reload what it loaded.


@dataclasses.dataclass
class _DigestLoaded:
    recharge: object = None
    geology: object = None
    loaded_plan_types: tuple[str, ...] | None = None


def test_the_provenance_rows_reuse_the_digest_the_load_computed(tmp_path: Path) -> None:
    """Hashing a 500 MB DEM twice per run buys nothing, so it is read back.

    The document below carries a digest the file does not have. A row that
    shows it proves the second hash pass is gone; a row showing the real digest
    would mean the file was hashed again.
    """
    import pandas as pd

    from hydromodpy.workflow.steps.prepare_solver.prepare import step_write_provenance

    source = tmp_path / "recharge.csv"
    source.write_bytes(b"real bytes")
    record = FakeRecord(
        "recharge",
        "custom",
        metadata={"source_path": str(source)},
        station_id="EX04",
    )
    record.data = pd.DataFrame({"value": [1.0, 2.0]})
    loaded = _DigestLoaded(recharge=FakeLoadResult(points=(record,)))

    payload = describe_loaded_data(loaded)
    payload["records"][0]["source_sha256"] = "0" * 64
    write_data_description(tmp_path, "run_a", payload)

    rows: list[dict] = []
    inputs: list = []

    class _Store:
        def write_provenance(self, sim_id, **kwargs):
            rows.append(kwargs)

        def record_input(self, sim_id, entry):
            inputs.append(entry)

    class _Setup:
        run_id = "run_a"
        workspace = type("_W", (), {"project_root": tmp_path})()

    class _Ctx:
        sim_id = "sim"
        run_dir = tmp_path
        setup = _Setup()
        loaded_data = loaded

    step_write_provenance(_Ctx(), store=_Store())

    assert [row["source_sha256"] for row in rows] == ["0" * 64]
    assert rows[0]["variable"] == "recharge:recharge"
    assert [entry.sha256 for entry in inputs] == ["0" * 64], "the input carries the same digest"


# --- test_a_ragged_mesh_registers_and_persists ---
# A polygon mesh (a Voronoi dual) registers and persists like a triangle mesh.
#
# Its connectivity is a tuple of rows of different lengths: the registration hash
# and the Zarr writer both need the ``-1`` padded rectangular rows instead.

PADDED = np.array([[0, 1, 2, 3, -1], [1, 4, 5, 6, 2]])


def _mesh_ctx(cell_mesh: object, z_interfaces: tuple[float, ...] = (0.0, -10.0)) -> SimpleNamespace:
    return SimpleNamespace(
        config_path=None,
        cfg=SimpleNamespace(
            flow=SimpleNamespace(flow_regime="steady"),
            simulation=None,
            geographic=SimpleNamespace(crs_project="EPSG:2154"),
            site=None,
            model_dump=lambda mode="json": {},
        ),
        setup=SimpleNamespace(
            cell_mesh=cell_mesh,
            mesh_summary=None,
            time_grid=None,
            domain=SimpleNamespace(z_interfaces=np.array(z_interfaces)),
        ),
    )


def test_a_polygon_mesh_is_persisted_as_padded_rows(tmp_path: Path) -> None:
    cell_mesh = cell_mesh_of(square_and_pentagon())
    store = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=2, n_layers=1)
    writer = SimpleNamespace(
        write_mesh=lambda sim_id, **fields: store.write_mesh(**fields),
        write_view=lambda sim_id, view_name, records: None,
    )
    try:
        prepare_module.step_persist_mesh(_mesh_ctx(cell_mesh), "sim-1", store=writer)

        stored = np.asarray(store.root["mesh"]["face_node_connectivity"][:])
    finally:
        store.close()

    np.testing.assert_array_equal(stored, PADDED)
