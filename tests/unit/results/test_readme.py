"""The generated README says what the thing is and ends with the digest of its manifest."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, date, datetime

from hydromodpy.results.manifest import ManifestPeriod
from hydromodpy.results.outcome import Outcome, OutcomeError
from hydromodpy.results.readme import (
    SummaryFacts,
    manifest_sha256,
    render_run_readme,
    render_session_readme,
    render_summary_readme,
    render_unsealed_run_readme,
    write_readme,
)
from hydromodpy.results.session.descriptor import (
    CostInterval,
    ParameterBound,
    ParameterWidth,
    ScoredSamples,
)
from hydromodpy.results.session.phase import FrozenValue, PhaseDescriptor
from hydromodpy.results.validity_rules import LabelResult, label_for, run_quantities
from tests._helpers.run_records import NOW, WINDOW, make_record
from tests._helpers.session_documents import best_trial, session_descriptor, trial_line

LABEL = LabelResult("calibrated", "2", ("promoted by session sess0001, completed",), ())


def _outcome() -> Outcome:
    return Outcome(
        case_id="J0014010-base",
        attempt=2,
        attempt_id="7c1e" * 8,
        sim_id="9a4f" * 8,
        status="failed",
        exit_code=15,
        written_by="launcher",
        started_at=NOW,
        ended_at=NOW,
        host="node12",
        pid=4421,
        error=OutcomeError(type="SolverError", message="mf6 did not converge at stress period 51"),
    )


def test_the_run_readme_says_site_period_version_checks_label_and_score(tmp_path):
    record = make_record()
    record.write(tmp_path)
    digest = manifest_sha256(tmp_path)

    text = render_run_readme(record, _outcome(), LABEL, manifest_sha256=digest)

    assert text.startswith("# J0014010-base\n")
    assert "`J0014010`: Nancon" in text
    assert "gauge `J0014010`, hubeau:J0014010" in text
    assert re.search(r"outlet WGS84: lon -1\.\d+, lat 48\.\d+", text)
    assert "2016-01-01 to 2020-12-31, 1827 day." in text
    assert "HydroModPy 2.0.0a5, solver `modflow6`, mesh engine `voronoi`" in text
    assert "code reproducible: no" in text
    assert "water budget 0.8 % (accepted up to 2 %)" in text
    assert "**calibrated** under rules 2." in text
    assert "NSE 0.81 on 2016-01-01 to 2020-12-31, 1827 samples, rule 1." in text
    assert "SolverError: mf6 did not converge at stress period 51" in text
    assert text.rstrip().endswith(f"sha256(manifest.json) = {digest}")


def test_the_run_readme_names_no_host_user_or_absolute_path(tmp_path):
    record = make_record()
    record.write(tmp_path)

    text = render_run_readme(record, _outcome(), LABEL, manifest_sha256=manifest_sha256(tmp_path))

    assert "node12" not in text
    assert "/home/" not in text
    assert str(tmp_path) not in text


def test_a_steady_run_says_it_has_no_period(tmp_path):
    record = make_record(period=ManifestPeriod())
    text = render_run_readme(record, None, LABEL, manifest_sha256="0" * 64)
    assert "Steady state, no period." in text
    assert "## Outcome" not in text


def test_the_label_of_the_day_is_the_one_rendered(tmp_path):
    record = make_record()
    result = label_for(
        record.checks, hydromodpy_version="2.0.0a4", quantities=run_quantities(solver="modflow6")
    )
    text = render_run_readme(record, None, result, manifest_sha256="0" * 64)
    assert "**exploratory** under rules 2." in text
    assert "known issues: mf6_computation_top" in text


def test_write_readme_lands_atomically(tmp_path):
    path = write_readme(tmp_path, "# x\n")
    assert path == tmp_path / "README.md"
    assert path.read_text(encoding="utf-8") == "# x\n"
    assert [p.name for p in tmp_path.iterdir()] == ["README.md"]


def test_the_session_readme_names_the_method_phases_best_trial_and_promoted_run():
    descriptor = session_descriptor(
        "J0014010-calage",
        site="J0014010",
        session_id="sess0001",
        method="tpe",
        cost_name="nse_log",
        bounds={"K": ParameterBound(lower=1e-7, upper=1e-4, search_space="log", units="m/s")},
        cost_label="1 - nse_log",
        widths={"K": ParameterWidth(interval=CostInterval(lower=2e-5, upper=9e-5))},
        scored=[ScoredSamples(window="calibration", case_id="c", output="hydrograph", n=1828)],
        best=best_trial(
            7,
            cost=-0.84,
            parameters={"K": 6.4e-5},
            case="J0014010-calage",
            sim_id="9a4f" * 8,
            rel_dir="runs/J0014010-calage",
        ),
        status="completed",
        ended_at=NOW,
    )
    trials = [trial_line(n, phase="transient_sy") for n in range(1, 8)]
    phases = [
        PhaseDescriptor(
            phase_id="p1", name="steady_k", index=0, status="completed", best=best_trial(3)
        ),
        PhaseDescriptor(
            phase_id="p2",
            name="transient_sy",
            index=1,
            status="completed",
            frozen={
                "K": FrozenValue(value=6.1e-6, mode="replace", from_phase="steady_k"),
            },
        ),
    ]

    text = render_session_readme(
        descriptor, trials, LABEL, phases=phases, manifest_sha256="ab" * 32
    )

    assert text.startswith("# Calibration J0014010-calage\n")
    assert "site `J0014010`, method `tpe`, cost `nse_log`, status **completed**" in text
    assert "- `K`: 1e-07 to 0.0001 m/s, log" in text
    assert "7 trials in `trials.jsonl`" in text
    assert "| steady_k | completed | 0 | none | 3 | not recorded |" in text
    assert "K = 6.1e-06 (steady_k)" in text
    assert "- trial 7, cost -0.84 (1 - nse_log)\n" in text
    assert "- `K` = 6.4e-05 m/s, interval 2e-05 to 9e-05\n" in text
    assert "- scored on hydrograph 1828 pair(s)\n" in text
    assert "calibrated run of `J0014010-calage`: `runs/J0014010-calage` (sim_id `" in text
    assert text.rstrip().endswith(f"sha256(manifest.json) = {'ab' * 32}")


def test_the_summary_readme_counts_cases_sites_versions_and_lists_its_digests():
    facts = SummaryFacts(
        project="bretagne_k",
        n_planned=300,
        n_completed=287,
        sites=("J0014010", "J0020000"),
        versions=("2.0.0a5",),
        collected_at=datetime(2026, 10, 20, 9, 15, tzinfo=UTC),
        period=WINDOW,
        label_date=date(2026, 10, 20),
        rule_version="2",
        best="calibrated",
        catalog_written=False,
    )
    text = render_summary_readme(facts, digests={"by_case.parquet": "cd" * 32})

    assert "287 completed of 300 planned cases, 2 sites, 2016-01-01 to 2020-12-31." in text
    assert "HydroModPy versions met: 2.0.0a5" in text
    assert "labels computed on 2026-10-20 under rules 2" in text
    assert "one row per site: the best calibrated case" in text
    assert "catalog.csv" not in text
    assert "- J0014010\n- J0020000" in text
    assert text.rstrip().endswith(f"sha256(by_case.parquet) = {'cd' * 32}")

    text = render_summary_readme(
        replace(facts, best="any", catalog_written=True), digests={"by_case.parquet": "cd" * 32}
    )

    assert 'one row per site: the best case whatever its label (best = "any")' in text
    assert "- `catalog.csv`: the sites as a table, replayable as an input" in text


def test_a_failed_run_gets_a_readme_from_its_outcome_alone(tmp_path):
    outcome = _outcome().model_copy(update={"step": "run_solver", "log_tail": ["IMS failed"]})

    text = render_unsealed_run_readme(outcome)
    write_readme(tmp_path, text)

    assert text.startswith("# J0014010-base\n")
    assert "status **failed**" in text
    assert "No `manifest.json`" in text
    assert "SolverError: mf6 did not converge at stress period 51" in text
    assert "last step reached: `run_solver`" in text
    assert "IMS failed" in text
    assert "sha256(" not in text
    assert "node12" not in text
    assert not (tmp_path / "manifest.json").exists()
