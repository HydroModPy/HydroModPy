"""A ledger names each derived file once, with how it was made, and is written whole under its lock."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.results.ledger import Ledger, LedgerEntry, ledger_path
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


def test_a_file_outside_the_directory_is_refused():
    with pytest.raises(ValidationError, match="inside its directory"):
        _entry("/tmp/heads.png")
    with pytest.raises(ValidationError, match="inside its directory"):
        _entry("../heads.png")


def test_two_entries_for_one_file_are_refused():
    with pytest.raises(ValidationError, match="each file once"):
        Ledger(entries=[_entry("heads.png"), _entry("heads.png")])


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


def test_a_record_whose_lock_was_taken_back_writes_nothing(tmp_path, monkeypatch):
    from hydromodpy.core.exceptions import WriteConflictError
    from hydromodpy.core.io.lock_file import LockFile
    from hydromodpy.results.ledger import record_derived_file

    path = tmp_path / "f.csv"
    path.write_text("x")
    monkeypatch.setattr(LockFile, "still_held", lambda self: False)

    with pytest.raises(WriteConflictError, match="taken back"):
        record_derived_file(
            tmp_path, path, producer="export.csv", options={}, identity=make_identity()
        )

    assert not ledger_path(tmp_path).exists()


def test_the_ledger_module_does_not_use_fcntl():
    import hydromodpy.results.ledger as ledger_module

    tree = ast.parse(Path(ledger_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "fcntl" not in imported
