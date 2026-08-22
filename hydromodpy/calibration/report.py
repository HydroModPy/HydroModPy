"""Calibration session data structures and loaders.

Two concerns live here, both purely data-side:

1. :class:`CalibrationReport` - structured return type of
   ``run_calibration_cli`` and ``Project.calibrate``. Exposes session metadata plus
   lazy accessors for the iteration history and the best :class:`Run`.
2. :class:`SessionReportData` + :func:`load_session_report_data` - read
   one calibration session out of the workspace catalog and return a
   plain dataclass ready to be handed to the display layer for HTML
   rendering. The rendering itself lives in
   :mod:`hydromodpy.reporting.calibration_report`; this module never
   imports ``hydromodpy.display`` or ``hydromodpy.reporting``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# CalibrationReport dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationReport:
    """Structured summary of one calibration session.

    Returned by ``Project.calibrate`` and by the ``run_calibration_cli`` helper (both keep a
    ``to_dict`` shim so
    existing callers keep working).

    Attributes
    ----------
    session_id
        UUID (hex) of the calibration session in the catalog.
    method
        Optimizer method name (e.g. ``"optuna"``).
    n_iterations
        Number of iterations actually run (could be < ``max_iter`` if
        the optimizer converged).
    best_objective
        Best (minimum) objective value achieved.
    best_sim_id
        UUID of the promoted best run when ``save_runs != "none"``,
        otherwise ``None``.
    best_parameters
        Physical values of the best candidate, keyed by calibrated parameter
        name. ``None`` when no candidate was evaluated. A staged calibration
        reads it to freeze what a phase calibrated.
    duration_s
        Wall-clock duration of the calibration loop in seconds.
    save_runs
        The ``save_runs`` mode used (``"none"``, ``"best_n"`` or ``"all"``).
    promoted
        Count of iterations promoted to full simulations after the loop.
    workspace
        Workspace root the session was written to.
    extra
        Free-form metadata (callers may attach anything extra here).
    """

    session_id: str
    method: str
    n_iterations: int
    best_objective: float | None
    best_sim_id: str | None
    duration_s: float
    save_runs: str
    promoted: int
    best_parameters: dict[str, float] | None = None
    workspace: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    store_factory: Callable[[Path], Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    # ------------------------------------------------------------------
    # Lazy accessors
    # ------------------------------------------------------------------

    @property
    def iterations(self):
        """Return the iteration history as a :class:`pandas.DataFrame`.

        Loads lazily through the configured calibration store.
        """
        import pandas as pd

        if self.workspace is None:
            return pd.DataFrame()
        from hydromodpy.calibration.persistence import CalibrationPersistence

        with self._open_store() as catalog:
            rows = CalibrationPersistence(catalog).load_iterations(self.session_id)
        return pd.DataFrame(rows)

    @property
    def best(self):
        """Return the best promoted :class:`Run` or ``None``."""
        if self.best_sim_id is None or self.workspace is None:
            return None

        with self._open_store() as catalog:
            return catalog[self.best_sim_id]

    def _open_store(self):
        """Open the report store using the injected factory or default catalog."""
        if self.workspace is None:
            raise ValueError("CalibrationReport has no workspace")
        if self.store_factory is not None:
            return self.store_factory(self.workspace)
        from hydromodpy.calibration.runners.state import default_store_factory

        return default_store_factory(self.workspace, None)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary matching the legacy CLI output."""
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "method": self.method,
            "n_iterations": int(self.n_iterations),
            "best_objective": self.best_objective,
            "best_sim_id": self.best_sim_id,
            "duration_s": round(float(self.duration_s), 3),
            "save_runs": self.save_runs,
            "promoted": int(self.promoted),
        }
        if self.best_parameters is not None:
            payload["best_parameters"] = dict(self.best_parameters)
        if self.workspace is not None:
            payload["workspace"] = str(self.workspace)
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload


# ---------------------------------------------------------------------------
# SessionReportData - data handed to the display layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionReportData:
    """Plain data extracted from one calibration session.

    Carries everything
    :func:`hydromodpy.reporting.calibration_report.render_session` needs to
    produce the HTML report; no catalog handle, no live database
    connection. Constructed by :func:`load_session_report_data`.

    Attributes
    ----------
    session_id
        Canonical hex session identifier.
    session_name
        Readable name of the session directory on disk
        (``<date>-<method>-<id8>``), so the report sits under the same name.
    session
        Row from ``calibration_sessions`` as a dict.
    iterations
        Rows from ``calibration_iterations`` as a list of dicts.
    workspace_root
        Workspace root the session was written to (used to compute the
        report output directory).
    best_sim_id
        Canonical hex sim_id of the promoted best run, or ``None`` when
        no run was promoted.
    sim_timeseries
        Simulated discharge for ``best_sim_id`` (columns ``datetime``,
        ``value``), or ``None`` when no best run is available.
    obs_timeseries
        Observed discharge for ``best_sim_id`` (columns ``datetime``,
        ``value``), or ``None`` when no observations are available.
    """

    session_id: str
    session_name: str
    session: dict[str, Any]
    iterations: list[dict[str, Any]]
    workspace_root: Path
    best_sim_id: str | None
    sim_timeseries: pd.DataFrame | None
    obs_timeseries: pd.DataFrame | None
    variable: str = "discharge"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _session_candidates(conn: Any) -> list[tuple[str, Any]]:
    """Return ``[(session_hex, started_at)]`` ordered most-recent first."""
    rows = conn.execute(
        "SELECT session_id, started_at FROM calibration_sessions "
        "ORDER BY started_at DESC NULLS LAST",
    ).fetchall()
    return [(_hex(r[0]), r[1]) for r in rows]


def _sessions_for_sim_prefix(conn: Any, normalized: str) -> set[str]:
    """Return session hexes whose calibration run matches ``normalized``.

    Matches both iteration runs (``calibration_iterations.sim_id``) and the
    promoted best run (``calibration_sessions.best_sim_id``), so a reference
    copied from ``hmp catalog ls`` resolves to its parent session.
    """
    out: set[str] = set()
    for session_id, sim_id in conn.execute(
        "SELECT session_id, sim_id FROM calibration_iterations WHERE sim_id IS NOT NULL"
    ).fetchall():
        if _hex(sim_id).startswith(normalized):
            out.add(_hex(session_id))
    for session_id, best in conn.execute(
        "SELECT session_id, best_sim_id FROM calibration_sessions WHERE best_sim_id IS NOT NULL"
    ).fetchall():
        if _hex(best).startswith(normalized):
            out.add(_hex(session_id))
    return out


def _match_session_ids(conn: Any, raw: str) -> list[str]:
    """Return session hexes matching ``raw`` as a session id or a run id.

    ``raw`` is a full UUID or a unique hex prefix. A reference that matches a
    calibration run (an iteration sim_id or the promoted best run) resolves to
    that run's parent session. Never raises; returns ``[]`` on no match.
    """
    import uuid

    normalized = raw.replace("-", "").lower()
    candidates = {h for h, _ in _session_candidates(conn)}
    if not candidates:
        return []
    hits: set[str] = set()
    if len(normalized) == 32:
        try:
            full = uuid.UUID(normalized).hex
        except ValueError:
            full = None
        if full is not None and full in candidates:
            hits.add(full)
    else:
        hits.update(h for h in candidates if h.startswith(normalized))
    hits.update(h for h in _sessions_for_sim_prefix(conn, normalized) if h in candidates)
    return sorted(hits)


def resolve_calibration_session_id(
    catalog: Any,
    raw: str | None,
) -> str:
    """Return the canonical hex session id for ``raw`` in one catalog.

    ``raw`` accepts a full UUID (hex or dashed, 32 hex chars) or a unique
    prefix of >= 1 hex char, matching either a calibration session id or a
    calibration run id (mapped to its parent session). When ``raw`` is
    ``None``, return the most recently started session.
    """
    from hydromodpy.core.exceptions import ConfigError, ConfigMissingError

    candidates = _session_candidates(catalog.connection)
    if not candidates:
        raise ConfigMissingError("No calibration session found in the workspace catalog.")
    if raw is None:
        return candidates[0][0]
    matches = _match_session_ids(catalog.connection, raw)
    if not matches:
        raise ConfigMissingError(f"No calibration session or run matches {raw!r}.")
    if len(matches) > 1:
        raise ConfigError(
            f"Reference {raw!r} is ambiguous ({len(matches)} sessions). Use more hex characters."
        )
    return matches[0]


def _iter_catalog_roots(workspace_root: Path) -> list[Path]:
    """Return the workspace catalog roots (single canonical federation helper)."""
    from hydromodpy.results.catalog import iter_project_catalog_roots

    return iter_project_catalog_roots(workspace_root)


def resolve_session_in_workspace(
    workspace_root: Path,
    raw: str | None,
) -> tuple[Path, str]:
    """Resolve a calibration session across a whole workspace.

    Searches the workspace-level catalog and every ``projects/<name>`` catalog
    under ``workspace_root``. ``raw`` may be a session id/prefix or a
    calibration run id/prefix (mapped to its parent session). ``None`` selects
    the most recently started session anywhere in the workspace.

    Returns ``(catalog_root, session_hex)``: the project root whose catalog owns
    the session, ready to open for rendering.
    """
    from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
    from hydromodpy.results.catalog import Catalog

    workspace_root = Path(workspace_root).expanduser().resolve()
    roots = _iter_catalog_roots(workspace_root)
    if not roots:
        raise ConfigMissingError(
            f"No catalog found under {workspace_root}. Pass -w <workspace-or-project>."
        )
    if len(roots) == 1:
        with Catalog(roots[0], read_only=True) as catalog:
            return roots[0], resolve_calibration_session_id(catalog, raw)

    matches: list[tuple[Path, str, Any]] = []
    for root in roots:
        try:
            with Catalog(root, read_only=True) as catalog:
                conn = catalog.connection
                if raw is None:
                    cands = _session_candidates(conn)
                    if cands:
                        matches.append((root, cands[0][0], cands[0][1]))
                else:
                    started = dict(_session_candidates(conn))
                    matches.extend(
                        (root, sid, started.get(sid)) for sid in _match_session_ids(conn, raw)
                    )
        except Exception as exc:  # a locked or stale catalog must not hide the rest
            logger.warning("report: skipping catalog %s: %s", root, exc)

    if not matches:
        if raw is None:
            raise ConfigMissingError(
                f"No calibration session found in any project under {workspace_root}."
            )
        raise ConfigMissingError(
            f"No calibration session or run matches {raw!r} in workspace {workspace_root}. "
            "Run 'hmp catalog ls' to list runs."
        )
    if raw is None:
        matches.sort(
            key=lambda m: (m[2] is not None, m[2].timestamp() if m[2] is not None else 0.0),
            reverse=True,
        )
        return matches[0][0], matches[0][1]
    distinct = {(root, sid) for root, sid, _ in matches}
    if len(distinct) > 1:
        listing = ", ".join(
            f"{root.name}/{sid[:8]}"
            for root, sid in sorted(distinct, key=lambda x: (x[0].name, x[1]))
        )
        raise ConfigError(
            f"Reference {raw!r} is ambiguous across the workspace: {listing}. "
            "Use more hex characters or pass -w <project_dir>."
        )
    root, sid = next(iter(distinct))
    return root, sid


def load_session_report_data(
    *,
    catalog: Any,
    session_id: str,
    workspace_root: Path,
) -> SessionReportData:
    """Load all data needed to render an HTML report for one session.

    Reads the session row, the iteration history, and (when a best run
    is available) the simulated and observed discharge timeseries. The
    return value is a plain dataclass, so the caller is free to render
    it through any backend.
    """
    session_row = _load_session(catalog, session_id)
    iterations = _load_iterations(catalog, session_id)
    variable = _calibration_variable(session_row)
    best_sim_id = _pick_report_sim_id(session_row, iterations)
    sim_df = obs_df = None
    if best_sim_id is not None:
        sid = _dashed(best_sim_id)
        if variable == "lake_level":
            sim_df, obs_df = _load_best_lake_level(catalog, sid)
        else:
            sim_df, obs_df = _load_best_discharge(catalog, sid)
    return SessionReportData(
        session_id=session_id,
        session_name=_session_name(session_row, session_id),
        session=session_row,
        iterations=iterations,
        workspace_root=Path(workspace_root),
        best_sim_id=best_sim_id,
        sim_timeseries=sim_df,
        obs_timeseries=obs_df,
        variable=variable,
    )


def _session_name(session_row: dict, session_id: str) -> str:
    """Return the on-disk directory name of the session.

    Rebuilt from the same ``(method, started_at)`` pair the journal used, so
    a report never invents a second vocabulary for one session.
    """
    from datetime import datetime

    from hydromodpy.results.session_journal import session_dir_name

    started_at = session_row["started_at"]
    if not isinstance(started_at, datetime):
        started_at = datetime.fromisoformat(str(started_at))
    return session_dir_name(session_id, str(session_row["method"]), started_at)


# ---------------------------------------------------------------------------
# Catalog reads
# ---------------------------------------------------------------------------


def _load_session(catalog: Any, session_id: str) -> dict:
    import uuid

    sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
    row = catalog.connection.execute(
        """
        SELECT s.session_id, s.project, s.method, s.objective_name,
               s.n_iterations, s.config, s.started_at, s.ended_at,
               st.code AS status,
               s.best_sim_id, s.best_objective, s.duration_s
          FROM calibration_sessions s
          LEFT JOIN statuses st ON st.id = s.status_id
         WHERE s.session_id = ?
        """,
        [sid],
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown calibration session {session_id!r}")
    keys = (
        "session_id",
        "project",
        "method",
        "objective_name",
        "n_iterations",
        "config",
        "started_at",
        "ended_at",
        "status",
        "best_sim_id",
        "best_objective",
        "duration_s",
    )
    return dict(zip(keys, row, strict=False))


def _load_iterations(catalog: Any, session_id: str) -> list[dict]:
    from hydromodpy.calibration.persistence import CalibrationPersistence

    return CalibrationPersistence(catalog).load_iterations(session_id)


def _calibration_variable(session_row: dict) -> str:
    """Return the calibrated variable from the persisted session config."""
    config = session_row.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (TypeError, ValueError):
            config = {}
    if isinstance(config, dict):
        return str(config.get("variable", "discharge"))
    return "discharge"


def _dashed(value: Any) -> str:
    """Normalize a sim id to the dashed UUID form stored in the catalog."""
    import uuid

    hexed = _hex(value)
    try:
        return str(uuid.UUID(hexed))
    except ValueError:
        return str(value)


def _load_best_lake_level(
    catalog: Any, sim_id: str
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Return (simulated stage, observed lake level) for ``sim_id``.

    The simulated LAK stage comes from the catalog ``timeseries`` (one
    ``lake:<id>`` station per lake); the observed series comes from the
    ``observations`` table populated at promotion. Either side may be ``None``
    when the catalog has no matching rows.
    """
    try:
        stations = catalog.backend.query(
            "SELECT DISTINCT station_id FROM timeseries "
            "WHERE sim_id = ? AND variable = 'stage' AND station_id LIKE 'lake:%' "
            "ORDER BY station_id",
            [sim_id],
        )
        if stations.empty:
            return None, None
        station = str(stations.iloc[0, 0])
        sim_df = catalog.backend.query(
            "SELECT time AS datetime, value FROM timeseries "
            "WHERE sim_id = ? AND station_id = ? AND variable = 'stage' ORDER BY timestep",
            [sim_id, station],
        )
        obs_df = catalog.backend.query(
            "SELECT datetime, value FROM observations "
            "WHERE station_id = ? AND variable_type = 'lake_level' ORDER BY datetime",
            [station],
        )
    except Exception as exc:
        logger.warning("best_lake_level: catalog query failed: %s", exc)
        return None, None
    return sim_df, obs_df


def _load_best_discharge(
    catalog: Any, sim_id: str
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Return (simulated, observed) discharge frames for ``sim_id``.

    Either side may be ``None`` (or empty) if the catalog does not
    contain matching rows; the display layer is expected to skip the
    obs-vs-sim figure in that case.
    """
    try:
        sim_df = catalog.backend.query(
            "SELECT time AS datetime, value FROM timeseries "
            "WHERE sim_id = ? AND variable = 'discharge' AND station_id = '_catchment' "
            "ORDER BY timestep",
            [sim_id],
        )
        obs_df = catalog.backend.query(
            "SELECT time AS datetime, value FROM timeseries "
            "WHERE sim_id = ? AND variable = 'discharge_obs' "
            "ORDER BY timestep",
            [sim_id],
        )
    except Exception as exc:
        logger.warning("best_obs_vs_sim: catalog query failed: %s", exc)
        return None, None
    return sim_df, obs_df


def _pick_report_sim_id(session_row: dict, iterations: list[dict]) -> str | None:
    """Return the sim_id used by the obs-vs-sim figure.

    Prefers the session-level ``best_sim_id`` (promoted run); falls back
    to the lowest-cost iteration whose ``sim_id`` is set when the session
    field is empty (e.g. failed promotion of the top iteration).
    """
    sid = session_row.get("best_sim_id")
    if sid is not None:
        return _hex(sid)
    for row in sorted(
        (r for r in iterations if r.get("sim_id") and r.get("objective_value") is not None),
        key=lambda r: r["objective_value"],
    ):
        return _hex(row["sim_id"])
    return None


def _hex(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "hex"):
        return value.hex
    return str(value).replace("-", "")


__all__ = (
    "CalibrationReport",
    "SessionReportData",
    "load_session_report_data",
    "resolve_calibration_session_id",
    "resolve_session_in_workspace",
)
