"""A run and a session of 2.0.0 read back, by the public path, with the values they hold.

``v2.0.0/current`` is a workspace as 2.0.0 stored it: the demo, one calibration of its K,
and the run that calibration promoted. ``v2.0.0/future`` is the same as a later 2.x could
have written it, with an extra key in the JSON documents, an extra column in the Parquet
tables and an extra array in the Zarr stores. Both read the same values, because every
later 2.x reads every 2.0.0 document, and every 2.0.0 reads what a later 2.x added.

No test writes under ``v2.0.0/``, and none regenerates it. ``expected.json`` holds what the
raw files say, read by ``zarr``, ``pyarrow`` and ``json`` when the tree was generated, so a
reader that changes a number, a sign, a unit or an order fails here. The Zarr golden of
``tests/regression/zarr`` detects a change of what the code writes, this file guards what
the code reads. See ``README.md`` beside it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import zarr

import hydromodpy as hmp
from hydromodpy.results.annotations import read_annotations
from hydromodpy.results.export.publish import publish, verify
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.outcome import read_outcome, write_outcome
from hydromodpy.results.session.descriptor import read_session, write_session
from hydromodpy.results.session.journal import append_trial, read_trials
from hydromodpy.results.session.phase import read_phase, write_phase
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.cli_runner import CliRunner
from tests._helpers.demo_mound import AREA_M2, RECHARGE_M_S, dupuit_mound_m
from tests._helpers.tolerances import tol

FROZEN = Path(__file__).parent / "v2.0.0"
EXPECTED: dict[str, Any] = json.loads((FROZEN / "expected.json").read_text(encoding="utf-8"))
PROJECT = Path("projects") / "example"
COPIES = ("current", "future")
FUTURE_KEY = "from_a_later_version"
"""Name of the extra key, column and array of the future copy."""

FUTURE_FILL = 7.0
"""The value of the extra array of the future copy."""

SIZE_LIMIT_BYTES = 700_000
"""One copy stays a few hundred kB: the demo, the promoted run and the session."""

RUNS = {
    "demo": ("demo", "exploratory"),
    "calage": ("calibrated_run", "calibrated"),
}
"""Run directory: its key in ``expected.json`` and the label of the rules it was sealed under."""

BUDGET_CLOSURE = tol("global_water_budget_closure")
MOUND_RTOL = tol("scaffolded_demo__mound_against_the_dupuit_integral")


def _copy_of(copy: str, parent: Path) -> Path:
    """Copy a frozen tree outside the repository and return its project."""
    shutil.copytree(FROZEN / copy, parent / copy)
    return parent / copy / PROJECT


@pytest.fixture(scope="module", params=COPIES)
def project(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One copy of the tree, shared by the tests that only read."""
    return _copy_of(request.param, tmp_path_factory.mktemp("frozen"))


@pytest.fixture
def future(tmp_path: Path) -> Path:
    """A future copy of its own, for a test that rewrites."""
    return _copy_of("future", tmp_path)


def _tree_digest(tree: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in tree.rglob("*") if item.is_file()):
        digest.update(path.relative_to(tree).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _rows(frame: pd.DataFrame, *columns: str) -> list[dict[str, Any]]:
    rows = frame.reset_index()[list(columns)].to_dict("records")
    return sorted(rows, key=lambda row: [str(row[name]) for name in columns])


def _assert_field(values: Any, expected: dict[str, Any]) -> None:
    """Compare a field with what the raw store held, whatever the dimensions it comes with."""
    flat = np.asarray(values, dtype="float64").ravel()
    assert flat.size == np.prod(expected["shape"])
    assert (float(flat.min()), float(flat.max())) == (expected["min"], expected["max"])
    assert flat[:: max(1, flat.size // 19)].tolist() == expected["sample"]
    assert hashlib.sha256(flat.astype("<f8").tobytes()).hexdigest() == expected["sha256"]


def _document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- the frozen tree


@pytest.mark.parametrize("copy", COPIES)
def test_the_frozen_bytes_have_not_moved(copy: str) -> None:
    """A test that writes in the tree, or a regeneration without its values, fails here."""
    assert _tree_digest(FROZEN / copy) == EXPECTED["digests"][copy]


@pytest.mark.parametrize("copy", COPIES)
def test_a_copy_stays_small(copy: str) -> None:
    size = sum(path.stat().st_size for path in (FROZEN / copy).rglob("*") if path.is_file())
    assert size < SIZE_LIMIT_BYTES


def test_the_frozen_tree_names_no_machine() -> None:
    for path in FROZEN.rglob("*"):
        if path.suffix in {".json", ".jsonl", ".toml", ".md", ".csv"}:
            assert "/home/" not in path.read_text(encoding="utf-8"), path
    provenance = _document(FROZEN / "current" / PROJECT / "runs" / "demo" / "provenance.json")
    assert (provenance["platform"]["hostname"], provenance["platform"]["user"]) == (
        "frozen",
        "frozen",
    )


def test_the_future_copy_holds_what_it_says_it_adds() -> None:
    """Without this, a generator that adds nothing would make every test below pass."""
    project = FROZEN / "future" / PROJECT
    manifest = _document(project / "runs" / "demo" / "manifest.json")
    assert FUTURE_KEY in manifest
    assert FUTURE_KEY in manifest["identity"]
    assert FUTURE_KEY in manifest["parameters"][0]
    assert FUTURE_KEY in _document(project / "sessions" / "calage" / "session.json")["best"]
    tables = project / "runs" / "demo" / "tables.parquet"
    assert all(FUTURE_KEY in pq.read_schema(path).names for path in tables.glob("*.parquet"))
    root = zarr.open_group(str(project / "runs" / "demo" / "fields.zarr"), mode="r")
    assert FUTURE_KEY in root
    assert FUTURE_KEY in root["budget"]


# ------------------------------------------------------------------------------ reading


@pytest.mark.parametrize("name", RUNS)
def test_a_run_reads_back_with_its_values(project: Path, name: str) -> None:
    key, label = RUNS[name]
    expected = EXPECTED[key]
    run = hmp.open(project / "runs" / name)

    assert isinstance(run, hmp.Run)
    assert (run.sim_id, run.name, run.project) == (
        expected["sim_id"],
        expected["name"],
        expected["project"],
    )
    assert (run.solver, run.flow_regime, run.status) == (
        expected["solver"],
        expected["flow_regime"],
        expected["status"],
    )
    assert (run.n_cells, run.n_layers, run.n_timesteps) == (
        expected["n_cells"],
        expected["n_layers"],
        expected["n_timesteps"],
    )
    assert run.params == expected["parameters"]
    assert run.label().label == label
    assert run.checks.budget_pct == expected["budget_pct"]
    assert run.inputs == []
    assert run.tags == (expected["tags"] or None)
    assert [note.text for note in read_annotations(run.dir).notes] == expected["notes"]
    assert all(run.has_table(table) for table in expected["tables"])
    assert sorted(run.record.budget.kept_terms) == expected["budget_terms"]
    assert run.record.period.time_unit == expected["period"]["time_unit"]
    assert run.record.period.n_timesteps == expected["period"]["n_timesteps"]
    assert [path.name for path in run.exports] == expected["exports"]
    assert [path.name for path in run.figures] == expected["figures"]
    assert all(path.is_file() for path in [*run.exports, *run.figures])
    assert run.time_index.equals(pd.to_datetime(expected["time"], unit="s"))

    lineage = run.record.lineage
    assert lineage.session_id == expected["lineage"]["session_id"]
    assert lineage.kind == expected["lineage"]["kind"]

    _assert_field(run.field("head"), expected["head"])
    _assert_field(hmp.read(run, "head", time=0), expected["head"])
    _assert_field(hmp.read(run, "head").values, expected["head"])
    _assert_field(run.mesh.topography, expected["topography"])

    assert _rows(run.budget(), "component", "flux_in", "flux_out", "unit") == expected["budget"]
    assert (
        _rows(run.mass_balance, "quantity", "total_in", "total_out", "percent_error")
        == expected["mass_balance"]
    )
    assert _rows(run.parameters, "param_name", "value", "unit") == expected["parameters_table"]
    series = expected["timeseries"][0]
    assert run.stations("discharge") == [series["station_id"]]
    assert hmp.read(run, "discharge").tolist() == [series["value"]]
    assert hmp.read(run, "watershed").area.sum() == expected["watershed_area_m2"]


def test_the_record_and_the_identity_of_a_run_read_back(project: Path) -> None:
    run_dir = project / "runs" / "demo"
    run = hmp.open(run_dir)
    sim_id = EXPECTED["demo"]["sim_id"]

    assert run.record.provenance.solver["name"] == EXPECTED["demo"]["solver"]
    assert run.record.provenance.sim_id == sim_id
    for path in (
        run_dir / "exports" / "discharge.csv",
        run_dir / "fields.zarr",
        run_dir / "tables.parquet" / "budgets.parquet",
    ):
        assert read_identity_from(path).sim_id == sim_id


def test_the_metrics_of_a_run_read_back(project: Path) -> None:
    rows = [
        {
            "station_id": row.station,
            "variable": row.variable,
            "metric": row.metric,
            "value": row.value,
        }
        for row in hmp.open(project / "runs" / "demo").record.metrics
    ]
    assert sorted(rows, key=lambda row: row["metric"]) == EXPECTED["demo"]["metrics"]


def test_the_frozen_demo_holds_the_physics_of_the_demo(project: Path) -> None:
    """Literals on purpose: a regeneration cannot move what the demo means."""
    run = hmp.open(project / "runs" / "demo")
    budget = run.budget().set_index("component")
    recharge = budget.loc["recharge", "flux_in"]
    assert recharge == pytest.approx(RECHARGE_M_S * AREA_M2, rel=BUDGET_CLOSURE)
    assert abs(recharge - budget.loc["drain", "flux_out"]) / recharge < BUDGET_CLOSURE

    head = run.field("head")[0].reshape(20, 20)
    assert run.params["K"] == 1.0e-4
    assert head[:, 0].mean() - head[:, -1].mean() == pytest.approx(
        dupuit_mound_m(1.0e-4), rel=MOUND_RTOL
    )


def test_the_config_a_run_sealed_reads_back(project: Path) -> None:
    run = hmp.open(project / "runs" / "demo")
    assert run.config_snapshot["flow"]["sinks_sources"]["recharge"]["values"] == 0.8
    assert run.hydromodpy_config.flow.active_sinks_sources == ["recharge"]


def test_a_session_reads_back_with_its_values(project: Path) -> None:
    expected = EXPECTED["session"]
    session = hmp.open(project / "sessions" / "calage")

    assert isinstance(session, Session)
    assert session.status == expected["status"]
    assert session.cases == (expected["case_id"],)
    assert session.descriptor.session_id == expected["session_id"]
    assert session.descriptor.method == expected["method"]
    assert session.descriptor.stop_state == expected["stop_state"]
    assert session.descriptor.cost_name == expected["cost_name"]
    assert session.descriptor.bounds["K"].lower == expected["bounds"]["K"]["lower"]
    assert session.descriptor.bounds["K"].upper == expected["bounds"]["K"]["upper"]
    assert session.windows == expected["windows"]
    assert session.best_cost == expected["best"]["cost"]
    assert session.best_parameters == expected["best"]["parameters"]
    assert [phase.name for phase in session.phases] == expected["phases"]
    assert session.config["calibration"]["parameters"]["K"]["bounds"] == [5.0e-5, 2.0e-4]

    trials = session.trials
    assert trials["trial"].tolist() == [row["trial"] for row in expected["trials"]]
    assert trials["cost"].tolist() == [row["cost"] for row in expected["trials"]]
    assert trials["phase"].tolist() == [row["phase"] for row in expected["trials"]]
    assert trials["sim_id"].tolist() == [row["sim_id"] for row in expected["trials"]]
    assert [row["K"]["value"] for row in trials["parameters"]] == [
        row["K"] for row in expected["trials"]
    ]

    best_run = expected["best"]["cases"]["calage"]
    assert session.best is not None
    assert session.best.sim_id == best_run["sim_id"]
    assert session.best.dir == project / best_run["rel_dir"]
    assert session.best_by_case["calage"].sim_id == best_run["sim_id"]


def test_the_frozen_search_ranks_k_by_the_mound(project: Path) -> None:
    """The observed head is the head of the demo: the search lands on its K, and K moves the head."""
    session = hmp.open(project / "sessions" / "calage")
    assert session.best_parameters == {"K": 1.0e-4}
    too_low, truth, too_high = session.trials["cost"]
    assert truth == session.best_cost
    assert too_low > too_high > truth


def test_a_project_lists_its_runs_and_its_session(project: Path) -> None:
    opened = hmp.open(project)
    cases = opened.cases.set_index("rel_dir")
    assert sorted(cases.index) == ["runs/calage", "runs/demo", "sessions/calage"]
    assert set(cases["status"]) == {"completed"}
    assert sorted(run.name for run in opened.runs()) == ["calage", "demo"]
    assert list(opened.sessions) == ["calage"]
    assert opened.sessions["calage"].best_cost == EXPECTED["session"]["best"]["cost"]
    assert opened["demo"].sim_id == EXPECTED["demo"]["sim_id"]

    across = hmp.index(project.parents[1]).runs()
    assert sorted(across["name"]) == ["calage", "demo"]
    assert set(across["n_cells"]) == {EXPECTED["demo"]["n_cells"]}


def test_the_index_rebuilt_from_the_directories_holds_the_same_values(project: Path) -> None:
    done = CliRunner().invoke(["catalog", "reindex", "-w", str(project)])
    assert done.exit_code == 0, done.stderr

    expected = EXPECTED["demo"]
    with hmp.Catalog(project) as catalog:
        simulations = catalog.list_simulations().set_index("name")
        assert sorted(simulations.index) == ["calage", "demo"]
        assert str(simulations.loc["demo", "sim_id"]) == expected["sim_id"]
        assert str(simulations.loc["calage", "sim_id"]) == EXPECTED["calibrated_run"]["sim_id"]
        budget = catalog.query_budget(expected["sim_id"])
        assert _rows(budget, "component", "flux_in", "flux_out", "unit") == expected["budget"]
        mass_balance = catalog.query_mass_balance(expected["sim_id"])
        assert mass_balance["total_in"].tolist() == [expected["mass_balance"][0]["total_in"]]
        assert catalog.calibration_sessions["session_id"].tolist() == [
            EXPECTED["session"]["session_id"]
        ]
        iterations = catalog.calibration_iterations(EXPECTED["session"]["session_id"])
        assert iterations["trial"].tolist() == [
            row["trial"] for row in EXPECTED["session"]["trials"]
        ]
        assert iterations["cost"].tolist() == [row["cost"] for row in EXPECTED["session"]["trials"]]


# ------------------------------------------------------------- what a later 2.x added


def test_a_field_of_a_later_version_stays_out_of_the_list_and_reads_by_name(project: Path) -> None:
    """``list_fields`` holds the names this version knows, ``field`` reads what is stored."""
    run = hmp.open(project / "runs" / "demo")
    assert FUTURE_KEY not in run.array.list_fields()
    assert "head" in run.array.list_fields()
    is_future = project.parents[1].name == "future"
    assert run.has_field(FUTURE_KEY) is is_future
    if is_future:
        assert np.all(run.field(FUTURE_KEY, time=0) == FUTURE_FILL)


def test_an_annotation_keeps_the_key_of_a_later_version(future: Path) -> None:
    run = hmp.open(future / "runs" / "demo")

    run.tag("kept")
    run.note("Written on a tree a later version wrote.")

    written = _document(future / "runs" / "demo" / "annotations.json")
    assert written["tags"] == ["frozen", "kept"]
    assert len(written["notes"]) == 2
    assert FUTURE_KEY in written
    assert read_annotations(future / "runs" / "demo").tags == ("frozen", "kept")


def test_an_export_keeps_the_keys_of_the_ledger_of_a_later_version(future: Path) -> None:
    run = hmp.open(future / "runs" / "demo")

    written = run.export("budget")

    ledger = _document(future / "runs" / "demo" / "exports" / "index.json")
    assert FUTURE_KEY in ledger
    entries = {entry["file"]: entry for entry in ledger["entries"]}
    assert FUTURE_KEY in entries["discharge.csv"]
    assert FUTURE_KEY in entries["discharge.csv"]["identity"]
    assert {path.name for path in written} <= set(entries)
    assert (future / "runs" / "demo" / "exports" / "discharge.csv").is_file()


@pytest.mark.parametrize(
    "where",
    [
        lambda doc: doc,
        lambda doc: doc["cases"]["calage"],
        lambda doc: doc["bounds"]["K"],
        lambda doc: doc["best"],
        lambda doc: doc["best"]["cases"]["calage"],
    ],
    ids=["root", "case", "bound", "best", "best_case"],
)
def test_a_session_written_again_keeps_the_keys_of_a_later_version(future: Path, where) -> None:
    directory = future / "sessions" / "calage"
    before = _document(directory / "session.json")

    write_session(directory, read_session(directory))

    after = _document(directory / "session.json")
    assert FUTURE_KEY in where(after)
    assert after == before


def test_the_other_session_documents_keep_the_keys_of_a_later_version(future: Path) -> None:
    directory = future / "sessions" / "calage"

    before = _document(directory / "phases" / "k_grid" / "session.json")
    write_phase(directory, read_phase(directory, "k_grid"))
    assert _document(directory / "phases" / "k_grid" / "session.json") == before

    before = _document(directory / "outcome.json")
    write_outcome(directory, read_outcome(directory))
    assert _document(directory / "outcome.json") == before

    trials = read_trials(directory)
    append_trial(directory, trials[-1])
    last = json.loads((directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert FUTURE_KEY in last
    assert FUTURE_KEY in last["params"]["K"]
    assert FUTURE_KEY in last["cases"]["calage"]


def test_a_table_written_again_keeps_the_column_of_a_later_version(future: Path) -> None:
    run_dir = future / "runs" / "demo"
    store = RunStore.open(run_dir)
    target = run_dir / "tables.parquet" / "budgets.parquet"
    stored = pq.read_table(target).to_pylist()

    store.write_budget(store.sim_id, 1, "domain", "recharge", 1.0, 0.0)

    rows = pq.read_table(target).to_pylist()
    assert len(rows) == len(stored) + 1
    assert {row["component"]: row[FUTURE_KEY] for row in rows if row["timestep"] == 0} == {
        row["component"]: row[FUTURE_KEY] for row in stored
    }
    assert [row[FUTURE_KEY] for row in rows if row["timestep"] == 1] == [None]


def test_a_field_written_again_leaves_the_array_of_a_later_version(future: Path) -> None:
    run_dir = future / "runs" / "demo"
    store = RunStore.open(run_dir)
    run = hmp.open(run_dir)
    head = run.field("head")

    store.write_field(store.sim_id, "head", 0, head)

    root = zarr.open_group(str(run_dir / "fields.zarr"), mode="r", use_consolidated=False)
    assert np.all(root[FUTURE_KEY][...] == FUTURE_FILL)
    assert np.all(root["budget"][FUTURE_KEY][...] == FUTURE_FILL)
    assert FUTURE_KEY in root.attrs
    _assert_field(hmp.open(run_dir).field("head"), EXPECTED["demo"]["head"])


def test_a_published_copy_keeps_what_a_later_version_added(future: Path, tmp_path: Path) -> None:
    run_dir = future / "runs" / "demo"

    copy = publish(run_dir, tmp_path / "published", project_root=future, with_=("results",))

    assert verify(copy) == []
    assert FUTURE_KEY in _document(copy / "manifest.json")
    assert FUTURE_KEY in pq.read_schema(copy / "tables.parquet" / "budgets.parquet").names
    assert FUTURE_KEY in zarr.open_group(str(copy / "fields.zarr"), mode="r")
