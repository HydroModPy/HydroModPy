"""The ``README.md`` of a run, a session or a summary, rendered from the seal.

Why
---
A reader who receives a directory alone, or who opens a project six months
later, needs one text that says what the thing is: the basin, the outlet, the
period (or that there is none), the version, whether the code was
reproducible, the checks, the label of the day and its rules, the score and
its window, and where each file is. The text is derived: it is rendered from
the sealed files and can be rendered again. Its footer gives the digest of
the manifest it summarises, so a reader can tell which seal a README belongs
to. It never names a host, a user or an absolute path.

Format
------
Markdown, one section per topic, a footer ``sha256(manifest.json) = <hex>``.

A run that did not complete has no manifest, so no record and no footer:
:func:`render_unsealed_run_readme` renders its README from ``outcome.json``
alone, with the error and the end of the log.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pyproj import Transformer

from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.results.checks import Checks, stop_line, stop_text
from hydromodpy.results.ledger import sha256_of
from hydromodpy.results.manifest import ManifestSite
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.outcome import Outcome
from hydromodpy.results.record import RunRecord
from hydromodpy.results.session.descriptor import SessionDescriptor
from hydromodpy.results.session.journal import TrialLine
from hydromodpy.results.session.phase import PhaseDescriptor
from hydromodpy.results.storage.contract import (
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_EXPORTS_DIRNAME,
    RUN_FIGURES_DIRNAME,
    RUN_INPUTS_FILENAME,
    RUN_LOGS_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_REPORT_DIRNAME,
    RUN_RESOLVED_CONFIG_FILENAME,
    SESSION_CONFIG_FILENAME,
    SESSION_DESCRIPTOR_FILENAME,
    SESSION_PHASES_DIRNAME,
    SESSION_TRIALS_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.validity_rules import LabelResult


@dataclass(frozen=True, slots=True)
class SummaryFacts:
    """What ``summary/README.md`` says about a collected project."""

    project: str
    n_planned: int
    n_completed: int
    sites: tuple[str, ...]
    versions: tuple[str, ...]
    collected_at: datetime
    period: DateWindow | None
    label_date: date
    rule_version: str
    best: str
    """``[sites.summary] best``: ``calibrated`` or ``any``."""
    catalog_written: bool
    """Whether the collect wrote ``catalog.csv``."""


def manifest_sha256(run_dir: str | Path) -> str:
    """Return the digest of the manifest of a run directory."""
    return sha256_of(Path(run_dir) / RUN_MANIFEST_FILENAME)


def write_readme(directory: str | Path, text: str) -> Path:
    """Write the README atomically and return its path."""
    target = Path(directory) / README_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with staged_path(target) as staged:
        staged.write_text(text, encoding="utf-8")
    return target


def render_run_readme(
    record: RunRecord,
    outcome: Outcome | None,
    label: LabelResult,
    *,
    manifest_sha256: str,
) -> str:
    """Return the README of a sealed run."""
    run = record.run
    lines = [
        f"# {run.case_id}",
        "",
        f"Run `{run.name}` of project `{run.project}`, sim_id `{run.sim_id}`, "
        f"attempt {run.attempt}, status **{run.status}**.",
        "",
    ]
    lines += _site_section(record.site)
    lines += _period_section(record)
    lines += [
        "## Version",
        "",
        f"- HydroModPy {record.identity.hydromodpy_version}, solver `{run.solver}`"
        + (f", mesh engine `{record.geometry.mesh_engine}`" if record.geometry.mesh_engine else ""),
        f"- code reproducible: {_yes_no(record.checks.code_reproducible)}",
        f"- configuration hash: `{record.config.hash or 'none'}`",
        "",
    ]
    lines += _checks_section(record.checks)
    lines += _label_section(label)
    lines += _score_section(record)
    lines += _lineage_section(record)
    if outcome is not None:
        lines += _outcome_section(outcome)
    lines += [
        "## Where is what",
        "",
        f"- `{RUN_CONFIG_FILENAME}`: what the run was given, replayable; "
        f"`{RUN_RESOLVED_CONFIG_FILENAME}`: the same with every default",
        f"- `{RUN_MANIFEST_FILENAME}`: the seal; `{RUN_PROVENANCE_FILENAME}`: the environment; "
        f"`{RUN_INPUTS_FILENAME}`: the inputs",
        f"- `{TABLES_DIRNAME}/`: tables (pyarrow); `fields.zarr/`: fields (zarr)",
        f"- `{RUN_FIGURES_DIRNAME}/`, `{RUN_EXPORTS_DIRNAME}/`, `{RUN_REPORT_DIRNAME}/`: "
        "derived, each with its ledger; "
        f"`{RUN_LOGS_DIRNAME}/`: diagnostics",
        "",
        "---",
        f"sha256({RUN_MANIFEST_FILENAME}) = {manifest_sha256}",
        "",
    ]
    return "\n".join(lines)


def render_unsealed_run_readme(outcome: Outcome) -> str:
    """Return the README of a run that did not complete, from its outcome alone."""
    lines = [
        f"# {outcome.case_id}",
        "",
        f"Case `{outcome.case_id}`"
        + (f" of project `{outcome.project}`" if outcome.project else "")
        + (f", site `{outcome.site}`" if outcome.site else "")
        + f", attempt {outcome.attempt}, status **{outcome.status}**. "
        f"No `{RUN_MANIFEST_FILENAME}`: this run did not complete and carries no seal.",
        "",
    ]
    lines += _outcome_section(outcome)
    if outcome.step:
        lines[-1:-1] = [f"- last step reached: `{outcome.step}`"]
    if outcome.log_tail:
        lines += ["## End of the log", "", "```", *outcome.log_tail, "```", ""]
    lines += [
        "## Where is what",
        "",
        f"- `{RUN_CONFIG_FILENAME}`: the resolved configuration, replayable",
        f"- `{RUN_LOGS_DIRNAME}/`: diagnostics; `{TABLES_DIRNAME}/`: the tables written before the end",
        "",
    ]
    return "\n".join(lines)


def render_session_readme(
    descriptor: SessionDescriptor,
    trials: Sequence[TrialLine],
    label: LabelResult | None,
    *,
    phases: Sequence[PhaseDescriptor] = (),
    manifest_sha256: str | None = None,
) -> str:
    """Return the README of a calibration session."""
    lines = [
        f"# Calibration {descriptor.case_id}",
        "",
        f"Session `{descriptor.session_id}` of site `{descriptor.site or 'unnamed'}`, "
        f"method `{descriptor.method}`, objective `{descriptor.objective_name}`, "
        f"status **{descriptor.status}**.",
        "",
        f"- started {descriptor.started_at.isoformat()}"
        + (f", ended {descriptor.ended_at.isoformat()}" if descriptor.ended_at else ""),
        f"- HydroModPy {descriptor.hydromodpy_version}, configuration hash "
        f"`{descriptor.config_hash}` (`{SESSION_CONFIG_FILENAME}`)",
        f"- {len(trials)} trials in `{SESSION_TRIALS_FILENAME}`",
        f"- search stopped: {stop_line(descriptor.stop_state, descriptor.stopping_rule)}",
    ]
    if descriptor.stop_note:
        lines.append(f"- {descriptor.stop_note}")
    lines.append("")
    if descriptor.error_message:
        lines += [f"Error: {descriptor.error_message}", ""]
    if descriptor.search_space:
        lines += ["## Search space", ""]
        lines += [f"- `{name}`: {spec}" for name, spec in descriptor.search_space.items()]
        lines.append("")
    if phases:
        lines += [
            "## Phases",
            "",
            "| phase | status | restarts | frozen | best trial | stopped |",
            "|---|---|---|---|---|---|",
        ]
        for phase in phases:
            best = "none" if phase.best is None else str(phase.best.trial)
            stopped = stop_text(phase.stop_state, phase.stopping_rule)
            if phase.stop_note:
                stopped += f"; {phase.stop_note}"
            lines.append(
                f"| {phase.name} | {phase.status} | {phase.restarts} | {phase.frozen or '{}'} "
                f"| {best} | {stopped} |"
            )
        lines.append("")
    lines += ["## Best trial", ""]
    best = descriptor.best
    if best is None:
        lines.append("No trial retained.")
    else:
        lines.append(f"- trial {best.trial}, objective {_number(best.objective)}")
        if best.rel_dir or best.sim_id:
            lines.append(
                f"- calibrated run: `{best.rel_dir or 'not promoted'}` (sim_id `{best.sim_id or 'none'}`)"
            )
    lines.append("")
    if label is not None:
        lines += _label_section(label)
    lines += [
        "## Where is what",
        "",
        f"- `{SESSION_DESCRIPTOR_FILENAME}`: this session; `{SESSION_PHASES_DIRNAME}/<phase>/"
        f"{SESSION_DESCRIPTOR_FILENAME}`: each phase",
        f"- `{SESSION_TRIALS_FILENAME}`: one trial per line, numbered once across phases",
        "",
    ]
    if manifest_sha256 is not None:
        lines += ["---", f"sha256({RUN_MANIFEST_FILENAME}) = {manifest_sha256}", ""]
    return "\n".join(lines)


def render_summary_readme(facts: SummaryFacts, *, digests: Mapping[str, str]) -> str:
    """Return the README of a collected ``summary/``; *digests* name the files it summarises."""
    period = (
        "no common period"
        if facts.period is None
        else f"{facts.period.start} to {facts.period.end}"
    )
    lines = [
        f"# Summary of {facts.project}",
        "",
        f"Collected {facts.collected_at.isoformat()}: {facts.n_completed} completed of "
        f"{facts.n_planned} planned cases, {len(facts.sites)} sites, {period}.",
        "",
        f"- HydroModPy versions met: {', '.join(facts.versions) or 'none'}",
        f"- labels computed on {facts.label_date} under rules {facts.rule_version}",
        "",
        "## How to read",
        "",
        "- `by_case.*`: one row per case: status, label, checks, parameters, overrides, "
        "score and window",
        f"- `by_site.*`: one row per site: {_best_words(facts.best)}, or in `best_reason` why "
        "it has none; `by_site.gpkg` is the map",
    ]
    if facts.catalog_written:
        lines.append("- `catalog.csv`: the sites as a table, replayable as an input")
    lines += [
        "- `figures/`, `exports/`, `report/`: derived, each with its ledger",
        "",
        "## Sites",
        "",
    ]
    lines += [f"- {site}" for site in facts.sites] or ["- none"]
    lines += ["", "---"]
    lines += [f"sha256({name}) = {digest}" for name, digest in digests.items()]
    lines.append("")
    return "\n".join(lines)


def _best_words(best: str) -> str:
    """Return what the best case of a site is, under ``[sites.summary] best``."""
    if best == "calibrated":
        return "the best calibrated case"
    return 'the best case whatever its label (best = "any")'


def _site_section(site: ManifestSite | None) -> list[str]:
    if site is None:
        return ["## Site", "", "No site declared.", ""]
    lines = ["## Site", "", f"- `{site.name}`" + (f": {site.label}" if site.label else "")]
    if site.gauge:
        lines.append(f"- gauge `{site.gauge}`" + (f", {site.uri}" if site.uri else ""))
    if site.x_outlet is not None and site.y_outlet is not None:
        lines.append(
            f"- outlet x = {site.x_outlet:.1f}, y = {site.y_outlet:.1f} ({site.crs or 'crs unknown'})"
        )
        if site.crs:
            lon, lat = _to_wgs84(site.crs, site.x_outlet, site.y_outlet)
            lines.append(f"- outlet WGS84: lon {lon:.5f}, lat {lat:.5f}")
    if site.area_km2 is not None:
        lines.append(f"- area {site.area_km2:.2f} km2")
    if site.dem_resolution_m is not None:
        lines.append(f"- DEM resolution {site.dem_resolution_m:g} m")
    lines.append(f"- fingerprint `{site.fingerprint}`")
    lines.append("")
    return lines


def _period_section(record: RunRecord) -> list[str]:
    period = record.period
    lines = ["## Period", ""]
    if period.start is None or period.end is None:
        lines.append("Steady state, no period.")
    else:
        steps = (
            f", {period.n_timesteps} {period.time_unit or 'steps'}" if period.n_timesteps else ""
        )
        lines.append(f"{period.start.date()} to {period.end.date()}{steps}.")
    lines.append("")
    return lines


def _checks_section(checks: Checks) -> list[str]:
    lines = ["## Checks", ""]
    if checks.budget_pct is not None:
        threshold = (
            f" (accepted up to {checks.budget_threshold_pct:g} %)"
            if checks.budget_threshold_pct is not None
            else " (no threshold declared)"
        )
        lines.append(f"- water budget {checks.budget_pct:g} %{threshold}")
    lines.append(f"- converged: {_yes_no(checks.converged)}")
    if checks.score_window is not None:
        coverage = (
            f", observations cover {checks.obs_coverage:.0%}"
            if checks.obs_coverage is not None
            else ""
        )
        lines.append(
            f"- scored on {checks.score_window.start} to {checks.score_window.end}"
            f" with {checks.n_samples or 0} samples{coverage}"
        )
    by = checks.calibrated_by
    if by is not None:
        lines.append(
            f"- promoted by session `{by.session_id}` (phase {by.phase or 'none'}, "
            f"trial {by.trial}, session {by.session_status})"
        )
        if by.stop_state is not None:
            lines.append(f"- its search {stop_line(by.stop_state, by.stopping_rule)}")
    for validity in checks.validities:
        verdict = "passed" if validity.passed else ("FAILED, fatal" if validity.fatal else "failed")
        lines.append(f"- {validity.name}: {verdict}. {validity.message}")
    if checks.bounds_hit:
        lines.append(f"- parameters on a bound: {', '.join(checks.bounds_hit)}")
    lines.append("")
    return lines


def _label_section(label: LabelResult) -> list[str]:
    lines = ["## Label", "", f"**{label.label}** under rules {label.rule_version}."]
    lines += [f"- {reason}" for reason in label.reasons]
    if label.known_issues:
        lines.append(f"- known issues: {', '.join(label.known_issues)}")
    lines.append("")
    return lines


def _score_section(record: RunRecord) -> list[str]:
    score = record.score
    lines = ["## Score", ""]
    if score is None or score.nse_window_start is None:
        lines.append("No window declared: no score.")
    else:
        lines.append(
            f"NSE {_number(score.value)} on {score.nse_window_start} to {score.nse_window_end}, "
            f"{score.nse_n} samples, rule {score.metric_rule_version}."
        )
    lines.append("")
    return lines


def _lineage_section(record: RunRecord) -> list[str]:
    lineage = record.lineage
    facts = []
    if lineage.kind:
        facts.append(
            f"- {lineage.kind}" + (f" of `{lineage.parent_hint}`" if lineage.parent_hint else "")
        )
    if lineage.parent_sim_id:
        facts.append(f"- parent sim_id `{lineage.parent_sim_id}`")
    if lineage.session_id:
        facts.append(
            f"- session `{lineage.session_id}`, phase {lineage.phase or 'none'}, trial {lineage.trial}"
        )
    if lineage.overrides:
        facts.append(
            "- overrides: " + ", ".join(f"`{k}` = {v}" for k, v in lineage.overrides.items())
        )
    if not facts:
        return []
    return ["## Lineage", "", *facts, ""]


def _outcome_section(outcome: Outcome) -> list[str]:
    lines = [
        "## Outcome",
        "",
        f"- attempt {outcome.attempt} {outcome.status}, started {outcome.started_at.isoformat()}"
        + (f", ended {outcome.ended_at.isoformat()}" if outcome.ended_at else ""),
    ]
    if outcome.exit_code is not None:
        lines.append(
            f"- exit code {outcome.exit_code}"
            + (f", signal {outcome.signal}" if outcome.signal else "")
        )
    if outcome.error is not None:
        lines.append(f"- {outcome.error.type}: {outcome.error.message}")
    lines.append("")
    return lines


def _to_wgs84(crs: str, x: float, y: float) -> tuple[float, float]:
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x, y)
    return float(lon), float(lat)


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _number(value: float | None) -> str:
    return "none" if value is None else f"{value:.4g}"


__all__ = [
    "SummaryFacts",
    "manifest_sha256",
    "render_run_readme",
    "render_session_readme",
    "render_summary_readme",
    "render_unsealed_run_readme",
    "write_readme",
]
