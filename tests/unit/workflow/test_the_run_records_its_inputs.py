"""The provenance walk fills ``inputs.json``: provider, request, path, digest, licence.

A loaded record of a known provider takes its licence from the registry of
sources; a user file takes it from its sidecar. The path is written relative
to the workspace, the digest is the one the load computed, and the entry
reaches the seal through the facts of the run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.steps.prepare_solver.prepare import step_write_provenance
from tests._helpers.run_stores import open_run_store


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
    from hydromodpy.core.state.paths import SCRATCH_ROOT_ENV

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
