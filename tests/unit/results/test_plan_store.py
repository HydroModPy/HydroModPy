"""A plan is written once under its hash, pointed at by plan/current, and never rewritten in place."""

from __future__ import annotations

import os
import tomllib
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from hydromodpy.core.state.paths import PLAN_DIRNAME
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
from hydromodpy.results.storage.contract import (
    PLAN_CASES_FILENAME,
    PLAN_FILENAME,
    PLAN_SITES_FILENAME,
)

NOW = datetime(2026, 10, 20, 9, 15, tzinfo=UTC)
SITES = pa.table({"site": ["J0014010", "J0020000"], "gauge": ["J0014010", "J0020000"]})
TOMLS = {
    "J0014010-base": '[simulation]\nname = "J0014010-base"\n[flow]\nk = 1e-5\n',
    "J0020000-base": '[simulation]\nname = "J0020000-base"\n[flow]\nk = 2e-5\n',
}


def _plan(**overrides) -> Plan:
    payload = {
        "plan_hash": "a3f9c2e1",
        "hydromodpy_version": "2.0.0a5",
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


def test_a_plan_lands_under_its_hash_with_its_four_kinds_of_files(tmp_path):
    directory = write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)

    assert directory == tmp_path / PLAN_DIRNAME / "a3f9c2e1" == plan_path(tmp_path, "a3f9c2e1")
    assert sorted(p.name for p in directory.iterdir()) == [
        "J0014010-base.toml",
        "J0020000-base.toml",
        PLAN_CASES_FILENAME,
        PLAN_FILENAME,
        PLAN_SITES_FILENAME,
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


def test_cases_parquet_has_no_status_column(tmp_path):
    directory = write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)
    names = pq.read_schema(directory / PLAN_CASES_FILENAME).names
    assert names == ["case_id", "site", "recipe", "config_hash", "config_path"]
    assert "status" not in names


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


def test_other_content_under_an_existing_hash_is_refused_and_the_plan_kept(tmp_path):
    write_plan(tmp_path, _plan(), SITES, _cases(), TOMLS)
    changed = {**TOMLS, "J0020000-base": TOMLS["J0020000-base"].replace("2e-5", "3e-5")}

    with pytest.raises(PlanConflictError, match="immutable"):
        write_plan(tmp_path, _plan(), SITES, _cases(), changed)

    assert read_plan(tmp_path).case_toml("J0020000-base") == TOMLS["J0020000-base"]
    assert sorted(p.name for p in (tmp_path / PLAN_DIRNAME).iterdir()) == ["a3f9c2e1", "current"]


def test_a_failed_write_leaves_no_plan_and_no_staging(tmp_path, monkeypatch):
    def refuse(table, target, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(plan_store, "write_table_atomic", refuse)

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
    assert not os.listdir(tmp_path / PLAN_DIRNAME) if (tmp_path / PLAN_DIRNAME).exists() else True


def test_the_models_refuse_what_they_do_not_know():
    with pytest.raises(ValidationError, match=PLAN_SCHEMA):
        Plan.model_validate({**_plan().model_dump(by_alias=True), "schema": "other"})
    with pytest.raises(ValidationError, match="status"):
        PlanCase.model_validate({**_cases()[0].model_dump(), "status": "planned"})
    with pytest.raises(ValidationError, match="case_id"):
        PlanCase(case_id="J0014010-base.v2", config_hash="h", config_path="x.toml")
