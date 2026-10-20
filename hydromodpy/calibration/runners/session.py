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

from hydromodpy.calibration.config import CalibrationConfig, scoring_window_bounds
from hydromodpy.core.state.paths import resolve_project_root
from hydromodpy.results.catalog.registration import (
    input_file_digests,
    reserve_version_dirname,
    run_identity_hash,
    split_stem_version,
)
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.session.descriptor import list_session_dirs
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.parameters import ParameterSpace
    from hydromodpy.calibration.runners.trial import TrialContext


def calibration_case_name(cfg_path: Path) -> str:
    """Return the name of the case a calibration file declares.

    The file that carries ``[calibration]`` is found along the ``base_config``
    chain, starting at ``cfg_path``. Its own ``[simulation] name`` wins when it
    writes one; otherwise its stem is the case.
    """
    carrier = _carrier_of_calibration(Path(cfg_path).expanduser().resolve())
    own = _own_document(carrier)
    simulation = own.get("simulation")
    name = simulation.get("name") if isinstance(simulation, Mapping) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return carrier.stem


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


def latest_session_dir(project_root: Path, case: str) -> Path | None:
    """Return the highest version of ``sessions/<case>`` that holds a descriptor, or None."""
    found: list[tuple[int, Path]] = []
    for entry in list_session_dirs(project_root):
        stem, version = split_stem_version(entry.name)
        if stem == case:
            found.append((1 if version is None else version, entry))
    if not found:
        return None
    return max(found)[1]


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


GEOMETRY_PATH_FIELDS = ("stream_geometry_path", "minimal_stream_geometry_path")
"""The output fields that name a file, anchored to the document that declares them."""


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
    for name, declared in cfg.outputs.items():
        written = anchored["calibration"]["outputs"].get(name)
        if not isinstance(written, dict):
            continue
        for field in GEOMETRY_PATH_FIELDS:
            resolved = getattr(declared, field, None)
            if resolved and field in written and Path(resolved).is_absolute():
                written[field] = os.path.relpath(resolved, base)
    return anchored


def session_config_hash(raw: Mapping[str, Any], trial_ctx: TrialContext | None) -> str:
    """Return the identity hash of the resolved case the session calibrates.

    The same hash a run records: the resolved configuration and the digests
    of its input files. A session with no prepared model (an evaluator that
    runs no HydroModPy model) hashes the document it read.
    """
    if trial_ctx is not None and hasattr(trial_ctx.base_cfg, "model_dump"):
        base_cfg = trial_ctx.base_cfg
        digest = run_identity_hash(
            base_cfg.model_dump(mode="json"), inputs=input_file_digests(base_cfg)
        )
        if digest is not None:
            return digest
    digest = run_identity_hash(dict(raw))
    if digest is not None:
        return digest
    return hashlib.sha256(json.dumps(dict(raw), sort_keys=True, default=str).encode()).hexdigest()


def objective_window_of(
    cfg: CalibrationConfig, document: Mapping[str, Any] | None = None
) -> DateWindow | None:
    """Return the window the session scores its objective on.

    A staged calibration promotes the best trial of its last phase, so its
    window is the one of that phase, or the section's when the phase writes
    none. A bound left open is the start or the end of the period that
    ``[simulation.time]`` of *document* declares. ``None`` when a bound stays
    unknown: a search that skips ``warmup_periods`` samples, or no period to
    close the window with.
    """
    window = cfg.scoring_window
    if cfg.phases and cfg.phases[-1].scoring_window is not None:
        window = cfg.phases[-1].scoring_window
    if window is None and cfg.warmup_periods:
        return None
    bounds = scoring_window_bounds(window) or (None, None)
    period_start, period_end = _declared_period(document)
    start = bounds[0].date() if bounds[0] is not None else period_start
    end = bounds[1].date() if bounds[1] is not None else period_end
    if start is None or end is None:
        return None
    return DateWindow(start=start, end=end)


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


def search_space_payload(space: ParameterSpace) -> dict[str, Any]:
    """Return the searched bounds, one entry per parameter, as plain data."""
    return {
        param.name: {
            "bounds": [param.lower, param.upper],
            "search_space": param.search_space,
            "target": param.effective_path,
            "units": param.units,
        }
        for param in space
    }


__all__ = [
    "calibration_case_name",
    "freeze_session_config",
    "latest_session_dir",
    "objective_window_of",
    "open_session_dir",
    "project_root_for",
    "search_space_payload",
    "session_config_hash",
]
