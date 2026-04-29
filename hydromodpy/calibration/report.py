"""Calibration session data structures and loaders.

Two concerns live here, both purely data-side:

1. :class:`CalibrationReport` - structured return type of
   :func:`hydromodpy.calibration.runner.run_calibration_cli` and
   :meth:`hydromodpy.Project.calibrate`. Exposes session metadata plus
   lazy accessors for the iteration history and the best :class:`Run`.
2. :class:`SessionReportData` + :func:`load_session_report_data` - read
   one calibration session out of the workspace catalog and return a
   plain dataclass ready to be handed to the display layer for HTML
   rendering. The rendering itself lives in
   :mod:`hydromodpy.display.sessions`; this module never imports
   ``hydromodpy.display``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.results.catalog import SimulationCatalog

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# CalibrationReport dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationReport:
    """Structured summary of one calibration session.

    Returned by :meth:`hydromodpy.Project.calibrate` and by the
    :func:`run_calibration_cli` helper (both keep a ``to_dict`` shim so
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
    workspace: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lazy accessors
    # ------------------------------------------------------------------

    @property
    def iterations(self):
        """Return the iteration history as a :class:`pandas.DataFrame`.

        Loads lazily via :class:`hydromodpy.results.catalog.SimulationCatalog`
        using the workspace attached to the report.
        """
        import pandas as pd

        if self.workspace is None:
            return pd.DataFrame()
        from hydromodpy.calibration.persistence import CalibrationPersistence
        from hydromodpy.results.catalog import SimulationCatalog

        with SimulationCatalog(self.workspace) as catalog:
            rows = CalibrationPersistence(catalog).load_iterations(self.session_id)
        return pd.DataFrame(rows)

    @property
    def best(self):
        """Return the best promoted :class:`Run` or ``None``."""
        if self.best_sim_id is None or self.workspace is None:
            return None
        from hydromodpy.results.catalog import SimulationCatalog

        with SimulationCatalog(self.workspace) as catalog:
            return catalog[self.best_sim_id]

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

    Carries everything :func:`hydromodpy.display.sessions.render_session`
    needs to produce the HTML report; no catalog handle, no live database
    connection. Constructed by :func:`load_session_report_data`.

    Attributes
    ----------
    session_id
        Canonical hex session identifier.
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
    session: dict[str, Any]
    iterations: list[dict[str, Any]]
    workspace_root: Path
    best_sim_id: str | None
    sim_timeseries: pd.DataFrame | None
    obs_timeseries: pd.DataFrame | None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def resolve_calibration_session_id(
    catalog: SimulationCatalog,
    raw: str | None,
) -> str:
    """Return the canonical hex session id for ``raw``.

    ``raw`` accepts a full UUID (hex or dashed, 32 hex chars) or a unique
    prefix of >= 1 hex char. When ``raw`` is ``None``, return the most
    recently started session.
    """
    import uuid

    from hydromodpy.core.exceptions import ConfigError, ConfigMissingError

    rows = catalog._connection.execute(
        "SELECT session_id, started_at FROM calibration_sessions "
        "ORDER BY started_at DESC NULLS LAST",
    ).fetchall()
    candidates = [r[0].hex if hasattr(r[0], "hex") else str(r[0]).replace("-", "") for r in rows]
    if not candidates:
        raise ConfigMissingError("No calibration session found in the workspace catalog.")

    if raw is None:
        return candidates[0]

    normalized = raw.replace("-", "").lower()
    if len(normalized) == 32:
        try:
            full = uuid.UUID(normalized).hex
        except ValueError as exc:
            raise ConfigError(f"Invalid calibration session id {raw!r}: {exc}") from exc
        if full in candidates:
            return full
        raise ConfigMissingError(f"Unknown calibration session {raw!r}.")

    matches = [c for c in candidates if c.startswith(normalized)]
    if not matches:
        raise ConfigMissingError(f"No calibration session matches {raw!r}.")
    if len(matches) > 1:
        raise ConfigError(
            f"Session prefix {raw!r} is ambiguous ({len(matches)} matches). "
            "Use more hex characters."
        )
    return matches[0]


def load_session_report_data(
    *,
    catalog: SimulationCatalog,
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
    best_sim_id = _pick_report_sim_id(session_row, iterations)
    sim_df = obs_df = None
    if best_sim_id is not None:
        sim_df, obs_df = _load_best_discharge(catalog, best_sim_id)
    return SessionReportData(
        session_id=session_id,
        session=session_row,
        iterations=iterations,
        workspace_root=Path(workspace_root),
        best_sim_id=best_sim_id,
        sim_timeseries=sim_df,
        obs_timeseries=obs_df,
    )


# ---------------------------------------------------------------------------
# Catalog reads
# ---------------------------------------------------------------------------


def _load_session(catalog: SimulationCatalog, session_id: str) -> dict:
    import uuid

    sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
    row = catalog._connection.execute(
        """
        SELECT session_id, project, method, objective_name,
               n_iterations, config, started_at, ended_at, status,
               best_sim_id, best_objective, duration_s
          FROM calibration_sessions
         WHERE session_id = ?
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


def _load_iterations(catalog: SimulationCatalog, session_id: str) -> list[dict]:
    from hydromodpy.calibration.persistence import CalibrationPersistence

    return CalibrationPersistence(catalog).load_iterations(session_id)


def _load_best_discharge(
    catalog: SimulationCatalog, sim_id: str
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Return (simulated, observed) discharge frames for ``sim_id``.

    Either side may be ``None`` (or empty) if the catalog does not
    contain matching rows; the display layer is expected to skip the
    obs-vs-sim figure in that case.
    """
    try:
        sim_df = catalog._connection.execute(
            "SELECT datetime, value FROM timeseries "
            "WHERE sim_id = ? AND variable = 'discharge' AND station_id = '_catchment' "
            "ORDER BY datetime",
            [sim_id],
        ).fetchdf()
        obs_df = catalog._connection.execute(
            "SELECT datetime, value FROM timeseries "
            "WHERE sim_id = ? AND variable = 'discharge_obs' "
            "ORDER BY datetime",
            [sim_id],
        ).fetchdf()
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
)
