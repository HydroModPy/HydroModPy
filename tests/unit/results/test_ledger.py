"""A ledger names each derived file once, with how it was made, and is written whole."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.results.ledger import LEDGER_SCHEMA, Ledger, LedgerEntry, ledger_path
from tests._helpers.run_records import make_identity

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def _entry(file: str, **overrides) -> LedgerEntry:
    payload = {
        "file": file,
        "producer": "display.figures.heads",
        "options": {"layer": 0, "cmap": "viridis"},
        "hydromodpy_version": "2.0.0a5",
        "at": NOW,
        "sha256": "ab" * 32,
        "identity": make_identity(),
    }
    payload.update(overrides)
    return LedgerEntry(**payload)


def test_a_ledger_round_trips(tmp_path):
    ledger = Ledger(entries=[_entry("heads.png"), _entry("discharge.csv", producer="export.csv")])
    ledger.write(tmp_path)

    assert Ledger.read(tmp_path) == ledger
    assert (
        (tmp_path / "index.json")
        .read_text(encoding="utf-8")
        .startswith('{\n  "schema": "hydromodpy.ledger.v1"')
    )


def test_a_directory_without_ledger_reads_as_empty(tmp_path):
    ledger = Ledger.read(tmp_path)
    assert ledger.entries == [] and ledger.schema_ == LEDGER_SCHEMA


def test_append_replaces_the_entry_of_the_same_file(tmp_path):
    ledger = Ledger.read(tmp_path)
    ledger.append(_entry("heads.png", sha256="aa" * 32))
    ledger.append(_entry("heads.png", sha256="bb" * 32))
    ledger.append(_entry("budget.png"))
    ledger.write(tmp_path)

    back = Ledger.read(tmp_path)
    assert [entry.file for entry in back.entries] == ["heads.png", "budget.png"]
    assert back.entry_for("heads.png").sha256 == "bb" * 32
    assert back.entry_for("missing.png") is None


def test_the_write_is_whole_and_leaves_no_temporary(tmp_path):
    (tmp_path / "heads.png").write_bytes(b"old")
    Ledger(entries=[_entry("heads.png")]).write(tmp_path)
    Ledger(entries=[_entry("heads.png"), _entry("budget.png")]).write(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["heads.png", "index.json"]
    assert ledger_path(tmp_path) == tmp_path / "index.json"


def test_sha256_of_a_file_is_its_digest(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hydromodpy")
    assert sha256_of(path) == hashlib.sha256(b"hydromodpy").hexdigest()


def test_a_file_outside_the_directory_is_refused():
    with pytest.raises(ValidationError, match="inside its directory"):
        _entry("/tmp/heads.png")
    with pytest.raises(ValidationError, match="inside its directory"):
        _entry("../heads.png")


def test_two_entries_for_one_file_are_refused():
    with pytest.raises(ValidationError, match="each file once"):
        Ledger(entries=[_entry("heads.png"), _entry("heads.png")])


def test_a_bad_digest_or_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="sha256"):
        _entry("heads.png", sha256="not-a-digest")
    with pytest.raises(ValidationError, match="label"):
        LedgerEntry.model_validate({**_entry("heads.png").model_dump(), "label": "x"})


def test_concurrent_records_of_derived_files_all_survive(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from hydromodpy.results.ledger import record_derived_file

    files = []
    for index in range(8):
        path = tmp_path / f"f{index}.csv"
        path.write_text(str(index))
        files.append(path)

    def record(path):
        record_derived_file(
            tmp_path, path, producer="export.csv", options={}, identity=make_identity()
        )

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(record, files))

    assert len(Ledger.read(tmp_path).entries) == 8
