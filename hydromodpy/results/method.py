"""The method text and the label sentence of a sealed run, in English or in French.

Why
---
A manager or a reviewer reads a run in words, not in a seal. The text has five
paragraphs, always in this order: the run, its data, its calibration, its
quality and its limits. It reads the seal, ``inputs.json`` and the label of the
day, and nothing else. It adds no field to the seal.

Every sentence is a row of ``phrases.toml`` (``[method.*]``, ``[label.*]``,
``[label_reason.*]``, ``[check_state.*]``), read through
:mod:`hydromodpy.schema.phrases`, so the English and the French text come from
one source. A text a run stored itself, a validity message or the text of a bug,
is written as stored, in the language it was written in.

The controls of the quality paragraph have three states: passed, failed and
unknown. The seal already holds all three. ``converged`` and
``code_reproducible`` are ``None`` when nothing is known, a budget with no
threshold or no value is unknown, and a validity has ``passed``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.results.metric_rule import MetricScore, PeriodWindow
from hydromodpy.results.record.checks import BUDGET_RULE, Checks
from hydromodpy.results.record.label import label_of
from hydromodpy.results.record.manifest import InputEntry, RunSeal, read_seal
from hydromodpy.results.record.record import read_inputs
from hydromodpy.results.validity_rules import LabelResult
from hydromodpy.schema.changes import REGISTER
from hydromodpy.schema.phrases import Lang, keys, phrase

_NUMBER = ".4g"


def label_text(result: LabelResult, *, lang: Lang = "en", today: date) -> str:
    """Return the label of *result*, its rule version, the day of the rendering and each reason.

    The label is a function of reading, so the text carries the day it was
    computed. Each reason is a sentence of its own, in *lang*.
    """
    sentences = [
        phrase(
            "method",
            "label",
            lang,
            label=phrase("label", result.label, lang),
            date=today.isoformat(),
            rule_version=result.rule_version,
        )
    ]
    sentences += [_sentence(reason) for reason in result.texts(lang)]
    return " ".join(sentences)


def method_text(run_dir: str | Path, *, lang: Lang = "en", today: date | None = None) -> str:
    """Return the method text of the sealed run at *run_dir*, five paragraphs apart by a blank line.

    *today* is the day written beside the label, the current day by default.

    Raises
    ------
    FileNotFoundError
        When the directory carries no seal, i.e. the run never completed.
    """
    directory = Path(run_dir)
    seal = read_seal(directory)
    entries = read_inputs(directory).inputs
    label = label_of(seal, directory)
    day = datetime.now(UTC).date() if today is None else today
    paragraphs = (
        _run_paragraph(seal, lang),
        _data_paragraph(entries, lang),
        _calibration_paragraph(seal, lang),
        _quality_paragraph(seal.checks, label, lang, day),
        _limits_paragraph(label, lang),
    )
    return "\n\n".join(paragraphs)


def _say(key: str, lang: Lang, **values: object) -> str:
    return phrase("method", key, lang, **values)


def _word(prefix: str, value: str, lang: Lang) -> str:
    """Return the word of a stored value, or the value itself when a newer build wrote it."""
    key = f"{prefix}_{value}"
    return _say(key, lang) if key in keys("method") else value


def _sentence(text: str) -> str:
    """Return *text* as one sentence: first letter up, one full stop at the end."""
    body = text.strip().rstrip(".")
    return f"{body[:1].upper()}{body[1:]}."


def _number(value: float) -> str:
    return format(value, _NUMBER)


def _run_paragraph(seal: RunSeal, lang: Lang) -> str:
    run, geometry, period = seal.run, seal.geometry, seal.period
    sentences = [
        _say(
            "run", lang, name=run.name, solver=run.solver, version=seal.identity.hydromodpy_version
        )
    ]
    if geometry.n_cells is not None:
        engine = geometry.mesh_engine or phrase("check_state", "unknown", lang)
        values = {"engine": engine, "n_cells": geometry.n_cells}
        if geometry.n_layers is None:
            sentences.append(_say("mesh_cells", lang, **values))
        elif geometry.n_layers == 1:
            sentences.append(_say("mesh_one_layer", lang, **values))
        else:
            sentences.append(_say("mesh", lang, n_layers=geometry.n_layers, **values))
    if period.start is None or period.end is None:
        sentences.append(_say("period_steady", lang))
    else:
        bounds = {"start": period.start.date().isoformat(), "end": period.end.date().isoformat()}
        if period.n_timesteps:
            sentences.append(_say("period", lang, n_timesteps=period.n_timesteps, **bounds))
        else:
            sentences.append(_say("period_bounds", lang, **bounds))
    return " ".join(sentences)


def _data_paragraph(entries: Iterable[InputEntry], lang: Lang) -> str:
    sentences = []
    for entry in entries:
        source = " ".join(
            part for part in (entry.provider, entry.product, entry.product_version) if part
        )
        licence = entry.license
        if licence is None or licence == UNDETERMINED_LICENSE:
            sentences.append(
                _say("data_input_unlicensed", lang, variable=entry.variable, source=source)
            )
        else:
            sentences.append(
                _say("data_input", lang, variable=entry.variable, source=source, license=licence)
            )
    return " ".join(sentences) if sentences else _say("data_none", lang)


def _calibration_paragraph(seal: RunSeal, lang: Lang) -> str:
    by = seal.checks.calibrated_by
    if by is None:
        sentences = [_say("calib_none", lang)]
    else:
        sentences = [
            _say(
                "calib_session",
                lang,
                trial=by.trial,
                session_id=by.session_id,
                status=_word("status", by.session_status, lang),
            )
        ]
        if by.phase:
            sentences.append(_say("calib_phase", lang, phase=by.phase))
        sentences.append(_stop_sentence(by.stop_state, by.stopping_rule, lang))
        if by.cost is not None:
            if by.metric:
                sentences.append(_say("calib_cost", lang, metric=by.metric, cost=_number(by.cost)))
            else:
                sentences.append(_say("calib_cost_unnamed", lang, cost=_number(by.cost)))
        if by.validation_cost is not None:
            sentences.append(_say("calib_validation_cost", lang, cost=_number(by.validation_cost)))
        if by.components:
            parts = ", ".join(f"{name} {_number(by.components[name])}" for name in by.components)
            sentences.append(_say("calib_components", lang, components=parts))
        if by.rule:
            sentences.append(_say("calib_rule", lang, rule=by.rule))
        sentences += _window_sentences(by.windows, lang)
        parameters = _calibrated_parameters(seal)
        if parameters:
            sentences.append(_say("calib_parameters", lang, parameters=parameters))
        if seal.checks.bounds_hit:
            sentences.append(_say("calib_bounds", lang, names=", ".join(seal.checks.bounds_hit)))
    sentences += _score_sentences(seal.score, seal.checks.obs_coverage, lang)
    return " ".join(sentences)


def _stop_sentence(state: str | None, rule: str | None, lang: Lang) -> str:
    if state == "budget_spent" and rule == BUDGET_RULE:
        return _say("calib_stop_budget_only", lang)
    if state in ("rule_met", "plan_exhausted", "budget_spent"):
        return _say(f"calib_stop_{state}", lang, rule=rule)
    return _say("calib_stop_unknown", lang)


def _window_sentences(windows: Mapping[str, PeriodWindow], lang: Lang) -> list[str]:
    if not windows:
        return [_say("calib_no_windows", lang)]
    return [
        _say(
            "calib_window",
            lang,
            role=_word("role", period.role, lang),
            name=name,
            start=period.start.isoformat(),
            end=period.end.isoformat(),
        )
        for name, period in windows.items()
    ]


def _calibrated_parameters(seal: RunSeal) -> str:
    parts = []
    for row in seal.parameters:
        if not row.calibrated:
            continue
        name = row.name if row.zone == CATCHMENT else f"{row.name} ({row.zone})"
        if row.value is None:
            parts.append(name)
        else:
            unit = f" {row.unit}" if row.unit else ""
            parts.append(f"{name} = {_number(row.value)}{unit}")
    return ", ".join(parts)


def _score_sentences(score: MetricScore | None, coverage: float | None, lang: Lang) -> list[str]:
    if score is None or score.window_start is None or score.window_end is None:
        return [_say("score_none", lang)]
    window = {"start": score.window_start.isoformat(), "end": score.window_end.isoformat()}
    if score.value is None:
        sentences = [_say("score_unavailable", lang, metric=score.metric, **window)]
    else:
        sentences = [
            _say(
                "score",
                lang,
                metric=score.metric,
                value=_number(score.value),
                n_samples=score.n_samples,
                **window,
            )
        ]
    if coverage is not None:
        sentences.append(_say("score_coverage", lang, share=f"{coverage:.0%}"))
    return sentences


def _quality_paragraph(checks: Checks, label: LabelResult, lang: Lang, today: date) -> str:
    return " ".join([label_text(label, lang=lang, today=today), *_control_sentences(checks, lang)])


def _state(passed: bool | None) -> str:
    """Return the state of a control: ``passed``, ``failed`` or ``unknown``."""
    if passed is None:
        return "unknown"
    return "passed" if passed else "failed"


def _control_sentences(checks: Checks, lang: Lang) -> list[str]:
    """Return one sentence per control, each in one of its three states."""
    budget_ok = (
        None
        if checks.budget_pct is None or checks.budget_threshold_pct is None
        else abs(checks.budget_pct) <= checks.budget_threshold_pct
    )
    budget_detail = None
    if checks.budget_pct is not None:
        pct = _number(checks.budget_pct)
        if checks.budget_threshold_pct is None:
            budget_detail = _say("budget_no_threshold", lang, pct=pct)
        else:
            threshold = _number(checks.budget_threshold_pct)
            budget_detail = _say("budget_detail", lang, pct=pct, threshold=threshold)
    reproducible_detail = (
        _say("reproducible_failed", lang) if checks.code_reproducible is False else None
    )
    controls: list[tuple[str, bool | None, str | None, bool]] = [
        (_say("control_converged", lang), checks.converged, None, False),
        (_say("control_budget", lang), budget_ok, budget_detail, False),
        (_say("control_reproducible", lang), checks.code_reproducible, reproducible_detail, False),
        *[
            (v.name, v.passed, v.message.strip().rstrip(".") or None, v.fatal)
            for v in checks.validities
        ],
    ]
    sentences = []
    for control, passed, detail, fatal in controls:
        state = phrase("check_state", _state(passed), lang)
        if detail:
            sentences.append(
                _say("check_detail", lang, control=control, state=state, detail=detail)
            )
        else:
            sentences.append(_say("check", lang, control=control, state=state))
        if fatal and passed is False:
            sentences.append(_say("check_fatal", lang, control=control))
    return sentences


def _limits_paragraph(label: LabelResult, lang: Lang) -> str:
    if label.label == "failed":
        return _say("limits_unread", lang)
    if not label.known_issues:
        return _say("limits_none", lang)
    bugs = {bug.id: bug for bug in REGISTER.bugs}
    return " ".join(
        _say(
            "limits_issue",
            lang,
            id=issue,
            since=bugs[issue].since,
            text=_sentence(bugs[issue].text),
        )
        for issue in label.known_issues
    )


__all__ = ["label_text", "method_text"]
