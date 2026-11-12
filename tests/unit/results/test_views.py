"""A run reads its site, case, lineage, checks, label, inputs and scores from its own seal.

The facts come from ``manifest.json`` and ``inputs.json`` in the run
directory, never from the index: the catalog handle only says where the
directory is. A run that never completed has no seal and says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.errors import RunNotSealedError
from hydromodpy.results.run.view import Run
from hydromodpy.results.validity_rules import RULE_VERSION
from tests._helpers.run_records import SIM_ID, SITE, WINDOW, make_record


class _Directories:
    """A catalog handle that only knows where each run lives."""

    closed = False

    def __init__(self, dirs: dict[str, Path]) -> None:
        self._dirs = dirs

    def run_dir_for(self, sim_id: str) -> Path:
        return self._dirs[sim_id]


@pytest.fixture(autouse=True)
def _no_index(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("reading a sealed run opened the index")

    monkeypatch.setattr(Catalog, "__init__", _refuse)


def _sealed(tmp_path: Path, **overrides) -> Run:
    record = make_record(**overrides)
    run_dir = tmp_path / record.run.rel_dir
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    return Run(record.run.sim_id, _Directories({record.run.sim_id: run_dir}))


def test_a_run_opened_on_its_directory_answers_with_the_words_of_the_cli(tmp_path) -> None:
    """``site``, ``checks``, ``inputs``, ``label()`` from the seal, with no index (D9)."""
    from hydromodpy.results.run.view import open_run_dir

    sealed = _sealed(tmp_path)
    run = open_run_dir(sealed.dir)

    assert run.sim_id == SIM_ID
    assert run.site == SITE
    assert run.checks.budget_pct == pytest.approx(0.8)
    assert [entry.provider for entry in run.inputs] == ["hubeau"]
    assert run.label().label == "calibrated"
    assert run.exports == []
    assert run.figures == []


def test_exports_and_figures_are_the_files_their_ledger_records(tmp_path) -> None:
    from datetime import UTC, datetime

    from hydromodpy.core.io.file_digest import sha256_of
    from hydromodpy.results.ledger import Ledger, LedgerEntry
    from hydromodpy.results.run.view import open_run_dir

    run = open_run_dir(_sealed(tmp_path).dir)
    identity = run.record.identity
    for folder, name in (("exports", "head.tif"), ("figures", "piezometric_map.png")):
        directory = run.dir / folder
        directory.mkdir()
        (directory / name).write_bytes(b"payload")
        (directory / "stray.txt").write_text("not recorded", encoding="utf-8")
        ledger = Ledger()
        ledger.append(
            LedgerEntry(
                file=name,
                producer="test",
                hydromodpy_version="2.0.0a5",
                at=datetime.now(UTC),
                sha256=sha256_of(directory / name),
                identity=identity,
            )
        )
        ledger.write(directory)

    assert run.exports == [run.dir / "exports" / "head.tif"]
    assert run.figures == [run.dir / "figures" / "piezometric_map.png"]


def test_a_run_directory_that_never_completed_is_not_opened_alone(tmp_path) -> None:
    from hydromodpy.results.run.view import open_run_dir

    run_dir = tmp_path / "runs" / "J0014010-base"
    run_dir.mkdir(parents=True)

    with pytest.raises(RunNotSealedError, match="never completed"):
        open_run_dir(run_dir)


def test_a_run_reads_its_checks_and_its_label_of_the_day(tmp_path) -> None:
    run = _sealed(tmp_path)

    assert run.record.checks.budget_pct == pytest.approx(0.8)
    assert run.record.checks.score_window == WINDOW
    label = run.label()
    assert label.label == "calibrated"
    assert label.rule_version == RULE_VERSION


def test_a_run_that_never_completed_has_no_seal(tmp_path) -> None:
    run_dir = tmp_path / "runs" / "J0014010-base"
    run_dir.mkdir(parents=True)
    run = Run(SIM_ID, _Directories({SIM_ID: run_dir}))

    with pytest.raises(RunNotSealedError, match="never completed"):
        _ = run.record
    with pytest.raises(RunNotSealedError):
        run.label()
    assert run.metrics.empty
