"""A run reads its site, case, lineage, checks, label, inputs and scores from its own seal.

The facts come from ``manifest.json`` and ``inputs.json`` in the run
directory, never from the index: the catalog handle only says where the
directory is. A run that never completed has no seal and says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.checks import Validity
from hydromodpy.results.errors import RunNotSealedError
from hydromodpy.results.metric_rule import EVALUATION_ROLE, HEADLINE_WINDOW
from hydromodpy.results.run import Run
from hydromodpy.results.run.sealed import lineage_of
from tests._helpers.metric_rows import headline_score
from tests._helpers.run_records import (
    CASE_ID,
    SIM_ID,
    SITE,
    WINDOW,
    make_checks,
    make_record,
)


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


def test_a_run_reads_its_site_case_lineage_and_inputs(tmp_path) -> None:
    run = _sealed(tmp_path)

    record = run.record
    assert run.dir == tmp_path / "runs" / "J0014010-base.v2"
    assert record.site.name == SITE
    assert record.site.gauge == "J0014010"
    assert record.run.case_id == CASE_ID
    assert record.lineage.kind == "promoted"
    assert record.lineage.session_id == "sess0001"
    assert lineage_of(run) == record.lineage
    assert [entry.provider for entry in record.inputs] == ["hubeau"]
    assert record.inputs[0].license == "etalab-2.0"


def test_the_parent_of_a_run_is_named_by_its_sealed_lineage(tmp_path) -> None:
    from hydromodpy.results.lineage import Lineage

    parent_id = SIM_ID[:-2] + "99"
    run = _sealed(tmp_path, lineage=Lineage(parent_sim_id=parent_id, kind="rerun"))

    assert lineage_of(run).parent_sim_id == parent_id
    assert lineage_of(_sealed(tmp_path / "orphan", lineage=Lineage())).parent_sim_id is None


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
    assert label.rule_version == "2"


def test_a_failed_fatal_validity_labels_the_run_failed(tmp_path) -> None:
    checks = make_checks(validities=[Validity("water_budget", False, 9.0, "open budget", True)])
    run = _sealed(tmp_path, checks=checks)

    assert run.label().label == "failed"


def test_the_metrics_of_a_run_carry_their_window(tmp_path) -> None:
    run = _sealed(tmp_path)

    frame = run.metrics
    assert list(frame.columns) == [
        "station",
        "variable",
        "metric",
        "value",
        "window_name",
        "window_role",
        "window_start",
        "window_end",
        "n_samples",
        "metric_rule_version",
        "n_clipped",
        "n_sim_nan",
    ]
    row = frame.iloc[0]
    assert (row["station"], row["metric"], row["value"]) == ("J0014010", "nse", 0.81)
    assert (row["window_name"], row["window_role"]) == (HEADLINE_WINDOW, EVALUATION_ROLE)
    assert (row["window_start"], row["window_end"]) == (WINDOW.start, WINDOW.end)


def test_a_run_that_never_completed_has_no_seal(tmp_path) -> None:
    run_dir = tmp_path / "runs" / "J0014010-base"
    run_dir.mkdir(parents=True)
    run = Run(SIM_ID, _Directories({SIM_ID: run_dir}))

    with pytest.raises(RunNotSealedError, match="never completed"):
        _ = run.record
    with pytest.raises(RunNotSealedError):
        run.label()
    assert run.metrics.empty


def test_the_headline_score_names_where_it_was_read(tmp_path) -> None:
    run = _sealed(tmp_path, score=headline_score(0.81, n_samples=1827))

    sealed = run._record().score  # noqa: SLF001 - the read-back of the seal
    assert (sealed.station, sealed.variable) == ("J0014010", "discharge")


def test_a_run_without_a_seal_exits_as_not_found() -> None:
    from hydromodpy.cli.helpers import EXIT_NOT_FOUND, exit_code_for

    error = RunNotSealedError("never completed")
    assert error.code == "HMPY.E825"
    assert exit_code_for(error) == EXIT_NOT_FOUND
