"""Two processes that record a derived file at once both survive in the ledger."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

from hydromodpy.results.ledger import Ledger
from tests._helpers.run_records import make_identity


def _record_one(directory: str, name: str) -> None:
    """Write a file and record it, in a process of its own."""
    from hydromodpy.results.ledger import record_derived_file

    path = Path(directory) / name
    path.write_text(name, encoding="utf-8")
    record_derived_file(
        directory, path, producer="export.csv", options={}, identity=make_identity()
    )


def test_two_processes_recording_at_once_both_survive(tmp_path):
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_record_one, args=(str(tmp_path), name))
        for name in ("a.csv", "b.csv")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(120)

    assert [worker.exitcode for worker in workers] == [0, 0]
    assert sorted(entry.file for entry in Ledger.read(tmp_path).entries) == ["a.csv", "b.csv"]
