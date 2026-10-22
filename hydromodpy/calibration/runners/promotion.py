"""Promotion of calibration trials to runs, and what a session leaves on disk.

The best trial of the last phase becomes ``runs/<case>/``, the calibrated run
of the case, in the directory paired with the session (same version number).
The other trials ``save_runs`` keeps become ``sessions/<case>/trials/<n>/``,
each in the form of a run. With ``promote_phases`` the best trial of each
earlier phase becomes ``sessions/<case>/phases/<phase>/best/``. A promotion
happens once per phase, after the last restart.

A promoted trial whose solve the session kept is not solved again: the run
goes on from extraction on the kept solver folder. A trial with no kept
solve is replayed, and the log says why, once per run. Each promoted run is
linked back by ids: the journal line of the trial receives the ``sim_id`` and
the ``rel_dir`` of the run, and the run's seal names the session, the phase
and the trial.

A reopened session (``--resume``, ``--phase``) promotes once more at its end.
A trial whose journal line already names the directory it would take is not
written again. The paired run directory is never overwritten: when it holds
another trial of the session, the new best is not written, the failure says
so, and ``hmp project promote <case> --trial N`` writes it under the next
version of the case.

``hmp project promote <case> --trial N`` replays a trial after the fact from
``sessions/<case>/config.toml`` and the frozen values of its phase, after
checking its fingerprint; a trial already kept under ``trials/<n>/`` is
moved. ``hmp project prune <case> --keep best`` trashes the other kept trials.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.persistence import SPECULATIVE_UNUSED, CalibrationPersistence
from hydromodpy.calibration.runners.trial import promote_prepared_trial
from hydromodpy.core import progress
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    TRIALS_DIRNAME,
    run_dir_rel,
    session_dir_rel,
    trial_dir_rel,
)
from hydromodpy.results.catalog.registration import (
    VersionPairingError,
    reserve_version_dirname,
    split_stem_version,
)
from hydromodpy.results.checks import CalibratedBy, CalibrationSessionStatus
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.session.descriptor import (
    BestTrial,
    SessionDescriptor,
    read_session,
    resolve_session_dir,
)
from hydromodpy.results.session.journal import TrialLine, trial_row
from hydromodpy.results.session.phase import phase_dir
from hydromodpy.results.storage.run_facts import CalibratedParameter, PromotionFacts
from hydromodpy.results.trash import trash_run

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.parameters import ParameterSpace
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)

PHASE_BEST_DIRNAME = "best"
"""Directory of the promoted best trial of a phase, under ``phases/<phase>/``."""


@dataclass(frozen=True)
class PromotionOutcome:
    """What a promotion wrote: how many runs, which failed, and the calibrated run.

    ``best_sim_id`` and ``best_rel_dir`` name the calibrated run of the case,
    written by this promotion or already there from an earlier one; ``count``
    counts the runs written now.
    """

    count: int = 0
    failures: list[str] = field(default_factory=list)
    best_sim_id: str | None = None
    best_rel_dir: str | None = None


def stored_parameter_value(raw: Any) -> float:
    """Return the physical candidate value from a journaled parameter payload."""
    if isinstance(raw, dict):
        for key in ("value", "candidate_value", "transformed_value"):
            if key in raw:
                return float(raw[key])
        raise KeyError("Journaled parameter payload has no value")
    return float(raw)


def select_trials_to_promote(
    cfg: CalibrationConfig, persistence: CalibrationPersistence, phase: str
) -> list[dict[str, Any]]:
    """Return the trial rows of ``phase`` that ``cfg.save_runs`` promotes, best first."""
    if cfg.save_runs == "best_n":
        return persistence.top_n(cfg.save_best_n, phase)
    if cfg.save_runs == "all":
        rows = [
            row
            for row in persistence.load_iterations(phase)
            if row["status"] == "completed" and row["objective_value"] is not None
        ]
        # The first row becomes runs/<case>: a speculative trial, solved and
        # never read by the search, may be kept but never ahead of the best.
        return sorted(
            rows,
            key=lambda row: (
                bool((row["metrics"] or {}).get(SPECULATIVE_UNUSED)),
                row["objective_value"],
                row["iteration"],
            ),
        )
    return []


def promotion_name_check(name: str) -> None:
    """Refuse a case name too long for a run directory, before the search."""
    from hydromodpy.results.catalog.storage_paths import MAX_DIRNAME_LEN

    longest = len(name) + len(".v99")
    if longest > MAX_DIRNAME_LEN:
        raise CalibrationError(
            f"The calibrated run of this case would be named {name!r} plus a version, "
            f"{longest} characters where a run folder holds {MAX_DIRNAME_LEN}. Shorten the "
            "file name or the [simulation] name."
        )


NO_CATALOG_NO_RUN = (
    "no run is written: [simulation.results.persistence] save_catalog is false, so a "
    "promoted run has no directory to hold it. Set save_catalog = true, or "
    'save_runs = "none" to keep only the journal of the search.'
)
"""Why a promotion writes nothing when the project does not persist its runs."""


def _writes_runs(trial_ctx: TrialContext) -> bool:
    """Say whether a promoted run of this session is written to disk at all."""
    return bool(trial_ctx.base_cfg.simulation.results.persistence.save_catalog)


def _values_of(row: Mapping[str, Any], override_paths: Mapping[str, str]) -> dict[str, float]:
    return {
        name: stored_parameter_value(row["parameters"][name])
        for name in override_paths
        if name in row["parameters"]
    }


def promote_session(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    persistence: CalibrationPersistence,
    project_root: Path,
    phase: str,
    session_status: CalibrationSessionStatus,
    override_paths: Mapping[str, str],
) -> PromotionOutcome:
    """Promote the trials of the last phase and return what was written.

    The best trial takes ``runs/<case>/``, paired with the session, keeps the
    project's ``keep_per_cell_budget`` and carries ``checks.calibrated_by``
    and the facts of :func:`promotion_facts`. Every other kept trial takes
    ``sessions/<case>/trials/<n>/`` with the ``consumers`` budget policy.
    """
    rows = select_trials_to_promote(cfg, persistence, phase)
    if not rows:
        return PromotionOutcome()
    return _promote_rows(
        rows,
        trial_ctx=trial_ctx,
        persistence=persistence,
        project_root=project_root,
        phase=phase,
        session_status=session_status,
        override_paths=override_paths,
    )


def promote_best_after_abort(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    persistence: CalibrationPersistence,
    project_root: Path,
    phase: str,
    override_paths: Mapping[str, str],
) -> PromotionOutcome:
    """Promote the best trial of ``phase`` after an interruption, from its kept solve alone.

    The session is closed ``aborted`` already; the run says so in
    ``checks.calibrated_by``. A best trial whose solve was not kept would have
    to be solved again, which the margin after a signal does not allow: it is
    left to ``hmp project promote <case> --trial N``, and the log says so.
    """
    best = persistence.best_trial(phase)
    if best is None or trial_ctx is None or cfg.save_runs == "none":
        return PromotionOutcome()
    retention = trial_ctx.kept_solves
    kept, why_not = (
        retention.take(best.trial)
        if retention is not None
        else (None, "the session keeps no solve")
    )
    if kept is None:
        logger.info(
            "Trial %d of phase %s is not promoted after the interruption: %s. "
            "hmp project promote %s --trial %d replays it.",
            best.trial,
            phase,
            why_not,
            split_stem_version(persistence.directory.name)[0],
            best.trial,
        )
        return PromotionOutcome()
    return _promote_rows(
        [trial_row(best)],
        trial_ctx=trial_ctx,
        persistence=persistence,
        project_root=project_root,
        phase=phase,
        session_status="aborted",
        override_paths=override_paths,
    )


def _promote_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    trial_ctx: TrialContext,
    persistence: CalibrationPersistence,
    project_root: Path,
    phase: str,
    session_status: CalibrationSessionStatus,
    override_paths: Mapping[str, str],
) -> PromotionOutcome:
    """Promote ``rows``, the first one as the calibrated run of the case."""
    if not _writes_runs(trial_ctx):
        logger.warning("%s", NO_CATALOG_NO_RUN)
        return PromotionOutcome(failures=[NO_CATALOG_NO_RUN])
    session_dir = persistence.directory
    descriptor = persistence.descriptor
    session_id = descriptor.session_id
    stem = split_stem_version(session_dir.name)[0]
    best_number = int(rows[0]["iteration"])
    failures: list[str] = []
    count = 0
    best_sim_id: str | None = None
    best_rel_dir: str | None = None
    for row in progress.track(rows, "Promoting calibrated runs"):
        number = int(row["iteration"])
        is_best = number == best_number
        rel_dir = (
            run_dir_rel(session_dir.name) if is_best else trial_dir_rel(session_dir.name, number)
        )
        written = _already_written(persistence, number, rel_dir, project_root)
        if written is not None:
            logger.info("Trial %d already became %s; it is not written again.", number, rel_dir)
            if is_best:
                best_sim_id, best_rel_dir = written.sim_id, rel_dir
            continue
        if is_best:
            run_dir = _reserve_paired_run(project_root, session_dir, persistence, number, failures)
            if run_dir is None:
                continue
            calibrated_by = CalibratedBy(
                session_id=session_id,
                phase=phase,
                trial=number,
                session_status=session_status,
                window=descriptor.objective_window,
            )
            promotion = promotion_facts(descriptor, row)
            kind = "promoted"
        else:
            run_dir = project_root / rel_dir
            run_dir.mkdir(parents=True, exist_ok=True)
            calibrated_by = None
            promotion = None
            kind = "trial"
        lineage = Lineage(
            session_id=session_id,
            phase=phase,
            trial=number,
            kind=kind,
            parent_hint=session_dir_rel(session_dir.name),
        )
        sim_id = _promote_one(
            trial_ctx,
            row,
            override_paths=override_paths,
            run_dir=run_dir,
            name=stem,
            lineage=lineage,
            calibrated_by=calibrated_by,
            promotion=promotion,
            keep_per_cell_budget=None if is_best else False,
            retention=trial_ctx.kept_solves,
            failures=failures,
        )
        if sim_id is None:
            continue
        count += 1
        persistence.link_trial(number, sim_id=sim_id, rel_dir=rel_dir)
        if is_best:
            best_sim_id, best_rel_dir = sim_id, rel_dir
    return PromotionOutcome(
        count=count, failures=failures, best_sim_id=best_sim_id, best_rel_dir=best_rel_dir
    )


BOUND_TOLERANCE = 1e-6
"""Share of the searched range within which a value counts as on its bound."""


def promotion_facts(descriptor: SessionDescriptor, row: Mapping[str, Any]) -> PromotionFacts:
    """Return what the session says about the run its trial ``row`` becomes.

    The objective of the session, its value for the trial and the window it
    was scored on; the convergence of the trial solve (a trial completes only
    once its solve terminated normally); the parameters whose value ended on
    a bound of the searched range; and the parameters the trial set, named as
    the parameter rows of the run name them.
    """
    parameters = row.get("parameters") or {}
    return PromotionFacts(
        objective_name=descriptor.objective_name,
        objective_value=row.get("objective_value"),
        objective_window=descriptor.objective_window,
        converged=row.get("status") == "completed",
        bounds_hit=sorted(name for name, payload in parameters.items() if _on_bound(payload)),
        calibrated=[_calibrated_parameter(name, payload) for name, payload in parameters.items()],
    )


def _on_bound(payload: Any) -> bool:
    """Whether a journaled parameter ended on a bound of its searched range.

    Read in the space the search moved in (``transformed_*``), where the
    range is the one the optimizer saw; a bare value carries no bounds.
    """
    if not isinstance(payload, Mapping):
        return False
    value, bounds = payload.get("transformed_value"), payload.get("transformed_bounds")
    if value is None or not bounds:
        value, bounds = payload.get("value"), payload.get("bounds")
    if value is None or not bounds or len(bounds) != 2:
        return False
    lower, upper = float(bounds[0]), float(bounds[1])
    margin = BOUND_TOLERANCE * abs(upper - lower)
    return abs(float(value) - lower) <= margin or abs(float(value) - upper) <= margin


def _calibrated_parameter(name: str, payload: Any) -> CalibratedParameter:
    """Return the parameter rows a journaled parameter set.

    A target ``flow.param.<P>...`` sets the rows of ``<P>``, only the zone
    after ``values_by_key`` when it names one. Any other target sets the
    rows named by its last segment, and a parameter without target the rows
    of its own name.
    """
    target = payload.get("target") if isinstance(payload, Mapping) else None
    if not target:
        return CalibratedParameter(name=str(name))
    parts = str(target).split(".")
    if len(parts) >= 3 and parts[:2] == ["flow", "param"]:
        zone = None
        if "values_by_key" in parts:
            position = parts.index("values_by_key") + 1
            zone = parts[position] if position < len(parts) else None
        return CalibratedParameter(name=parts[2], zone=zone)
    return CalibratedParameter(name=parts[-1])


def _already_written(
    persistence: CalibrationPersistence, number: int, rel_dir: str, project_root: Path
) -> TrialLine | None:
    """Return the journal line of a trial that already became the run at ``rel_dir``."""
    line = next((item for item in persistence.trials() if item.trial == number), None)
    if line is None or line.sim_id is None or line.rel_dir != rel_dir:
        return None
    return line if (project_root / rel_dir).is_dir() else None


def _reserve_paired_run(
    project_root: Path,
    session_dir: Path,
    persistence: CalibrationPersistence,
    number: int,
    failures: list[str],
) -> Path | None:
    """Reserve the run directory paired with the session, or say why it cannot be.

    The paired directory is never overwritten. When it is taken, by another
    trial of a reopened session or by anything else, the best trial is not
    written and the failure names the way out.
    """
    rel_dir = run_dir_rel(session_dir.name)
    stem = split_stem_version(session_dir.name)[0]
    try:
        return reserve_version_dirname(project_root, "run", stem, pair_with=session_dir)
    except VersionPairingError:
        holder = next(
            (item.trial for item in persistence.trials() if item.rel_dir == rel_dir),
            None,
        )
        held_by = f"trial {holder} of this session" if holder is not None else "another run"
        failures.append(
            f"trial {number}: {rel_dir} already holds {held_by} and is not overwritten; "
            f"hmp project promote {stem} --trial {number} writes it under the next version."
        )
        return None


def promote_phase_best(
    *,
    trial_ctx: TrialContext,
    persistence: CalibrationPersistence,
    phase: str,
    override_paths: Mapping[str, str],
) -> str | None:
    """Promote the best trial of an earlier phase under ``phases/<phase>/best/``.

    The run keeps the ``consumers`` budget policy: the permanent model of a
    phase is read, not analysed term by term. Returns its ``sim_id``, or None
    when the phase scored nothing or the promotion failed.
    """
    best = persistence.best_trial(phase)
    if best is None:
        return None
    if not _writes_runs(trial_ctx):
        logger.warning("Phase %s: %s", phase, NO_CATALOG_NO_RUN)
        return None
    session_dir = persistence.directory
    run_dir = phase_dir(session_dir, phase) / PHASE_BEST_DIRNAME
    run_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    sim_id = _promote_one(
        trial_ctx,
        trial_row(best),
        override_paths=override_paths,
        run_dir=run_dir,
        name=f"{split_stem_version(session_dir.name)[0]}_{phase}",
        lineage=Lineage(
            session_id=persistence.descriptor.session_id,
            phase=phase,
            trial=best.trial,
            kind="promoted",
            parent_hint=session_dir_rel(session_dir.name),
        ),
        calibrated_by=None,
        promotion=None,
        keep_per_cell_budget=False,
        retention=trial_ctx.kept_solves,
        failures=failures,
    )
    if sim_id is not None:
        persistence.link_trial(best.trial, sim_id=sim_id, rel_dir=None)
    for failure in failures:
        logger.error("Promotion of the best trial of phase %s failed: %s", phase, failure)
    return sim_id


def _promote_one(
    trial_ctx: TrialContext,
    row: Mapping[str, Any],
    *,
    override_paths: Mapping[str, str],
    run_dir: Path,
    name: str,
    lineage: Lineage,
    calibrated_by: CalibratedBy | None,
    promotion: PromotionFacts | None,
    keep_per_cell_budget: bool | None,
    retention: Any,
    failures: list[str],
) -> str | None:
    """Promote one trial row into ``run_dir``; append to ``failures`` and return None on error."""
    number = int(row["iteration"])
    values = _values_of(row, override_paths)
    kept, why_not = (
        retention.take(number) if retention is not None else (None, "this session keeps no solve")
    )
    if kept is None:
        logger.info("Promoting %s by solving trial %d again: %s.", run_dir.name, number, why_not)
    spared = retention.spared_folders(number) if retention is not None else ()
    sim_id = str(uuid.uuid4())
    try:
        with progress.suppressed():
            promote_prepared_trial(
                trial_ctx,
                values,
                name=name,
                sim_id=sim_id,
                run_dir=run_dir,
                lineage=lineage,
                calibrated_by=calibrated_by,
                promotion=promotion,
                kept=kept,
                spared=spared,
                keep_per_cell_budget=keep_per_cell_budget,
            )
    except Exception as exc:
        logger.exception("Promotion failed for trial %d.", number)
        failures.append(f"trial {number}: {exc}")
        return None
    if kept is not None and retention is not None:
        retention.promoted(number)
    return sim_id


# ---------------------------------------------------------------------------
# After the fact: hmp project promote, hmp project prune
# ---------------------------------------------------------------------------


def promote_trial_from_session(
    project_root: Path,
    case: str,
    trial: int,
    *,
    as_name: str | None = None,
) -> Path:
    """Promote trial ``trial`` of the session of ``case`` to ``runs/<as_name or case>/``.

    Without ``as_name`` the run takes ``runs/<case>`` paired with the
    session when that directory is free, else the next version of the case;
    with it, the next version of ``as_name``. A trial already kept under
    ``trials/<n>/`` is moved, in one rename, onto the directory reserved for
    it; its seal is the one it was written with, a trial of the session
    (``lineage.kind = "trial"``, no ``calibrated_by``). Any other trial is
    replayed from ``sessions/<case>/config.toml`` with the values of its
    journal line, on the model its phase scored it under
    (:func:`replay_context`), after its fingerprint (``params_hash``) is
    reproduced, and sealed as a promoted run. The journal line receives the
    ``sim_id`` and the new ``rel_dir`` either way.
    """
    from hydromodpy.calibration.optim.cache import params_hash
    from hydromodpy.calibration.runners.resume import physical_values
    from hydromodpy.calibration.runners.state import build_cache_context, override_paths
    from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME

    session_dir = resolve_session_dir(project_root, case)
    persistence = CalibrationPersistence(session_dir)
    line = next((item for item in persistence.trials() if item.trial == int(trial)), None)
    if line is None:
        raise CalibrationError(f"session {session_dir.name} journals no trial {trial}.")
    if line.status != "completed":
        raise CalibrationError(
            f"trial {trial} of {session_dir.name} is {line.status}, not completed."
        )
    stem = as_name or split_stem_version(session_dir.name)[0]
    kept_dir = project_root / trial_dir_rel(session_dir.name, int(trial))
    if kept_dir.is_dir():
        target = _reserve_after_the_fact(project_root, session_dir, as_name)
        # The reserved directory is empty: one rename moves the kept trial onto
        # it, and the claim its mkdir made is never released in between.
        os.replace(kept_dir, target)
        rel_dir = run_dir_rel(target.name)
        persistence.link_trial(int(trial), sim_id=line.sim_id, rel_dir=rel_dir)
        _point_best_if_better(persistence, line, rel_dir)
        return target

    hash_cfg, space, trial_ctx = replay_context(
        session_dir / SESSION_CONFIG_FILENAME, persistence, line
    )
    if not _writes_runs(trial_ctx):
        raise CalibrationError(f"trial {trial} is not promoted: {NO_CATALOG_NO_RUN}")
    values = physical_values(line.params)
    context = build_cache_context(
        cfg=hash_cfg,
        trial_ctx=trial_ctx,
        space=space,
        override_paths=override_paths(hash_cfg),
        objective_entrypoint=None,
    )
    moved = {name: values[name] for name in space.names if name in values}
    if line.params_hash is not None and params_hash(moved, context=context) != line.params_hash:
        raise CalibrationError(
            f"trial {trial} of {session_dir.name} was scored on another model: its "
            "params_hash is not reproduced by the configuration, the mesh or the input "
            "files read today. Nothing is replayed."
        )
    run_dir = _reserve_after_the_fact(project_root, session_dir, as_name)
    sim_id = str(uuid.uuid4())
    descriptor = read_session(session_dir)
    status: CalibrationSessionStatus = (
        descriptor.status if descriptor.status in ("completed", "partial", "aborted") else "partial"
    )
    promote_prepared_trial(
        trial_ctx,
        moved,
        name=stem,
        sim_id=sim_id,
        run_dir=run_dir,
        promotion=promotion_facts(descriptor, trial_row(line)),
        lineage=Lineage(
            session_id=descriptor.session_id,
            phase=line.phase,
            trial=line.trial,
            kind="promoted",
            parent_hint=session_dir_rel(session_dir.name),
        ),
        calibrated_by=CalibratedBy(
            session_id=descriptor.session_id,
            phase=line.phase,
            trial=line.trial,
            session_status=status,
            window=descriptor.objective_window,
        ),
    )
    rel_dir = run_dir_rel(run_dir.name)
    persistence.link_trial(int(trial), sim_id=sim_id, rel_dir=rel_dir)
    _point_best_if_better(persistence, line.model_copy(update={"sim_id": sim_id}), rel_dir)
    return run_dir


def replay_context(
    config_path: Path, persistence: CalibrationPersistence, line: TrialLine
) -> tuple[CalibrationConfig, ParameterSpace, TrialContext]:
    """Return the model trial ``line`` was scored under, rebuilt from *config_path*.

    Three parts: the calibration configuration its ``params_hash`` reads,
    the parameters it moved, and the prepared trial pipeline. A trial of a
    staged session is rebuilt on its phase (:func:`replay_phase`): the phase
    configuration, its overrides and the values the phase held fixed. A
    restart of a multistart search ran under its own seed, ``seed + restart``.
    """
    from hydromodpy.calibration.runners.cli_runner import _with_its_method, load_toml_calibration
    from hydromodpy.calibration.runners.staged_runner import replay_phase
    from hydromodpy.calibration.runners.state import override_paths, space_from_config
    from hydromodpy.calibration.runners.trial import prepare_trials

    cfg, raw = load_toml_calibration(config_path)
    if cfg.phases:
        phase = persistence.phase(line.phase)
        frozen = (phase.frozen if phase is not None else None) or {}
        replay = replay_phase(cfg, raw, config_path, line.phase, frozen)
        hash_cfg, space, trial_ctx = replay.config, replay.space, replay.trial_ctx
    else:
        hash_cfg = _with_its_method(cfg)
        space = space_from_config(cfg)
        trial_ctx = prepare_trials(
            config_path, override_paths=override_paths(cfg), parameter_space=space
        )
    if line.restart > 0 and getattr(hash_cfg.uncertainty, "method", None) == "multistart":
        hash_cfg = hash_cfg.model_copy(update={"seed": (hash_cfg.seed or 0) + line.restart})
    return hash_cfg, space, trial_ctx


def _reserve_after_the_fact(project_root: Path, session_dir: Path, as_name: str | None) -> Path:
    """Reserve the run directory of an after-the-fact promotion.

    The directory paired with the session when no name is asked and it is
    free; the next version of the case, or of ``as_name``, otherwise.
    """
    if as_name is not None:
        return reserve_version_dirname(project_root, "run", as_name)
    stem = split_stem_version(session_dir.name)[0]
    if not (project_root / run_dir_rel(session_dir.name)).exists():
        return reserve_version_dirname(project_root, "run", stem, pair_with=session_dir)
    return reserve_version_dirname(project_root, "run", stem)


def _point_best_if_better(
    persistence: CalibrationPersistence, line: TrialLine, rel_dir: str
) -> None:
    """Point ``session.json`` at the promoted trial when it is the best of the session."""
    best = persistence.best_trial()
    if best is not None and best.trial == line.trial:
        persistence.set_best(
            BestTrial(
                trial=line.trial, sim_id=line.sim_id, rel_dir=rel_dir, objective=line.objective
            )
        )


def prune_session(
    project_root: Path,
    case: str,
    *,
    keep: str = "best",
    now: datetime | None = None,
) -> list[Path]:
    """Trash the kept trials of a session, all but the best, and return what moved."""
    if keep != "best":
        raise CalibrationError(f"keep={keep!r}: the only policy is 'best'.")
    session_dir = resolve_session_dir(project_root, case)
    descriptor = read_session(session_dir)
    best = descriptor.best.trial if descriptor.best is not None else None
    trials_root = session_dir / TRIALS_DIRNAME
    if not trials_root.is_dir():
        return []
    moved: list[Path] = []
    stamp = now or datetime.now(UTC)
    for entry in sorted(trials_root.iterdir()):
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        number = int(entry.name)
        if number == best:
            continue
        moved.append(trash_run(project_root, trial_dir_rel(session_dir.name, number), now=stamp))
    return moved


__all__ = [
    "PHASE_BEST_DIRNAME",
    "PromotionOutcome",
    "promote_best_after_abort",
    "promote_phase_best",
    "promote_session",
    "promote_trial_from_session",
    "promotion_facts",
    "promotion_name_check",
    "prune_session",
    "replay_context",
    "select_trials_to_promote",
    "stored_parameter_value",
]
