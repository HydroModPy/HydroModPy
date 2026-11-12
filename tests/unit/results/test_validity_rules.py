"""The label is a function of reading: calibrated, evaluated, failed, or declassed by a known issue.

Under rule 3 a promoted run is calibrated only when a window was scored, and a
parameter on a bound of its range adds a reason to any label.
"""

from __future__ import annotations

from datetime import date

import pytest
from packaging.specifiers import SpecifierSet

from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.record.checks import Checks, Validity
from hydromodpy.results.record.label import declared_start_tokens
from hydromodpy.results.validity_rules import (
    CYCLIC_LAKE_START,
    REASON_CODES,
    RESTART_START,
    LabelResult,
    Reason,
    label_for,
    run_quantities,
)
from hydromodpy.schema.changes import REGISTER, Bug, read
from hydromodpy.schema.sources import source_entry
from tests._helpers.run_records import WINDOW, make_calibrated_by, make_checks

CURRENT = "2.0.0a5"
MF6 = run_quantities(solver="modflow6", mesh_engine="voronoi", has_metrics=True)


CALIBRATION_WINDOW = DateWindow(start=date(2010, 1, 1), end=date(2015, 12, 31))


def _promoted(status: str, window: DateWindow | None = None, **overrides) -> Checks:
    return make_checks(calibrated_by=make_calibrated_by(window, status=status), **overrides)


def test_a_non_fatal_failure_does_not_touch_the_label():
    checks = _promoted("completed", validities=[Validity("coverage", False, 0.3, "thin", False)])
    assert label_for(checks, hydromodpy_version=CURRENT, issues=()).label == "calibrated"


def test_exploratory_without_a_window_or_without_samples():
    assert label_for(Checks(), hydromodpy_version=CURRENT, issues=()).label == "exploratory"
    thin = Checks(score_window=WINDOW, n_samples=0)
    assert label_for(thin, hydromodpy_version=CURRENT, issues=()).label == "exploratory"


def test_the_shipped_register_holds_the_three_real_issues_with_valid_specifiers():
    by_id = {issue.id: issue for issue in REGISTER.bugs}
    for known in (
        "discharge_scores_before_period_alignment",
        "voronoi_nwt_boussinesq_fixes_2026_10_09",
        "mf6_computation_top",
    ):
        assert by_id[known].commit
    for issue in REGISTER.bugs:
        SpecifierSet(issue.versions)


def _a_known_token(token: str, allowed: set[str]) -> bool:
    """A source token names a registered source: ``source@<section>_<slug>``."""
    if token.startswith("source@"):
        _section, _, slug = token.removeprefix("source@").partition("_")
        return source_entry(slug) is not None
    return token in allowed


_BAD_BUGS = {
    "a bad id": ('id = "Bad Id"', "id must match"),
    "a commit that is no sha": ('commit = "not-a-sha"', "commit must be a hex sha"),
    "versions that are no specifier": ('versions = "two point one"', "versions must be"),
    "no quantity": ("quantities = []", "quantities is empty"),
}


@pytest.mark.parametrize(("change", "fault"), _BAD_BUGS.values(), ids=_BAD_BUGS.keys())
def test_an_issue_with_a_bad_field_is_refused(change: str, fault: str):
    fields = {
        "id": 'id = "x"',
        "commit": 'commit = "abc1234"',
        "versions": 'versions = "<3"',
        "quantities": 'quantities = ["metrics"]',
    }
    fields[change.split(" = ")[0]] = change
    text = 'schema = "hydromodpy.changes.v1"\n[[bug]]\nsince = "2.0.0"\ntext = "d"\n' + "\n".join(
        fields.values()
    )
    with pytest.raises(ValueError, match=fault):
        read(text)


SOURCE_CONFIGS = {
    "a Hub'Eau gauge": (
        '[[data.hydrometry.sources]]\nsource = "hubeau"\n',
        ("source@hydrometry_hubeau",),
    ),
    "two sections, one source twice": (
        '[[data.dem.sources]]\nsource = "file"\npath = "a.tif"\n'
        '[[data.dem.sources]]\nsource = "file"\npath = "b.tif"\n'
        '[[data.hydrometry.sources]]\nsource = "hubeau"\n',
        ("source@dem_file", "source@hydrometry_hubeau"),
    ),
    "no source": ("[data]\ntypes = []\n", ()),
    "no data": ('[simulation]\nname = "x"\n', ()),
}


HUBEAU_BUG = Bug(
    id="hubeau_x",
    since="2.1.0",
    versions="<2.1.0",
    quantities=("source@hydrometry_hubeau",),
    text="Hub'Eau read the wrong series.",
)


LAKE = "[flow.sinks_sources.lakes.pond]\nstage = 1.0\n"
CYCLIC = '[flow.ic.h]\nkind = "spinup_cyclic"\n'


@pytest.mark.parametrize(
    ("config", "tokens"),
    [
        ('[flow]\nrestart_from = "runs/spin"\n', (RESTART_START,)),
        (CYCLIC + LAKE, (CYCLIC_LAKE_START,)),
        (CYCLIC + "[flow.sinks_sources.lakes]\n", ()),
        ('[flow.ic.h]\nkind = "top"\n' + LAKE, ()),
        ("[simulation]\n", ()),
    ],
)
def test_a_start_token_names_only_the_starts_a_fix_moved(config, tokens):
    assert declared_start_tokens(config) == tokens


def _codes(result: LabelResult) -> tuple[str, ...]:
    return tuple(cause.code for cause in result.causes)


STEADY = "steady"
TRANSIENT = "transient"

RULE_3 = {
    "a calibration window": (
        {"score_window": None, "n_samples": 0},
        {"window": CALIBRATION_WINDOW, "cost": 0.4},
        TRANSIENT,
        ("calibrated", ("promoted",)),
    ),
    "the headline window": (
        {},
        {"cost": 0.4},
        TRANSIENT,
        ("calibrated", ("promoted",)),
    ),
    "a steady run with a finite cost": (
        {"score_window": None, "n_samples": 0},
        {"cost": 0.0029},
        STEADY,
        ("calibrated", ("promoted",)),
    ),
    "a steady run without a cost": (
        {"score_window": None, "n_samples": 0},
        {"cost": None},
        STEADY,
        ("exploratory", ("promoted", "no_scored_window")),
    ),
    "a steady run with an infinite cost": (
        {"score_window": None, "n_samples": 0},
        {"cost": float("inf")},
        STEADY,
        ("exploratory", ("promoted", "no_scored_window")),
    ),
    "a transient run promoted without a window": (
        {"score_window": None, "n_samples": 0},
        {"cost": 0.4},
        TRANSIENT,
        ("exploratory", ("promoted", "no_scored_window")),
    ),
    "a regime that was not recorded": (
        {"score_window": None, "n_samples": 0},
        {"cost": 0.4},
        None,
        ("exploratory", ("promoted", "no_scored_window")),
    ),
    "a headline window without a sample": (
        {"n_samples": 0},
        {"cost": 0.4},
        STEADY,
        ("calibrated", ("promoted",)),
    ),
    "a headline window without a sample, transient": (
        {"n_samples": 0},
        {"cost": 0.4},
        TRANSIENT,
        ("exploratory", ("promoted", "no_scored_window")),
    ),
    "a bound reached on a calibrated run": (
        {"bounds_hit": ["K", "Sy"]},
        {"cost": 0.4},
        TRANSIENT,
        ("calibrated", ("promoted", "bound_reached")),
    ),
    "a bound reached on a run that scored nothing": (
        {"score_window": None, "n_samples": 0, "bounds_hit": ["K"]},
        {"cost": 0.4},
        TRANSIENT,
        ("exploratory", ("promoted", "no_scored_window", "bound_reached")),
    ),
    "a bound reached on a failed run": (
        {"converged": False, "bounds_hit": ["K"]},
        {"cost": 0.4},
        STEADY,
        ("failed", ("not_converged", "bound_reached")),
    ),
    "nothing scored and no session": (
        {"score_window": None, "n_samples": 0, "calibrated_by": None},
        None,
        STEADY,
        ("exploratory", ("no_score_window",)),
    ),
}


@pytest.mark.parametrize(
    ("checks", "promoted", "regime", "expected"), RULE_3.values(), ids=RULE_3.keys()
)
def test_rule_3_calibrates_a_promoted_run_only_on_a_scored_window(
    checks, promoted, regime, expected
):
    fields = dict(checks)
    if promoted is not None:
        fields.setdefault("calibrated_by", make_calibrated_by(**promoted))
    result = label_for(
        make_checks(**fields), hydromodpy_version=CURRENT, flow_regime=regime, issues=()
    )
    assert (result.label, _codes(result)) == expected


def test_a_reason_with_an_unknown_code_is_refused():
    with pytest.raises(ValueError, match="no_such_code"):
        Reason.of("no_such_code")


def test_every_reason_code_is_one_a_label_can_give():
    issue = Bug(id="x", since="2.0.0", versions="<3", quantities=("heads@modflow6",), text="d")
    fatal = [Validity("water_budget", False, 12.0, "no", True)]
    cases = [
        (make_checks(validities=fatal), ()),
        (make_checks(converged=False), ()),
        (make_checks(), (issue,)),
        (_promoted("completed", window=CALIBRATION_WINDOW), ()),
        (
            _promoted("completed", window=DateWindow(start=date(2018, 1, 1), end=date(2025, 1, 1))),
            (),
        ),
        (make_checks(score_window=None, n_samples=0, bounds_hit=["K"]), ()),
        (_promoted("partial", score_window=None), ()),
        (_promoted("partial", n_samples=0), ()),
        (Checks(score_window=WINDOW, n_samples=1827), ()),
    ]
    given = {
        cause.code
        for checks, issues in cases
        for cause in label_for(
            checks,
            hydromodpy_version="2.0.0a4",
            quantities=MF6,
            flow_regime=TRANSIENT,
            issues=issues,
        ).causes
    }
    assert given == REASON_CODES
