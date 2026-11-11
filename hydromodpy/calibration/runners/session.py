"""Where a calibration session lives, and how its case is named.

A calibration occupies two sibling directories of one name: ``sessions/<case>``
for what the search evaluated and ``runs/<case>`` for the promoted run. The
case is named by the stem of the file that carries ``[calibration]``, unless
that file writes ``[simulation] name`` itself; a name inherited through
``base_config`` never names a calibration. The session reserves its version
first (``reserve_version_dirname``), the promoted run takes the same one.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tomllib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.config_terms import window_bounds
from hydromodpy.core.state.names import fold_name
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.metric_rule import CALIBRATION_ROLE, VALIDATION_ROLE, PeriodWindow
from hydromodpy.results.session.descriptor import ParameterBound, latest_session_dir
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.parameters import ParameterSpace
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext


def calibration_case_name(cfg_path: Path) -> str:
    """Return the name of the case a calibration file declares.

    The file that carries ``[calibration]`` is found along the ``base_config``
    chain, starting at ``cfg_path``. Its own ``[simulation] name`` wins when it
    writes one; otherwise its stem, folded into the letters of a name, is the case.
    """
    carrier = _carrier_of_calibration(Path(cfg_path).expanduser().resolve())
    return case_named_by(_own_document(carrier), carrier.stem)


def case_named_by(document: Mapping[str, Any], stem: str) -> str:
    """Return the case a document names: its ``[simulation] name``, else *stem* folded.

    A file goes through :func:`calibration_case_name`, from the CLI or from a project
    built on it. Only a project with no file names its case from its configuration.
    A name the document writes is kept as written, and the session refuses it when
    it breaks the rule of a name. The stem is a name the code makes, so it is
    folded into the letters of a name, as the run of the same file is.
    """
    simulation = document.get("simulation")
    name = simulation.get("name") if isinstance(simulation, Mapping) else None
    return name.strip() if isinstance(name, str) and name.strip() else fold_name(stem)


def _own_document(path: Path) -> dict[str, Any]:
    """Return the keys one file writes itself, without its base_config chain."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _carrier_of_calibration(path: Path) -> Path:
    """Return the first file of the base_config chain that writes ``[calibration]``."""
    current = path
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        own = _own_document(current)
        if "calibration" in own:
            return current
        base = own.get("base_config")
        if not isinstance(base, str) or not base:
            break
        candidate = Path(base).expanduser()
        current = (candidate if candidate.is_absolute() else current.parent / candidate).resolve()
        if not current.is_file():
            break
    return path


def project_root_for(cfg_path: Path, workspace: Path | str | None) -> Path:
    """Return the project root a calibration file runs in."""
    if workspace is not None:
        return Path(workspace).expanduser().resolve()
    return resolve_project_root(Path(cfg_path).expanduser().resolve().parent)


def open_session_dir(project_root: Path, case: str, *, resume: bool) -> tuple[Path, bool]:
    """Return the session directory of a case, and whether it is reopened.

    A new session reserves the next version. ``resume`` reopens the latest
    existing session of the case instead, and reserves a new one when there is
    none to reopen.
    """
    if resume:
        existing = latest_session_dir(project_root, case)
        if existing is not None:
            return existing, True
    return reserve_version_dirname(project_root, "session", case), False


def freeze_session_config(
    session_dir: Path, raw: Mapping[str, Any], cfg: CalibrationConfig | None = None
) -> Path:
    """Write the resolved document of the case as ``sessions/<case>/config.toml``.

    *cfg* is the calibration the search reads, its geometry paths already
    anchored to the file of the case. Each one is written relative to the
    session directory, so the frozen document finds the same file from where
    it sits: a promotion after the fact reads it and must hash the same
    model as the search did.
    """
    from hydromodpy.calibration.runners.materialize import write_overlay_toml

    target = Path(session_dir) / SESSION_CONFIG_FILENAME
    payload = {key: value for key, value in dict(raw).items() if key != "base_config"}
    if cfg is not None:
        payload = _with_anchored_geometry(payload, cfg, Path(session_dir))
    write_overlay_toml(target, payload)
    return target


def _with_anchored_geometry(
    payload: dict[str, Any], cfg: CalibrationConfig, session_dir: Path
) -> dict[str, Any]:
    """Return *payload* with each found geometry path written relative to *session_dir*."""
    calibration = payload.get("calibration")
    outputs = calibration.get("outputs") if isinstance(calibration, Mapping) else None
    if not isinstance(outputs, Mapping):
        return payload
    anchored = copy.deepcopy(payload)
    base = session_dir.expanduser().resolve()
    for name, role, resolved in cfg.map_files():
        written = anchored["calibration"]["outputs"].get(name, {}).get("map")
        if isinstance(written, dict) and role in written and resolved.is_absolute():
            written[role] = os.path.relpath(resolved, base)
    return anchored


def session_config_hash(raw: Mapping[str, Any], trial_ctx: TrialContext | None) -> str:
    """Return the solution key of the resolved case the session calibrates.

    The key a run records, with the search kept: the request of the case, the
    digests of its inputs, the code, the solver binaries and the numeric packages.
    A plan and a calibration compare a key to a key, never a request id to one. A
    session with no prepared model (an evaluator that runs no HydroModPy model)
    hashes the document it read.
    """
    from hydromodpy.calibration.runners.trial import trial_pipeline

    if trial_ctx is not None and hasattr(trial_ctx.base_cfg, "model_dump"):
        key = trial_pipeline().session_key(trial_ctx.base_cfg)
        if key is not None:
            return key
    return hashlib.sha256(json.dumps(dict(raw), sort_keys=True, default=str).encode()).hexdigest()


def search_windows(
    cfg: CalibrationConfig,
    document: Mapping[str, Any] | None = None,
    *,
    phase: CalibPhaseDecl | None = None,
) -> dict[str, PeriodWindow]:
    """Return the periods a search scores on, by name; empty when no date closes one.

    A staged calibration promotes the best trial of its last phase, so without
    ``phase`` the period is the one of that phase, or the section's when the phase
    writes none. A bound left open is the start or the end of the period that
    ``[simulation.time]`` of *document* declares. Empty when a bound stays unknown:
    a steady phase that writes no window of its own. The validation window comes
    second, on a search it is scored on.
    """
    last = phase if phase is not None else (cfg.phases[-1] if cfg.phases else None)
    window = cfg.window
    if last is not None and last.window is not None:
        window = last.window
    elif last is not None and last.regime == "steady":
        return {}
    bounds = window_bounds(window) or (None, None)
    period_start, period_end = _declared_period(document)
    start = bounds[0].date() if bounds[0] is not None else period_start
    end = bounds[1].date() if bounds[1] is not None else period_end
    if start is None or end is None:
        return {}
    windows = {CALIBRATION_ROLE: PeriodWindow(role=CALIBRATION_ROLE, start=start, end=end)}
    if cfg.validation_scored_by(last):
        first_day, last_day = window_bounds(cfg.validation_window)
        windows[VALIDATION_ROLE] = PeriodWindow(
            role=VALIDATION_ROLE, start=first_day.date(), end=last_day.date()
        )
    return windows


def _declared_period(document: Mapping[str, Any] | None) -> tuple[date | None, date | None]:
    """Return the first and last day ``[simulation.time]`` of *document* declares."""
    simulation = document.get("simulation") if isinstance(document, Mapping) else None
    time = simulation.get("time") if isinstance(simulation, Mapping) else None
    if not isinstance(time, Mapping):
        return None, None
    return _day(time.get("start_datetime")), _day(time.get("end_datetime"))


def _day(value: Any) -> date | None:
    """Return the day of a TOML date, datetime or ISO string, or None."""
    import pandas as pd

    if value is None or value == "":
        return None
    return pd.Timestamp(value).date()


def session_bounds(space: ParameterSpace, case_id: str) -> dict[str, ParameterBound]:
    """Return the dimensions a search walks, each target under the case it touches."""
    return {
        param.name: ParameterBound(
            lower=param.lower,
            upper=param.upper,
            search_space=param.search_space,
            units=param.units,
            targets={case_id: param.effective_path} if param.effective_path else {},
        )
        for param in space
    }


def report_of_session(directory: Path, *, project_root: Path) -> CalibrationReport:
    """Return the report of the completed session in *directory*, read from the disk.

    A calibration identical to a completed session is given back by this report
    instead of searching again. Every field comes from ``session.json``, the count
    of trials from ``trials.jsonl``; nothing ran, so the duration is 0 and nothing
    was promoted. ``extra["identical_to"]`` names the session folder.
    """
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.results.session.descriptor import read_session
    from hydromodpy.results.session.journal import read_trials

    folder = Path(directory)
    descriptor = read_session(folder)
    best = descriptor.best
    return CalibrationReport(
        session_id=descriptor.session_id,
        method=descriptor.method,
        n_trials=len({line.trial for line in read_trials(folder)}),
        best_cost=None if best is None else best.cost,
        duration_s=0.0,
        save_runs="none",
        promoted=0,
        status=descriptor.status,
        cost_name=descriptor.cost_name,
        cost_label=descriptor.cost_label,
        best_trial=None if best is None else best.trial,
        best_parameters=None if best is None else dict(best.parameters),
        best_cases={} if best is None else dict(best.cases),
        windows=dict(descriptor.windows),
        workspace=Path(project_root),
        session_dir=folder,
        extra={"identical_to": folder.name},
    )


__all__ = [
    "calibration_case_name",
    "freeze_session_config",
    "open_session_dir",
    "project_root_for",
    "report_of_session",
    "search_windows",
    "session_bounds",
    "session_config_hash",
]
