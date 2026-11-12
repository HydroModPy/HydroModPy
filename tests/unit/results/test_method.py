"""The method text and the label sentence of a run, in English and in French, from a synthetic seal."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.results import method
from hydromodpy.results.method import method_text
from hydromodpy.results.metric_rule import DateWindow, PeriodWindow
from hydromodpy.results.record.checks import CalibratedBy, Validity
from hydromodpy.results.record.manifest import InputEntry, ManifestGeometry, ManifestPeriod
from hydromodpy.schema.phrases import keys
from tests._helpers.metric_rows import headline_score
from tests._helpers.run_records import (
    MESH_HASH,
    NOW,
    make_calibrated_by,
    make_checks,
    make_identity,
    make_record,
)

TODAY = date(2026, 11, 11)
WINDOW = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))
CALIBRATION = PeriodWindow(role="calibration", start=date(2016, 1, 1), end=date(2018, 12, 31))
VALIDATION = PeriodWindow(role="validation", start=date(2019, 1, 1), end=date(2020, 12, 31))


def _by(**fields: Any) -> CalibratedBy:
    payload: dict[str, Any] = {
        "session_id": "sess0001",
        "phase": "transient_sy",
        "trial": 7,
        "session_status": "completed",
        "stop_state": "rule_met",
        "stopping_rule": "sigma",
        "metric": "nse",
        "cost": 0.84,
        "validation_cost": 0.6125,
        "rule": "nse_log",
        "components": {"nse": 0.5, "kge": 0.34},
        "windows": {"calage": CALIBRATION, "valid": VALIDATION},
    }
    payload.update(fields)
    return CalibratedBy(**payload)


def _geometry(**fields: Any) -> ManifestGeometry:
    return ManifestGeometry(mesh_hash=MESH_HASH, **fields)


def _write(tmp_path: Path, **overrides: Any) -> Path:
    make_record(**overrides).write(tmp_path)
    return tmp_path


def _paragraphs(tmp_path: Path, lang: str = "en", **overrides: Any) -> list[str]:
    run_dir = _write(tmp_path, **overrides)
    return method_text(run_dir, lang=lang, today=TODAY).split("\n\n")


CALIBRATED_BY_LANG = {
    "en": [
        "The run J0014010-base.v2 was computed with the modflow6 solver, using HydroModPy 2.0.0a5.",
        "Its voronoi mesh has 4148 cells in one layer.",
        "It covers 2016-01-01 to 2020-12-31 in 1827 time steps.",
        "The input discharge comes from hubeau hydrometrie, under the licence etalab-2.0.",
        "It was promoted by trial 7 of session sess0001 (final status: completed).",
        "The search ran in the phase transient_sy.",
        "The search converged: it met its own rule, sigma.",
        "Its nse cost at that trial is 0.84.",
        "On the validation period it costs 0.6125.",
        "The cost has these components: nse 0.5, kge 0.34.",
        "The rule of that cost is nse_log.",
        "The calibration period calage runs from 2016-01-01 to 2018-12-31.",
        "The validation period valid runs from 2019-01-01 to 2020-12-31.",
        "The calibration set these parameters: K = 6.1e-06 m/s.",
        "Its headline score is nse 0.81 on 2016-01-01 to 2020-12-31, from 1827 samples.",
        "The observations cover 97% of that window.",
        "This run is labelled calibrated on 2026-11-11, under the validity rules",
        "No known issue of the register touches this run.",
    ],
    "fr": [
        "Le run J0014010-base.v2 a été calculé avec le solveur modflow6, par HydroModPy 2.0.0a5.",
        "Son maillage voronoi compte 4148 mailles sur une couche.",
        "Il couvre du 2016-01-01 au 2020-12-31 en 1827 pas de temps.",
        "L'entrée discharge vient de hubeau hydrometrie, sous la licence etalab-2.0.",
        "Il a été promu par l'essai 7 de la session sess0001 (état final : terminé).",
        "La recherche a tourné dans la phase transient_sy.",
        "La recherche a convergé : elle a atteint sa propre règle, sigma.",
        "Son coût nse à cet essai vaut 0.84.",
        "Sur la période de validation il coûte 0.6125.",
        "Le coût a pour composantes : nse 0.5, kge 0.34.",
        "La règle de ce coût est nse_log.",
        "La période de calage calage va du 2016-01-01 au 2018-12-31.",
        "La période de validation valid va du 2019-01-01 au 2020-12-31.",
        "Le calage a posé ces paramètres : K = 6.1e-06 m/s.",
        "Son score de tête est nse 0.81 du 2016-01-01 au 2020-12-31, sur 1827 échantillons.",
        "Les observations couvrent 97% de cette fenêtre.",
        "Ce run est étiqueté calibré au 2026-11-11, selon les règles de validité",
        "Aucun bogue connu du registre ne touche ce run.",
    ],
}


# lang, overrides, sentence written in the quality paragraph
CONTROLS = [
    ("en", {"converged": True}, "solver convergence: passed."),
    ("en", {"converged": None}, "solver convergence: unknown."),
    ("en", {"converged": False}, "solver convergence: failed."),
    (
        "en",
        {"budget_pct": 0.8, "budget_threshold_pct": 2.0},
        "water budget: passed, the discrepancy is 0.8 % and 2 % is accepted.",
    ),
    (
        "en",
        {"budget_pct": -3.0, "budget_threshold_pct": 2.0},
        "water budget: failed, the discrepancy is -3 % and 2 % is accepted.",
    ),
    (
        "en",
        {"budget_pct": 0.8, "budget_threshold_pct": None},
        "water budget: unknown, the discrepancy is 0.8 % and no threshold was declared.",
    ),
    ("en", {"budget_pct": None, "budget_threshold_pct": None}, "water budget: unknown."),
    ("en", {"code_reproducible": True}, "reproducible code: passed."),
    ("en", {"code_reproducible": None}, "reproducible code: unknown."),
    (
        "en",
        {"code_reproducible": False},
        "reproducible code: failed, the code came from a modified checkout or an editable install.",
    ),
    (
        "en",
        {"validities": [Validity("snap", True, 1.0, "no cell was moved.")]},
        "snap: passed, no cell was moved.",
    ),
    (
        "en",
        {"validities": [Validity("snap", False, 9.0, "nine cells were moved")]},
        "snap: failed, nine cells were moved.",
    ),
    ("fr", {"converged": True}, "convergence du solveur : réussi."),
    ("fr", {"converged": None}, "convergence du solveur : inconnu."),
    ("fr", {"converged": False}, "convergence du solveur : échoué."),
    (
        "fr",
        {"budget_pct": 0.8, "budget_threshold_pct": 2.0},
        "bilan hydrique : réussi, l'écart est de 0.8 % et 2 % sont acceptés.",
    ),
    (
        "fr",
        {"budget_pct": 0.8, "budget_threshold_pct": None},
        "bilan hydrique : inconnu, l'écart est de 0.8 % et aucun seuil n'a été déclaré.",
    ),
    ("fr", {"code_reproducible": None}, "code reproductible : inconnu."),
]


@pytest.mark.parametrize(("lang", "facts", "expected"), CONTROLS)
def test_control_sentences(tmp_path: Path, lang: str, facts: dict[str, Any], expected: str) -> None:
    checks = make_checks(**facts)
    quality = _paragraphs(tmp_path, lang, checks=checks)[3]
    assert expected in quality


def test_fatal_failure(tmp_path: Path) -> None:
    checks = make_checks(
        validities=[Validity("water_budget", False, 40.0, "the budget is off", True)]
    )
    quality = _paragraphs(tmp_path, "en", checks=checks)[3]
    assert "This run is labelled failed on 2026-11-11" in quality
    assert "Fatal validity failed: water_budget." in quality
    assert "water_budget: failed, the budget is off." in quality
    assert "The failure of water_budget is fatal" in quality


def test_known_issue(tmp_path: Path) -> None:
    identity = make_identity(hydromodpy_version="2.0.0a0")
    limits = _paragraphs(tmp_path, "en", identity=identity)[4]
    assert limits.startswith("Known issue ")
    assert "Known issue discharge_scores_before_period_alignment, fixed in 2.0.0: " in limits
    assert limits.endswith(".")
    quality = _paragraphs(tmp_path / "again", "fr", identity=identity)[3]
    assert "Ce run est étiqueté exploratoire" in quality
    assert "Le bogue connu discharge_scores_before_period_alignment touche 2.0.0a0" in quality


LICENCES = [
    (
        "en",
        "etalab-2.0",
        "The input discharge comes from hubeau hydrometrie, under the licence etalab-2.0.",
    ),
    (
        "en",
        None,
        "The input discharge comes from hubeau hydrometrie, and no licence is stated for it.",
    ),
    (
        "en",
        "LicenseRef-undetermined",
        "The input discharge comes from hubeau hydrometrie, and no licence is stated for it.",
    ),
    (
        "fr",
        None,
        "L'entrée discharge vient de hubeau hydrometrie, et aucune licence n'est indiquée pour elle.",
    ),
]


@pytest.mark.parametrize(("lang", "licence", "expected"), LICENCES)
def test_input_licence_sentence(
    tmp_path: Path, lang: str, licence: str | None, expected: str
) -> None:
    entry = InputEntry(
        variable="discharge",
        provider="hubeau",
        product="hydrometrie",
        path="data/hydrometry/J0014010.parquet",
        sha256="cd" * 32,
        license=licence,
    )
    assert _paragraphs(tmp_path, lang, inputs=[entry])[1] == expected


RUNS = [
    (
        {"geometry": _geometry(n_cells=120, n_layers=3, mesh_engine="regular")},
        "Its regular mesh has 120 cells in 3 layers.",
    ),
    ({"geometry": _geometry(n_cells=120)}, "Its unknown mesh has 120 cells."),
    ({"period": ManifestPeriod(start=NOW, end=NOW)}, "It covers 2026-10-15 to 2026-10-15."),
    ({"period": ManifestPeriod()}, "It is a steady state, with no period."),
]


@pytest.mark.parametrize(("overrides", "expected"), RUNS)
def test_run_paragraph(tmp_path: Path, overrides: dict[str, Any], expected: str) -> None:
    assert expected in _paragraphs(tmp_path, "en", **overrides)[0]


def test_mesh_without_cells(tmp_path: Path) -> None:
    run = _paragraphs(tmp_path, "en", geometry=_geometry())[0]
    assert "mesh" not in run


STOPS = [
    ("rule_met", "sigma", "The search converged: it met its own rule, sigma."),
    (
        "plan_exhausted",
        "grid 27",
        "The search converged: it solved every point of its plan, grid 27.",
    ),
    (
        "budget_spent",
        "sigma",
        "The search did not converge: it spent its budget before its rule, sigma, was met.",
    ),
    (
        "budget_spent",
        "budget",
        "The search did not converge: it has a budget and no rule of its own, and it spent the budget.",
    ),
    (None, None, "The way the search stopped is not recorded."),
]


@pytest.mark.parametrize(("state", "rule", "expected"), STOPS)
def test_why_the_search_stopped(
    tmp_path: Path, state: str | None, rule: str | None, expected: str
) -> None:
    checks = make_checks(calibrated_by=_by(stop_state=state, stopping_rule=rule))
    assert expected in _paragraphs(tmp_path, "en", checks=checks)[2]


def test_sparse_search(
    tmp_path: Path,
) -> None:
    by = make_calibrated_by(
        session_status="aborted", metric=None, cost=0.5, phase=None, validation_cost=None
    )
    calibration = _paragraphs(tmp_path, "en", checks=make_checks(calibrated_by=by))[2]
    assert calibration.startswith(
        "It was promoted by trial 3 of session s (final status: aborted). "
    )
    assert "Its cost at that trial is 0.5." in calibration
    assert "The search did not record its periods." in calibration
    for absent in ("phase", "validation period", "components", "The rule of that cost"):
        assert absent not in calibration


def test_bounds_and_period_roles(tmp_path: Path) -> None:
    windows = {
        "a": CALIBRATION,
        "b": VALIDATION,
        "c": PeriodWindow(role="evaluation", start=date(2021, 1, 1), end=date(2021, 12, 31)),
    }
    checks = make_checks(calibrated_by=_by(windows=windows), bounds_hit=["K", "Sy"])
    en = _paragraphs(tmp_path / "en", "en", checks=checks)[2]
    assert "The evaluation period c runs from 2021-01-01 to 2021-12-31." in en
    assert "Parameters on a bound: K, Sy. The best value of each may lie outside" in en
    fr = _paragraphs(tmp_path / "fr", "fr", checks=checks)[2]
    assert "La période d'évaluation" not in fr
    assert "La période de évaluation c va du 2021-01-01 au 2021-12-31." in fr
    assert "Paramètres en butée : K, Sy." in fr
    # the label keeps a bound as a reason, in the language asked
    assert (
        "A parameter reached its bound: K, Sy."
        in _paragraphs(tmp_path / "q", "en", checks=checks)[3]
    )


def test_run_without_session(tmp_path: Path) -> None:
    checks = make_checks(calibrated_by=None)
    calibration = _paragraphs(tmp_path, "en", checks=checks)[2]
    assert calibration.startswith(
        "No calibration session promoted this run, so its parameters are the ones its "
        "configuration declares."
    )
    assert "calibration set these parameters" not in calibration


SCORES = [
    ({"score": None, "metrics": []}, "No score is recorded for this run."),
    (
        {"score": headline_score(None, n_samples=0, metric_rule_version="1", window=WINDOW)},
        "Its headline score nse could not be computed on 2016-01-01 to 2020-12-31.",
    ),
]


@pytest.mark.parametrize(("overrides", "expected"), SCORES)
def test_missing_or_empty_score(tmp_path: Path, overrides: dict[str, Any], expected: str) -> None:
    assert expected in _paragraphs(tmp_path, "en", **overrides)[2]


def test_directory_without_seal(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        method_text(tmp_path)


def test_every_sentence_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    used: set[str] = set()
    real = method.phrase

    def spy(table: str, key: str, lang: str, **values: object) -> str:
        if table == "method":
            used.add(key)
        return real(table, key, lang, **values)

    monkeypatch.setattr(method, "phrase", spy)
    windows = {
        "a": CALIBRATION,
        "b": VALIDATION,
        "c": PeriodWindow(role="evaluation", start=date(2021, 1, 1), end=date(2021, 12, 31)),
    }
    unlicensed = InputEntry(
        variable="v", provider="p", path="data/p", sha256="ab" * 32, license=None
    )
    scenarios: list[dict[str, Any]] = [
        {"checks": make_checks(calibrated_by=_by(windows=windows), bounds_hit=["K"])},
        {"checks": make_checks(calibrated_by=None, code_reproducible=None, budget_pct=None)},
        {
            "checks": make_checks(
                calibrated_by=make_calibrated_by(
                    status="partial", stop_state="plan_exhausted", metric=None, cost=0.5
                ),
                budget_threshold_pct=None,
                validities=[Validity("v", False, 1.0, "bad", True)],
            )
        },
        {
            "checks": make_checks(
                calibrated_by=_by(session_status="aborted", stop_state="budget_spent")
            )
        },
        {
            "checks": make_checks(
                calibrated_by=_by(stop_state="budget_spent", stopping_rule="budget")
            )
        },
        {"checks": make_checks(calibrated_by=_by(stop_state=None))},
        {"checks": make_checks(converged=False)},
        {"identity": make_identity(hydromodpy_version="2.0.0a0")},
        {"inputs": [], "score": None, "metrics": [], "period": ManifestPeriod()},
        {
            "inputs": [unlicensed],
            "geometry": _geometry(n_cells=5, n_layers=2, mesh_engine="a"),
        },
        {"geometry": _geometry(n_cells=5), "period": ManifestPeriod(start=NOW, end=NOW)},
        {"score": headline_score(None, n_samples=0, metric_rule_version="1", window=WINDOW)},
    ]
    for number, overrides in enumerate(scenarios):
        for lang in ("en", "fr"):
            _paragraphs(tmp_path / f"{number}-{lang}", lang, **overrides)
    assert keys("method") - used == frozenset()
