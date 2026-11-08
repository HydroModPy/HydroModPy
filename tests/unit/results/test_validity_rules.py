"""The label is a function of reading: calibrated, evaluated, failed, or declassed by a known issue."""

from __future__ import annotations

from datetime import date

import pytest
from packaging.specifiers import SpecifierSet
from pydantic import ValidationError

from hydromodpy.mesh import registry as mesh_registry
from hydromodpy.results.checks import Checks, Validity
from hydromodpy.results.manifest import RUN_MANIFEST_FILENAME
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.validity_rules import (
    KnownIssue,
    ValidityRules,
    known_issues_hitting,
    label_for,
    load_known_issues,
    run_quantities,
)
from hydromodpy.solver.base import registry as solver_registry
from tests._helpers.run_records import (
    WINDOW,
    make_calibrated_by,
    make_checks,
    make_identity,
    make_record,
)

CURRENT = "2.0.0a5"
MF6 = run_quantities(solver="modflow6", mesh_engine="voronoi", has_metrics=True)


CALIBRATION_WINDOW = DateWindow(start=date(2010, 1, 1), end=date(2015, 12, 31))


def _promoted(status: str, window: DateWindow | None = None, **overrides) -> Checks:
    return make_checks(calibrated_by=make_calibrated_by(window, status=status), **overrides)


def test_calibrated_only_when_the_session_completed_and_no_fatal_validity_failed():
    result = label_for(
        _promoted("completed"), hydromodpy_version=CURRENT, quantities=MF6, issues=()
    )
    assert result.label == "calibrated"
    assert result.rule_version == ValidityRules().rule_version
    assert result.known_issues == ()


@pytest.mark.parametrize("status", ["partial", "aborted"])
def test_a_promoted_run_of_an_unfinished_session_is_not_calibrated(status):
    checks = _promoted(status, window=CALIBRATION_WINDOW)
    result = label_for(checks, hydromodpy_version=CURRENT, quantities=MF6, issues=())
    assert result.label == "exploratory"
    assert any(status in reason for reason in result.reasons)


def test_a_run_that_did_not_converge_is_failed_before_any_other_rule():
    issue = KnownIssue(
        id="x", versions="<3", quantities=["heads@modflow6"], since_commit="abc", description="d"
    )
    checks = _promoted("completed", converged=False)
    result = label_for(checks, hydromodpy_version=CURRENT, quantities=MF6, issues=[issue])
    assert result.label == "failed"
    assert result.reasons == ("solver did not converge",)
    assert result.known_issues == ()


def test_unknown_convergence_is_not_a_failure():
    checks = _promoted("completed", converged=None)
    assert label_for(checks, hydromodpy_version=CURRENT, issues=()).label == "calibrated"


def test_a_fatal_validity_wins_over_a_failed_convergence():
    checks = _promoted(
        "completed",
        converged=False,
        validities=[Validity("water_budget", False, 12.0, "does not close", True)],
    )
    result = label_for(checks, hydromodpy_version=CURRENT, issues=())
    assert result.label == "failed"
    assert "water_budget" in result.reasons[0]


def test_a_fatal_failure_makes_the_run_failed_even_when_promoted():
    checks = _promoted(
        "completed", validities=[Validity("water_budget", False, 12.0, "does not close", True)]
    )
    result = label_for(checks, hydromodpy_version=CURRENT, quantities=MF6, issues=())
    assert result.label == "failed"
    assert "water_budget" in result.reasons[0]


def test_a_non_fatal_failure_does_not_touch_the_label():
    checks = _promoted("completed", validities=[Validity("coverage", False, 0.3, "thin", False)])
    assert label_for(checks, hydromodpy_version=CURRENT, issues=()).label == "calibrated"


def test_evaluated_when_a_calibrated_run_is_scored_outside_the_calibration_window():
    checks = _promoted("completed", window=CALIBRATION_WINDOW)
    assert checks.score_window != CALIBRATION_WINDOW
    result = label_for(checks, hydromodpy_version=CURRENT, quantities=MF6, issues=())
    assert result.label == "evaluated"
    assert "1827 samples" in result.reasons[1]
    assert "outside the calibration window 2010-01-01 to 2015-12-31" in result.reasons[1]


def test_a_run_scored_on_the_calibration_window_stays_calibrated():
    checks = _promoted("completed", window=WINDOW)
    assert label_for(checks, hydromodpy_version=CURRENT, issues=()).label == "calibrated"


def test_an_unrecorded_calibration_window_cannot_make_a_run_evaluated():
    checks = _promoted("completed", window=None)
    assert label_for(checks, hydromodpy_version=CURRENT, issues=()).label == "calibrated"


def test_a_scored_run_without_a_session_stays_exploratory():
    checks = Checks(score_window=WINDOW, n_samples=1827)
    result = label_for(checks, hydromodpy_version=CURRENT, quantities=MF6, issues=())
    assert result.label == "exploratory"
    assert result.reasons == ("scored on 2016-01-01 to 2020-12-31, not promoted by a session",)


def test_exploratory_without_a_window_or_without_samples():
    assert label_for(Checks(), hydromodpy_version=CURRENT, issues=()).label == "exploratory"
    thin = Checks(score_window=WINDOW, n_samples=0)
    assert label_for(thin, hydromodpy_version=CURRENT, issues=()).label == "exploratory"


def test_the_rules_are_a_model_that_can_be_tightened():
    rules = ValidityRules(min_scored_samples=2000)
    checks = _promoted("completed", window=CALIBRATION_WINDOW)
    assert (
        label_for(checks, hydromodpy_version=CURRENT, rules=rules, issues=()).label == "calibrated"
    )


def test_a_known_issue_declasses_an_old_version_without_rewriting_the_seal(tmp_path):
    record = make_record()
    record.write(tmp_path)
    sealed = (tmp_path / RUN_MANIFEST_FILENAME).read_bytes()
    issue = KnownIssue(
        id="mf6_top",
        versions="<2.0.0a5",
        quantities=["heads@modflow6"],
        since_commit="b1fa87021",
        description="the top was the ground",
    )

    old = label_for(record.checks, hydromodpy_version="2.0.0a4", quantities=MF6, issues=[issue])
    new = label_for(record.checks, hydromodpy_version="2.0.0a5", quantities=MF6, issues=[issue])

    assert old.label == "exploratory" and old.known_issues == ("mf6_top",)
    assert "the top was the ground" in old.reasons[0]
    assert new.label == "calibrated"
    assert (tmp_path / RUN_MANIFEST_FILENAME).read_bytes() == sealed


def test_a_known_issue_on_another_quantity_leaves_the_run_alone():
    issue = KnownIssue(
        id="x", versions="<3", quantities=["heads@boussinesq"], since_commit="abc", description="d"
    )
    result = label_for(
        _promoted("completed"), hydromodpy_version="2.0.0a4", quantities=MF6, issues=[issue]
    )
    assert result.label == "calibrated"


def test_a_failed_run_stays_failed_under_a_known_issue():
    issue = KnownIssue(
        id="x", versions="<3", quantities=["heads@modflow6"], since_commit="abc", description="d"
    )
    checks = Checks(validities=[Validity("water_budget", False, 9.0, "no", True)])
    assert (
        label_for(checks, hydromodpy_version=CURRENT, quantities=MF6, issues=[issue]).label
        == "failed"
    )


def test_the_shipped_register_holds_the_three_real_issues_with_valid_specifiers():
    issues = load_known_issues()
    assert [issue.id for issue in issues] == [
        "discharge_scores_before_period_alignment",
        "voronoi_nwt_boussinesq_fixes_2026_10_09",
        "mf6_computation_top",
    ]
    for issue in issues:
        SpecifierSet(issue.versions)
        assert issue.since_commit


def test_the_shipped_register_declasses_the_versions_it_names_and_not_the_current_one():
    hits_a1 = {i.id for i in known_issues_hitting("2.0.0a1", MF6)}
    hits_a5 = {i.id for i in known_issues_hitting(CURRENT, MF6)}
    hits_old = {i.id for i in known_issues_hitting("1.0.0", MF6)}

    assert hits_a1 == {"voronoi_nwt_boussinesq_fixes_2026_10_09", "mf6_computation_top"}
    assert hits_a5 == set()
    assert "discharge_scores_before_period_alignment" in hits_old


def test_a_fix_of_a_derived_field_declasses_the_runs_sealed_under_the_old_rules():
    issue = KnownIssue(
        id="seepage_band",
        versions=">=2.0.0a1",
        quantities=["derived@1"],
        since_commit="abc",
        description="The seepage mask of these runs read the wrong band.",
    )
    sealed_under = run_quantities(solver="modflow6", derive_rule_version="1")
    assert "derived@1" in sealed_under

    old = label_for(
        make_checks(), hydromodpy_version="2.0.1", quantities=sealed_under, issues=[issue]
    )
    assert old.label == "exploratory"
    assert old.known_issues == ("seepage_band",)

    new = label_for(
        make_checks(),
        hydromodpy_version="2.0.1",
        quantities=run_quantities(solver="modflow6", derive_rule_version="2"),
        issues=[issue],
    )
    assert new.known_issues == ()


def test_run_quantities_spell_the_vocabulary_of_the_register():
    assert run_quantities(solver="boussinesq") == ("heads@boussinesq", "fluxes@boussinesq")
    assert run_quantities(solver="modflow_nwt", mesh_engine="regular", has_metrics=True) == (
        "heads@modflow_nwt",
        "fluxes@modflow_nwt",
        "mesh@regular",
        "metrics",
    )


def test_every_register_token_names_a_real_solver_or_mesh_engine():
    solvers = set(solver_registry.solvers.names("flow"))
    engines = set(mesh_registry.mesh_engines.names(shipped_only=True))
    allowed = {"metrics"}
    allowed |= {f"{kind}@{solver}" for kind in ("heads", "fluxes") for solver in solvers}
    allowed |= {f"mesh@{engine}" for engine in engines}

    unknown = {
        (issue.id, token)
        for issue in load_known_issues()
        for token in issue.quantities
        if token not in allowed
    }
    assert unknown == set(), f"tokens naming no solver or mesh engine: {sorted(unknown)}"


def test_an_issue_without_a_fix_commit_or_with_a_bad_id_is_refused():
    with pytest.raises(ValidationError, match="since_commit"):
        KnownIssue(id="x", versions="<3", quantities=["metrics"], description="d")
    with pytest.raises(ValidationError, match="id"):
        KnownIssue(
            id="Bad Id", versions="<3", quantities=["metrics"], since_commit="a", description="d"
        )


def test_the_label_carries_the_rule_version_a_reader_can_cite():
    result = label_for(make_checks(), hydromodpy_version=CURRENT, issues=())
    assert result.rule_version == "2"
    assert (
        make_identity()
        .labelled(result.label, label_date=WINDOW.end, rule_version=result.rule_version)
        .label
        == "calibrated"
    )
