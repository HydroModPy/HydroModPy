"""Guard the single-source tolerance policy.

``tests/TOLERANCES.md`` is the one source of truth for numerical tolerances.
``tests/_helpers/tolerances.py::tol`` loads the 22 single-scalar rows from that
table. This test prevents two kinds of drift:

1. A ``tol("...")`` call that points at a typo / dangling key (it would resolve
   to nothing, or ambiguously, and silently break the single-source contract).
2. An INLINE row whose value is hard-coded at its assertion site again, so the
   row could diverge from the table without anyone noticing.

The 22 loadable rows split into three enforcement classes (W5 classification):

* INLINE  - the value is asserted at a validation/regression call site; the
            literal was replaced by ``tol(<slug>)``. Every INLINE row MUST be
            referenced by at least one ``tol()`` call (checked below).
* CASE_TOML - the value is enforced at runtime through ``comparison.tolerances``
            loaded from a per-case ``validation_cases/**/tolerances*.toml``. The
            case-TOML stays the runtime authority for these analytical PDE
            benchmarks; ``tol()`` is intentionally NOT used for them.
* UNUSED  - the documented tolerance is not enforced by any test today.

CASE_TOML and UNUSED rows are an explicit allow-list here so a future reader
sees why they carry no ``tol()`` reference.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._helpers.tolerances import TOLERANCES, tol

_TESTS_ROOT = Path(__file__).resolve().parents[1]

# These two files exercise the tol() machinery itself (including negative-path
# arguments such as a deliberately-unknown key), so their tol() calls are not
# real tolerance references and must be skipped when scanning the suite.
_SCAN_EXCLUDE: frozenset[str] = frozenset(
    {
        "test_tolerances_helper.py",
        "test_tolerances_single_source.py",
        "tolerances.py",
    }
)

# --------------------------------------------------------------------------- #
# W5 classification of the 22 loadable TOLERANCES.md rows.
# --------------------------------------------------------------------------- #

# INLINE: literal replaced by tol(); must be referenced by >= 1 tol() call.
INLINE_ROWS: frozenset[str] = frozenset(
    {
        "theis_confined_pumping_2d__nse_vs_analytical_9_probes",
        "theis_confined_pumping_2d__max_pointwise_relative_drawdown_error",
        "direct_solver_outputs__rtol",
        "reservoir_calibration_validation__recovered_log10_k_and_n_drift_from_truth",
        "regression_goldens_arrays__rtol",
        "regression_goldens_arrays__atol",
        "signature_stats_post_v0_5__rtol",
        "signature_stats_post_v0_5__atol",
        "mf6_prt_uniform_velocity_streamline__max_relative_position_error_x_x_exp_x_exp_x0",
    }
)

# CASE_TOML: enforced via comparison.tolerances from validation_cases/**/*.toml
# (or, for the twin K recovery, via a case-config tolerance object). These keep
# the case store as the runtime authority; tol() is intentionally not used.
CASE_TOML_ROWS: frozenset[str] = frozenset(
    {
        # Dupuit fixed-head head RMSE, per-solver tolerances*.toml head_profile.rmse.
        "dupuit_fixed_head_1d_nwt__head_rmse",
        "dupuit_fixed_head_1d_mf6__head_rmse",
        # Linearized transient cross-row spread, *_modflow6_irregular_tri.toml
        # space_time.row_spread (values match the doc exactly: 0.006/0.006/0.012/
        # 0.005/0.0007).
        "linearized_transient_recharge_step_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_recharge_periodic_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_boundary_piecewise_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_boundary_step_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_recharge_step_deep_1d_mf6_irregular_tri__cross_row_spread",
        # Twin K recovery. The benchmark enforces an ABSOLUTE K_global tolerance
        # (~2.0e-5) in validation_cases/calibration/.../experiment.py
        # parameter_abs_tolerances (case config, out of scope for tests/). The
        # documented row 19 is a RELATIVE 0.05 SNR envelope and is a different
        # metric than what is enforced; see the disagreement test below.
        "twin_calibration_k_recovery__k_k_true_k_true",
    }
)

# UNUSED: documented but not enforced by any test today.
UNUSED_ROWS: frozenset[str] = frozenset(
    {
        # No test asserts max head change per iteration; HCLOSE lives in solver
        # config inputs, not a pass/fail gate.
        "modflow_nwt_mf6_head_convergence__max_head_change_per_iteration",
        # No test gates the global water-budget closure ratio at 1 %.
        "global_water_budget_closure__relative_error_in_out_in",
        # No test asserts the absolute NSE drift vs a calibration baseline.
        "calibration_nse_vs_baseline__absolute_nse_drift",
        # No test references the Marcais 2017 recession-slope benchmark.
        "boussinesq_vs_mar_ais_2017__recession_slope_error",
        # No test enforces a bootstrap CI rtol on metrics.
        "bootstrap_ci_on_metrics__bootstrap_rtol",
    }
)


def _collect_tol_arguments() -> dict[str, list[str]]:
    """Return ``{slug: [file:line, ...]}`` for every ``tol("...")`` string arg.

    Walk every ``*.py`` under ``tests/`` (excluding this guard file's own
    documentation strings does not matter, AST only sees real calls) and pull
    the literal string argument of each ``tol(...)`` call.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        if path.name in _SCAN_EXCLUDE:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_tol = (isinstance(func, ast.Name) and func.id == "tol") or (
                isinstance(func, ast.Attribute) and func.attr == "tol"
            )
            if not is_tol or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.setdefault(first.value, []).append(f"{path}:{node.lineno}")
    return found


def _resolve(slug: str) -> str:
    """Resolve a tol() argument to its canonical key with tol()'s own logic."""
    table = TOLERANCES
    if slug in table:
        return slug
    candidates = [key for key in table if slug in key]
    assert len(candidates) == 1, (
        f"tol({slug!r}) does not resolve to exactly one loadable row: {sorted(candidates)}"
    )
    return candidates[0]


@pytest.mark.fast
def test_classification_partitions_all_loadable_rows() -> None:
    """INLINE, CASE_TOML and UNUSED partition exactly the 22 loadable rows."""
    classified = INLINE_ROWS | CASE_TOML_ROWS | UNUSED_ROWS
    loadable = set(TOLERANCES)
    assert len(loadable) == 22, sorted(loadable)
    missing = loadable - classified
    extra = classified - loadable
    assert not missing, f"loadable rows with no classification: {sorted(missing)}"
    assert not extra, f"classified keys that are not loadable rows: {sorted(extra)}"
    # The three classes must not overlap.
    assert not (INLINE_ROWS & CASE_TOML_ROWS)
    assert not (INLINE_ROWS & UNUSED_ROWS)
    assert not (CASE_TOML_ROWS & UNUSED_ROWS)


@pytest.mark.fast
def test_every_tol_call_resolves_to_one_real_row() -> None:
    """No dangling / typo / ambiguous tol() argument anywhere in tests/."""
    calls = _collect_tol_arguments()
    assert calls, "expected at least one tol() call across the test suite"
    for slug, sites in calls.items():
        try:
            _resolve(slug)
        except (AssertionError, KeyError) as exc:
            raise AssertionError(f"tol({slug!r}) used at {sites} is invalid: {exc}") from exc


@pytest.mark.fast
def test_referenced_rows_are_subset_of_loadable_keys() -> None:
    """Every row reached through tol() is one of the 22 loadable keys."""
    referenced = {_resolve(slug) for slug in _collect_tol_arguments()}
    assert referenced <= set(TOLERANCES), sorted(referenced - set(TOLERANCES))


@pytest.mark.fast
def test_every_inline_row_is_referenced_by_a_tol_call() -> None:
    """No INLINE row can drift: each must be anchored by >= 1 tol() call."""
    referenced = {_resolve(slug) for slug in _collect_tol_arguments()}
    missing = INLINE_ROWS - referenced
    assert not missing, f"INLINE rows not referenced by any tol() call: {sorted(missing)}"


@pytest.mark.fast
def test_known_case_toml_vs_doc_disagreement_is_documented() -> None:
    """Flag the one CASE_TOML doc-vs-TOML disagreement so it stays visible.

    TOLERANCES.md row 12 documents the Dupuit MF6 head RMSE as ``0.02 m`` but the
    enforced case-TOML value (validation_cases/.../dupuit_fixed_head_1d/
    tolerances_modflow6.toml ``head_profile.rmse``) is ``2e-4`` (100x tighter).
    The NWT row 11 (0.05) agrees with its case-TOML. Neither value is changed by
    W5; this assertion records the documented mismatch so a silent edit to either
    store surfaces here.
    """
    doc_mf6 = tol("dupuit_fixed_head_1d_mf6__head_rmse")
    doc_nwt = tol("dupuit_fixed_head_1d_nwt__head_rmse")
    assert doc_mf6 == pytest.approx(0.02)
    assert doc_nwt == pytest.approx(0.05)

    case_root = (
        _TESTS_ROOT.parent / "validation_cases" / "analytical" / "steady" / "dupuit_fixed_head_1d"
    )
    mf6_toml = (case_root / "tolerances_modflow6.toml").read_text(encoding="utf-8")
    nwt_toml = (case_root / "tolerances.toml").read_text(encoding="utf-8")
    # Enforced MF6 head_profile.rmse is tighter than the documented 0.02.
    assert "rmse = 2e-4" in mf6_toml, "dupuit MF6 case-TOML rmse changed; revisit row 12"
    # Enforced NWT head_profile.rmse agrees with the documented 0.05.
    assert "rmse = 0.05" in nwt_toml, "dupuit NWT case-TOML rmse changed; revisit row 11"
