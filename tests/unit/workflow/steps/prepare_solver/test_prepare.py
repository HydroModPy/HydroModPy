"""Provenance of the inputs and the parameters table written by the prepare-solver step.

A record of a known provider takes its licence from the registry of sources, a user file from
its sidecar. Paths are relative to the workspace. Thickness (m) is calibrable, so a run writes
the value it solved. Provenance rows reuse the digests of the data description.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import xarray as xr

from hydromodpy.core.state.scratch import SCRATCH_ROOT_ENV
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import INPUT_FILES_KEY, FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.results.record.record import RunRecord
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.steps.data_description import (
    describe_loaded_data,
    write_data_description,
)
from hydromodpy.workflow.steps.prepare_solver.prepare import (
    step_persist_params,
    step_write_provenance,
)
from tests._helpers.run_stores import open_run_store
from tests.unit.workflow.steps._helpers import FakeLoadResult, FakeRecord


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


def test_inputs_reach_the_seal(tmp_path: Path) -> None:
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


def test_record_written_twice_is_one_input(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    csv = _series_file(workspace / "data" / "hydrometry" / "hubeau_J0014010.csv")
    record = _record(csv, source="hubeau", station="J0014010", variable="discharge")
    loaded = _Loaded(hydrometry=LoadResult(points=[record]))

    with open_run_store(workspace / "projects" / "demo", "run", n_cells=4) as store:
        step_write_provenance(_ctx(store.sim_id, loaded, workspace), store=store)
        step_write_provenance(_ctx(store.sim_id, loaded, workspace), store=store)
        assert len(store.facts.inputs) == 1


def test_scratch_product_is_no_input(tmp_path: Path, monkeypatch) -> None:
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


def test_network_names_its_sources(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    project = workspace / "projects" / "demo"
    monkeypatch.setenv(SCRATCH_ROOT_ENV, str(tmp_path / "scratch"))
    delivered = workspace / "data" / "hydrography" / "hydrography_bdtopage_5347fa22.gpkg"
    delivered.parent.mkdir(parents=True)
    delivered.write_bytes(b"the BD Topage answer")
    delivered.with_name(delivered.name + ".json").write_text(
        json.dumps({"source": "bdtopage", "license": "etalab-2.0"}), encoding="utf-8"
    )
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
        {},
        domain=SimpleNamespace(config=config),
    )
    return store.written


def test_profiles_reach_parameters_table() -> None:
    profiles = {
        "K": SimpleNamespace(kind="homogeneous", value=5e-6, unit="m/s"),
        "Sy": SimpleNamespace(kind="geology", values_by_key={1: 0.1, 2: 0.2}, unit="-"),
    }

    store = _Store()
    step_persist_params(store, "sim", profiles)

    assert store.written == [
        {
            "param_name": "K",
            "zone_id": None,
            "value": 5e-6,
            "unit": "m/s",
            "parameterization": "homogeneous",
        },
        {
            "param_name": "Sy",
            "zone_id": "1",
            "value": 0.1,
            "unit": "-",
            "parameterization": "geology_mapped",
        },
        {
            "param_name": "Sy",
            "zone_id": "2",
            "value": 0.2,
            "unit": "-",
            "parameterization": "geology_mapped",
        },
    ]


def test_constant_thickness_row() -> None:
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


def test_flat_substratum_no_thickness_row() -> None:
    config = DomainConfig.model_validate(
        {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 0.0}}
    )

    assert _persist(config) == []


@dataclasses.dataclass
class _DigestLoaded:
    recharge: object = None
    geology: object = None
    loaded_plan_types: tuple[str, ...] | None = None


def test_provenance_reuses_the_load_digest(tmp_path: Path) -> None:
    # Hashing a 500 MB DEM twice per run buys nothing. The description carries a digest the file
    # does not have: a row that shows it proves the second hash pass is gone.
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
