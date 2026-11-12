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


@pytest.mark.parametrize(
    ("damage", "error", "sentence"),
    [
        (_as_2_0, SchemaVersionMismatchError, "cases.csv"),
        (_as_2_0, SchemaVersionMismatchError, "hmp project plan"),
        (_drop_cases, FileNotFoundError, PLAN_CASES_FILENAME),
    ],
    ids=[
        "a plan of a pre-release names cases.csv",
        "a plan of a pre-release names the command",
        "cases.csv absent",
    ],
)
def test_a_plan_that_cannot_be_read_is_refused_with_its_sentence(tmp_path, damage, error, sentence):
    damage(_written(tmp_path))

    with pytest.raises(error, match=sentence):
        read_plan(tmp_path)


def test_the_models_refuse_what_they_do_not_know():
    with pytest.raises(ValidationError, match=PLAN_SCHEMA):
        Plan.model_validate({**_plan().model_dump(by_alias=True), "schema": "other"})
    with pytest.raises(ValidationError, match="status"):
        PlanCase.model_validate({**_cases()[0].model_dump(), "status": "planned"})
    with pytest.raises(ValidationError, match="case_id"):
        PlanCase(case_id="J0014010-base.v2", config_hash="h", config_path="x.toml")
