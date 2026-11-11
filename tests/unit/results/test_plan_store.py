"""A plan is written once under its hash, pointed at by plan/current, and never rewritten in place."""

from __future__ import annotations

import json
import os
import tomllib
from datetime import UTC, datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.state.layout import PLAN_DIRNAME
from hydromodpy.results import plan_store
from hydromodpy.results.plan_store import (
    CASE_COLUMNS,
    PLAN_SCHEMA,
    Plan,
    PlanCase,
    PlanConflictError,
    current_plan_hash,
    plan_path,
    read_plan,
    write_plan,
)
from hydromodpy.results.storage.contract import PLAN_CASES_FILENAME, PLAN_FILENAME

NOW = datetime(2026, 10, 20, 9, 15, tzinfo=UTC)
SITES = pd.DataFrame({"site": ["J0014010", "J0020000"], "gauge": ["J0014010", "J0020000"]})
TOMLS = {
    "J0014010-base": '[simulation]\nname = "J0014010-base"\n[flow]\nk = 1e-5\n',
    "J0020000-base": '[simulation]\nname = "J0020000-base"\n[flow]\nk = 2e-5\n',
}


def _plan(**overrides) -> Plan:
    payload = {
        "plan_hash": "a3f9c2e1",
        "hydromodpy_version": "2.1.0",
        "created_at": NOW,
        "fingerprints": {"project.toml": "ab" * 32, "sites.csv": "cd" * 32},
        "n_cases": 2,
        "budget": {"solves": 2, "peak_memory_gb": 1.5},
    }
    payload.update(overrides)
    return Plan(**payload)


def _cases() -> list[PlanCase]:
    return [
        PlanCase(
            case_id=case_id,
            site=case_id.split("-")[0],
            recipe="base",
            config_hash=f"h{n}",
            config_path=f"{case_id}.toml",
        )
        for n, case_id in enumerate(TOMLS)
    ]


def test_a_plan_lands_under_its_hash_with_its_three_kinds_of_files(tmp_path):
    directory = write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)

    assert directory == tmp_path / PLAN_DIRNAME / "a3f9c2e1" == plan_path(tmp_path, "a3f9c2e1")
    assert sorted(p.name for p in directory.iterdir()) == [
        "J0014010-base.toml",
        "J0020000-base.toml",
        PLAN_CASES_FILENAME,
        PLAN_FILENAME,
    ]
    assert current_plan_hash(tmp_path) == "a3f9c2e1"
    assert (tmp_path / PLAN_DIRNAME / "current").read_text(encoding="utf-8") == "a3f9c2e1\n"


def test_a_plan_reads_back_whole(tmp_path):
    write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)

    stored = read_plan(tmp_path)
    assert stored.plan == _plan()
    assert stored.sites.equals(SITES)
    assert list(stored.cases) == _cases()
    assert read_plan(tmp_path, "a3f9c2e1").directory == stored.directory


def test_cases_csv_starts_with_the_five_columns_then_the_site_columns(tmp_path):
    directory = write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)

    lines = (directory / PLAN_CASES_FILENAME).read_text(encoding="utf-8").splitlines()

    assert CASE_COLUMNS == ("case_id", "site", "recipe", "config_hash", "config_path")
    assert lines[0] == "case_id,site,recipe,config_hash,config_path,gauge"
    assert lines[1] == "J0014010-base,J0014010,base,h0,J0014010-base.toml,J0014010"
    assert "status" not in lines[0]


def test_a_site_with_two_cases_is_one_row_of_the_sites(tmp_path):
    cases = [
        PlanCase(
            case_id=f"J0014010-{r}",
            site="J0014010",
            recipe=r,
            config_hash="h",
            config_path=f"J0014010-{r}.toml",
        )
        for r in ("low", "high")
    ]
    tomls = {case.case_id: "[flow]\n" for case in cases}
    sites = pd.DataFrame({"site": ["J0014010"], "label": ["a; b"]})

    write_plan(tmp_path, _plan(n_cases=2), sites, cases, tomls)
    stored = read_plan(tmp_path)

    assert len(stored.cases) == 2
    assert stored.sites.to_dict("records") == [{"site": "J0014010", "label": "a; b"}]


def test_the_cells_of_a_site_are_text_and_an_empty_cell_stays_empty(tmp_path):
    sites = pd.DataFrame({"site": ["J0014010", "J0020000"], "gauge": ["J0014010", ""]})

    write_plan(tmp_path, _plan(), sites, _cases(), TOMLS)

    assert read_plan(tmp_path).sites["gauge"].tolist() == ["J0014010", ""]


def test_a_case_with_no_key_and_no_recipe_reads_back_as_it_was_written(tmp_path):
    case = PlanCase(case_id="J0014010", config_hash="", config_path="J0014010.toml")
    plan = _plan(n_cases=1)

    write_plan(tmp_path, plan, SITES.iloc[:0], [case], {"J0014010": "[flow]\n"})

    assert list(read_plan(tmp_path).cases) == [case]


def test_a_case_toml_replays_alone_from_another_cwd(tmp_path, monkeypatch):
    write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    text = read_plan(tmp_path).case_toml("J0020000-base")

    assert tomllib.loads(text)["flow"]["k"] == 2e-5
    assert tomllib.loads(text)["simulation"]["name"] == "J0020000-base"
    with pytest.raises(KeyError, match="no case 'missing'"):
        read_plan(tmp_path).case_toml("missing")


def test_the_same_plan_written_twice_is_a_no_op(tmp_path):
    first = write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)
    stamp = {p.name: p.stat().st_mtime_ns for p in first.iterdir()}

    second = write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)

    assert second == first
    assert {p.name: p.stat().st_mtime_ns for p in first.iterdir()} == stamp
    assert sorted(p.name for p in first.parent.iterdir()) == ["a3f9c2e1", "current"]


@pytest.mark.parametrize(
    "change",
    ["toml", "site cell"],
)
def test_other_content_under_an_existing_hash_is_refused_and_the_plan_kept(tmp_path, change):
    write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)
    tomls, sites = dict(TOMLS), SITES.copy()
    if change == "toml":
        tomls["J0020000-base"] = TOMLS["J0020000-base"].replace("2e-5", "3e-5")
    else:
        sites.loc[1, "gauge"] = "other"

    with pytest.raises(PlanConflictError, match="immutable"):
        write_plan(tmp_path, _plan(), sites, _cases(), tomls)

    assert read_plan(tmp_path).case_toml("J0020000-base") == TOMLS["J0020000-base"]
    assert read_plan(tmp_path).sites.equals(SITES)
    assert sorted(p.name for p in (tmp_path / PLAN_DIRNAME).iterdir()) == ["a3f9c2e1", "current"]


def test_a_failed_write_leaves_no_plan_and_no_staging(tmp_path, monkeypatch):
    def refuse(target, payload):
        raise OSError("disk full")

    monkeypatch.setattr(plan_store, "write_json_atomic", refuse)

    with pytest.raises(OSError, match="disk full"):
        write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)

    assert not plan_path(tmp_path, "a3f9c2e1").exists()
    assert current_plan_hash(tmp_path) is None
    assert [p.name for p in (tmp_path / PLAN_DIRNAME).iterdir()] == []


def test_current_moves_to_the_newest_plan_and_old_plans_stay(tmp_path):
    write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)
    newer = _plan(plan_hash="b7d2e9f0", fingerprints={"project.toml": "ef" * 32})
    write_plan(tmp_path, newer, SITES, _cases(), TOMLS)

    assert current_plan_hash(tmp_path) == "b7d2e9f0"
    assert sorted(p.name for p in (tmp_path / PLAN_DIRNAME).iterdir()) == [
        "a3f9c2e1",
        "b7d2e9f0",
        "current",
    ]
    assert read_plan(tmp_path, "a3f9c2e1").plan.plan_hash == "a3f9c2e1"


def test_a_project_without_plan_says_so(tmp_path):
    assert current_plan_hash(tmp_path) is None
    with pytest.raises(FileNotFoundError, match="no plan"):
        read_plan(tmp_path)


def test_cases_and_tomls_must_agree_with_the_plan(tmp_path):
    with pytest.raises(ValueError, match="n_cases is 1"):
        write_plan(tmp_path, _plan(n_cases=1), SITES, _cases(), TOMLS)
    with pytest.raises(ValueError, match="missing \\['J0020000-base'\\]"):
        write_plan(tmp_path, _plan(), SITES, _cases(), {"J0014010-base": TOMLS["J0014010-base"]})
    renamed = _cases()
    renamed[0] = renamed[0].model_copy(update={"config_path": "other.toml"})
    with pytest.raises(ValueError, match="names 'other.toml'"):
        write_plan(tmp_path, _plan(), SITES, renamed, TOMLS)
    with pytest.raises(ValueError, match="none of"):
        write_plan(tmp_path, _plan(), SITES.assign(recipe="x"), _cases(), TOMLS)
    assert not os.listdir(tmp_path / PLAN_DIRNAME) if (tmp_path / PLAN_DIRNAME).exists() else True


def _written(tmp_path):
    return write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)


def _as_2_0(directory):
    document = json.loads((directory / PLAN_FILENAME).read_text(encoding="utf-8"))
    document["schema"] = "hydromodpy.plan.v1"
    (directory / PLAN_FILENAME).write_text(json.dumps(document), encoding="utf-8")


def _drop_cases(directory):
    (directory / PLAN_CASES_FILENAME).unlink()


def _drop_toml(directory):
    (directory / "J0020000-base.toml").unlink()


@pytest.mark.parametrize(
    ("damage", "error", "sentence"),
    [
        (_as_2_0, SchemaVersionMismatchError, "cases.csv"),
        (_as_2_0, SchemaVersionMismatchError, "hmp project plan"),
        (_drop_cases, FileNotFoundError, PLAN_CASES_FILENAME),
    ],
    ids=["a plan of 2.0 names cases.csv", "a plan of 2.0 names the command", "cases.csv absent"],
)
def test_a_plan_that_cannot_be_read_is_refused_with_its_sentence(tmp_path, damage, error, sentence):
    damage(_written(tmp_path))

    with pytest.raises(error, match=sentence):
        read_plan(tmp_path)


def test_a_case_without_its_toml_is_found_when_its_text_is_asked(tmp_path):
    _drop_toml(_written(tmp_path))

    stored = read_plan(tmp_path)

    assert [case.case_id for case in stored.cases] == list(TOMLS)
    with pytest.raises(FileNotFoundError, match="J0020000-base.toml"):
        stored.case_toml("J0020000-base")


def test_the_models_refuse_what_they_do_not_know():
    with pytest.raises(ValidationError, match=PLAN_SCHEMA):
        Plan.model_validate({**_plan().model_dump(by_alias=True), "schema": "other"})
    with pytest.raises(ValidationError, match="status"):
        PlanCase.model_validate({**_cases()[0].model_dump(), "status": "planned"})
    with pytest.raises(ValidationError, match="case_id"):
        PlanCase(case_id="J0014010-base.v2", config_hash="h", config_path="x.toml")
