"""Reference resolution and Run/Group discovery.

``resolve`` is the canonical lookup that turns a user reference (full UUID,
prefix, or ``name`` within a project) into a simulation ``sim_id``.
``__getitem__`` / ``find`` / ``latest`` / ``best`` build :class:`Run` and
:class:`RunSet` views on top of it.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.results.catalog.constants import (
    OUTLET_STATION,
    UnrankedMetricError,
    metric_rank_sql,
)

if TYPE_CHECKING:
    from hydromodpy.results.run import Run
    from hydromodpy.results.run.group import RunSet


def iter_project_catalog_roots(workspace_root: Path | str) -> list[Path]:
    """Return every project catalog root under ``workspace_root``.

    The layout rule lives in
    :func:`hydromodpy.core.state.paths.project_roots_under`; this helper only
    narrows its answer to the roots that already carry an index database, since
    a caller here is about to read one. Sorted, workspace root first.
    """
    from hydromodpy.core.state.paths import catalog_path_for, project_roots_under

    return [
        root
        for root in project_roots_under(Path(workspace_root))
        if catalog_path_for(root).is_file()
    ]


_MIN_PREFIX_LEN = 4
_UUID_FULL_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)
_LAST_SELECTOR_RE = re.compile(r"^(?:last|latest)(?:~(\d+))?$")
_RANK_SELECTOR_RE = re.compile(r"^(best|worst):(.+)$")


def short_id(sim_id: str | UUID) -> str:
    """Return the first 8 hex characters of a simulation UUID (Git-style)."""
    return str(sim_id)[:8]


class ReferenceResolutionError(Exception):
    """Base class for catalog reference resolution failures.

    Deliberately not a :class:`KeyError`: that subclassing doubled the quotes
    in error rendering and collapsed not-found and ambiguous into one exit code.
    """


class SimulationNotFoundError(ReferenceResolutionError):
    """Raised when a reference does not match any simulation in the catalog."""


class AmbiguousReferenceError(ReferenceResolutionError):
    """Raised when a reference matches more than one simulation."""

    def __init__(self, ref: str, candidates: list[tuple[str, str | None]]) -> None:
        self.ref = ref
        self.candidates = candidates
        head = candidates[:10]
        lines = "\n".join(f"  {short_id(sid)}  {name or '(no name)'}" for sid, name in head)
        suffix = f"\n  ... and {len(candidates) - 10} more" if len(candidates) > 10 else ""
        super().__init__(
            f"Reference '{ref}' is ambiguous; matches {len(candidates)} "
            f"simulations:\n{lines}{suffix}"
        )


class DiscoveryMixin:
    """Reference-resolution and view-builder methods for :class:`Catalog`.

    Relies on the facade attribute ``self._backend`` (CatalogBackend port).
    """

    def resolve(
        self,
        ref: str | UUID,
        *,
        project: str | None = None,
        in_trash: bool = False,
        unambiguous: bool = False,
    ) -> str:
        """Resolve a user reference to a simulation UUID.

        Accepted forms, tried in order:

        1. ``@``-selectors: ``@last``, ``@last~N`` (N-th newest completed),
           ``@best:METRIC`` / ``@worst:METRIC`` (outlet first, any station as
           fallback; add ``@STATION`` to scope explicitly), ``@running``. Best
           follows the direction of the metric: highest ``nse``, lowest
           ``rmse``, ``pbias`` closest to zero (see
           :data:`~hydromodpy.results.catalog.constants.METRIC_SENSE`).
        2. Full UUID (36 chars with dashes).
        3. UUID prefix of >= 4 hex characters. Must match a single simulation;
           raises :class:`AmbiguousReferenceError` otherwise.
        4. Exact ``name`` of a live run (globally, or within ``project``).
        5. ``name_stem``: a bare name resolves to the latest live version of
           that stem (``baseline`` -> ``baseline.v3``).
        6. Exact ``name`` of a trashed run, when no live run answers to it.

        With ``in_trash``, a name looks only at trashed runs, under the name
        the trash listing shows (``original_name``): it is what ``restore``
        means. With ``unambiguous``, a name that a live run answers to (rules
        4 and 5) while a trashed run still carries it raises
        :class:`AmbiguousReferenceError` listing both: a purge must not pick
        one of two runs the user could mean.

        Raises :class:`SimulationNotFoundError` when nothing matches, with the
        closest known names and tags suggested.
        """
        ref_s = str(ref).strip()
        if not ref_s:
            raise SimulationNotFoundError("Empty reference")

        if ref_s.startswith("@"):
            return self._resolve_selector(ref_s[1:], project=project)

        if _UUID_FULL_RE.match(ref_s):
            row = self._backend.fetch_one(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
                [ref_s.lower()],
            )
            if row:
                return str(row[0])

        ref_nodash = ref_s.replace("-", "").lower()
        if _HEX_RE.match(ref_nodash) and len(ref_nodash) >= _MIN_PREFIX_LEN:
            rows = self._backend.fetch_all(
                "SELECT CAST(sim_id AS VARCHAR), name FROM simulations "
                "WHERE REPLACE(CAST(sim_id AS VARCHAR), '-', '') LIKE ? || '%'",
                [ref_nodash],
            )
            # A hex-looking name (e.g. 'beef1234') can be both a UUID prefix and
            # an exact run name. Detect the cross-kind collision: if an exact
            # name matches a different sim, raise rather than silently return
            # the prefix hit.
            name_rows = self._backend.fetch_all(
                "SELECT CAST(sim_id AS VARCHAR), project FROM simulations WHERE name = ?"
                + (" AND project = ?" if project is not None else ""),
                ([ref_s, project] if project is not None else [ref_s]),
            )
            candidate_ids = {str(r[0]) for r in rows} | {str(r[0]) for r in name_rows}
            if len(candidate_ids) > 1:
                combined = {str(r[0]): r[1] for r in rows}
                for r in name_rows:
                    combined.setdefault(str(r[0]), ref_s)
                raise AmbiguousReferenceError(ref_s, list(combined.items()))
            if len(rows) == 1:
                return str(rows[0][0])
            if len(name_rows) == 1:
                return str(name_rows[0][0])

        if in_trash:
            return self._resolve_trashed_name(ref_s, project)

        # Exact name match, live runs only. A run that ``if_exists = "replace"``
        # sent to the trash keeps its name; answering with it would hand back
        # the run the user just replaced instead of the one that replaced it.
        exact_sql = (
            "SELECT CAST(sim_id AS VARCHAR), project, "
            "status_id = (SELECT id FROM statuses WHERE code = 'trashed') "
            "FROM simulations WHERE name = ?"
        )
        exact_params: list[str] = [ref_s]
        if project is not None:
            exact_sql += " AND project = ?"
            exact_params.append(project)
        exact_rows = self._backend.fetch_all(exact_sql, exact_params)
        live_exact = [r for r in exact_rows if not r[2]]
        if len(live_exact) == 1:
            if unambiguous:
                self._refuse_a_name_the_trash_holds(ref_s, project, str(live_exact[0][0]), ref_s)
            return str(live_exact[0][0])
        if len(live_exact) > 1:
            raise AmbiguousReferenceError(
                ref_s,
                [(str(r[0]), f"{ref_s} (project={r[1]})") for r in live_exact],
            )

        # Bare stem -> latest live version of the stem.
        stem_sql = (
            "SELECT CAST(sim_id AS VARCHAR), project, name FROM simulations "
            "WHERE name_stem = ? "
            "AND status_id <> (SELECT id FROM statuses WHERE code = 'trashed') "
        )
        params: list[str] = [ref_s]
        if project is not None:
            stem_sql += "AND project = ? "
            params.append(project)
        stem_sql += "ORDER BY version_int DESC"
        stem_rows = self._backend.fetch_all(stem_sql, params)
        if stem_rows:
            projects = {r[1] for r in stem_rows}
            if len(projects) == 1:
                if unambiguous:
                    self._refuse_a_name_the_trash_holds(
                        ref_s, project, str(stem_rows[0][0]), str(stem_rows[0][2])
                    )
                return str(stem_rows[0][0])
            raise AmbiguousReferenceError(
                ref_s,
                [(str(r[0]), f"{ref_s} (project={r[1]})") for r in stem_rows],
            )

        # Nothing live answers to the name: a trashed run that still carries it
        # is what the user means (to restore it, or to read it before it goes).
        if len(exact_rows) == 1:
            return str(exact_rows[0][0])
        if len(exact_rows) > 1:
            raise AmbiguousReferenceError(
                ref_s,
                [(str(r[0]), f"{ref_s} (project={r[1]}, trashed)") for r in exact_rows],
            )

        raise SimulationNotFoundError(self._not_found_message(ref_s, project))

    def _trashed_name_rows(self, ref: str, project: str | None) -> list[tuple]:
        """Return ``(sim_id, project)`` of the trashed runs that carry ``ref``.

        A run sent to the trash by ``if_exists = "replace"`` keeps ``name``; one
        trashed by ``Catalog.trash`` keeps it only as ``original_name``, which
        is what the trash listing shows. Both count.
        """
        sql = (
            "SELECT CAST(sim_id AS VARCHAR), project FROM simulations "
            "WHERE status_id = (SELECT id FROM statuses WHERE code = 'trashed') "
            "AND (name = ? OR original_name = ?)"
        )
        params: list[str] = [ref, ref]
        if project is not None:
            sql += " AND project = ?"
            params.append(project)
        return list(self._backend.fetch_all(sql + " ORDER BY trashed_at DESC", params))

    def _resolve_trashed_name(self, ref: str, project: str | None) -> str:
        """Resolve ``ref`` as the name of a trashed run, the way the trash lists it."""
        rows = self._trashed_name_rows(ref, project)
        if len(rows) == 1:
            return str(rows[0][0])
        if len(rows) > 1:
            raise AmbiguousReferenceError(
                ref, [(str(r[0]), f"{ref} (project={r[1]}, trashed)") for r in rows]
            )
        raise SimulationNotFoundError(f"No trashed simulation named '{ref}'.")

    def _refuse_a_name_the_trash_holds(
        self, ref: str, project: str | None, live_sid: str, live_name: str
    ) -> None:
        """Raise when ``ref`` names both the live run ``live_sid`` and a trashed one."""
        trashed = [r for r in self._trashed_name_rows(ref, project) if str(r[0]) != live_sid]
        if trashed:
            raise AmbiguousReferenceError(
                ref,
                [(live_sid, f"{live_name} (live)")]
                + [(str(r[0]), f"{ref} (trashed)") for r in trashed],
            )

    def _resolve_selector(self, body: str, *, project: str | None) -> str:
        """Resolve an ``@``-selector body (the part after ``@``)."""
        last_match = _LAST_SELECTOR_RE.match(body)
        if last_match:
            offset = int(last_match.group(1) or 0)
            row = self._backend.fetch_one(
                "SELECT CAST(s.sim_id AS VARCHAR) FROM simulations s "
                "JOIN statuses st ON s.status_id = st.id "
                "WHERE st.code = 'completed' "
                + ("AND s.project = ? " if project else "")
                + "ORDER BY s.created_at DESC LIMIT 1 OFFSET ?",
                ([project, offset] if project else [offset]),
            )
            if row:
                return str(row[0])
            scope = f" in project '{project}'" if project else ""
            raise SimulationNotFoundError(f"No completed run for '@{body}'{scope}")

        rank_match = _RANK_SELECTOR_RE.match(body)
        if rank_match:
            kind, remainder = rank_match.group(1), rank_match.group(2).strip()
            # Optional station scope: '@best:kge@lake:forebay'. Without one, the
            # outlet station is preferred and any-station best is the fallback.
            metric, _, station = remainder.partition("@")
            metric = metric.strip()
            station = station.strip() or None
            try:
                order = metric_rank_sql(metric, best=kind == "best")
            except UnrankedMetricError as exc:
                raise SimulationNotFoundError(f"'@{body}': {exc}") from exc
            row = self._rank_best_run(metric, order, station=station, project=project)
            if row is not None:
                return str(row)
            scope = f" in project '{project}'" if project else ""
            where = f"at station '{station}'" if station else "at outlet or any station"
            raise SimulationNotFoundError(
                f"No completed run with metric '{metric}' {where} for '@{body}'{scope}"
            )

        if body == "running":
            row = self._backend.fetch_one(
                "SELECT CAST(s.sim_id AS VARCHAR) FROM simulations s "
                "JOIN statuses st ON s.status_id = st.id "
                "WHERE st.code = 'running' "
                + ("AND s.project = ? " if project else "")
                + "ORDER BY s.created_at DESC LIMIT 1",
                ([project] if project else []),
            )
            if row:
                return str(row[0])
            raise SimulationNotFoundError("No running run")

        raise SimulationNotFoundError(
            f"Unknown selector '@{body}'. "
            "Known: @last, @last~N, @best:METRIC, @worst:METRIC, @running"
        )

    def _rank_best_run(
        self,
        metric: str,
        order: str,
        *,
        station: str | None,
        project: str | None,
    ) -> str | None:
        """Return the best/worst run for ``metric``, honouring a station scope.

        ``order`` is the ``ORDER BY`` expression of :func:`metric_rank_sql`, so
        best follows the direction of the metric. With an explicit ``station``
        the rank is scoped to it. Without one, the outlet station is tried
        first, then any station (lake-level metrics live at lake/station
        scopes, not at the outlet). A missing or non-finite value never ranks.
        """
        stations = [station] if station is not None else [OUTLET_STATION, None]
        for scope in stations:
            sql = (
                "SELECT CAST(s.sim_id AS VARCHAR) FROM simulations s "
                "JOIN statuses st ON s.status_id = st.id "
                "JOIN metrics m ON s.sim_id = m.sim_id "
                "WHERE st.code = 'completed' AND m.metric_name = ? "
                "AND m.value IS NOT NULL AND isfinite(m.value) "
            )
            params: list = [metric]
            if scope is not None:
                sql += "AND m.station_id = ? "
                params.append(scope)
            if project:
                sql += "AND s.project = ? "
                params.append(project)
            sql += f"ORDER BY {order} LIMIT 1"
            row = self._backend.fetch_one(sql, params)
            if row is not None:
                return str(row[0])
        return None

    def _not_found_message(self, ref: str, project: str | None) -> str:
        """Build a not-found message suggesting the closest names and tags."""
        context = f" in project '{project}'" if project else ""
        name_rows = self._backend.fetch_all(
            "SELECT name FROM simulations WHERE name IS NOT NULL"
            + (" AND project = ?" if project else ""),
            ([project] if project else []),
        )
        names = [str(r[0]) for r in name_rows]
        close = difflib.get_close_matches(ref, names, n=3, cutoff=0.4)
        if not close:
            tag_rows = self._backend.fetch_all(
                "SELECT DISTINCT tag FROM tags",
            )
            tags = [str(r[0]) for r in tag_rows]
            close = difflib.get_close_matches(ref, tags, n=3, cutoff=0.4)
        suggestion = f" Closest: {', '.join(close)}." if close else ""
        return f"Reference '{ref}' not found{context}. Run `hmp catalog ls` to list known runs.{suggestion}"

    def __getitem__(self, ref: str | UUID) -> Run:
        from hydromodpy.results.run import Run

        sid = self.resolve(ref)
        return Run(sid, self)

    def find(self, **filters) -> RunSet:
        """Return the runs that match every filter, newest first.

        Trashed runs are left out unless ``status`` asks for them.

        Parameters
        ----------
        **filters
            Each keyword narrows the set:

            - ``project``, ``name``, ``name_stem``, ``config_hash``,
              ``crs_wkt`` (or ``crs``), ``geographic_fingerprint``: exact value
              of that run column.
            - ``solver``, ``solver_category``, ``status``, ``flow_regime``,
              ``mesh_topology``: their code, for example ``solver="modflow6"``
              or ``status="completed"``.
            - ``tags``: one tag the run carries.
            - ``<metric>_gt``, ``<metric>_gte``, ``<metric>_lt``,
              ``<metric>_lte``: bound on an outlet metric, for example
              ``nse_gt=0.7``.

        Returns
        -------
        RunSet
            The matching runs. It is empty when nothing matches.

        Raises
        ------
        ValueError
            If a keyword is none of the above. The message lists them.

        Examples
        --------
        >>> good = cat.find(
        ...     project="my_project", status="completed", nse_gt=0.7
        ... )  # doctest: +SKIP
        >>> good.best("nse")  # doctest: +SKIP
        """
        from hydromodpy.results.run.group import RunSet

        # v2 dim-table joins for filters that hit text codes (solver/status/etc.).
        # Always-on JOINs keep the WHERE clause uniform whether or not the
        # caller filters on the joined columns.
        query = (
            "SELECT DISTINCT s.sim_id FROM simulations s "
            "JOIN solvers sv ON s.solver_id = sv.id "
            "JOIN statuses st ON s.status_id = st.id "
            "LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id "
            "LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id"
        )
        joins: list[str] = []
        clauses: list[str] = []
        join_params: list = []
        clause_params: list = []
        # v2: tags moved out of simulations into a per-sim table.
        tag_join_added = False
        has_status_filter = "status" in filters

        for key, val in filters.items():
            if key == "tags":
                if not tag_join_added:
                    joins.append("JOIN tags tg ON s.sim_id = tg.sim_id")
                    tag_join_added = True
                clauses.append("tg.tag = ?")
                clause_params.append(val)
            elif key.endswith("_gt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ? AND {alias}.station_id = ?"
                )
                join_params.extend([metric, OUTLET_STATION])
                clauses.append(f"{alias}.value > ?")
                clause_params.append(val)
            elif key.endswith("_lt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ? AND {alias}.station_id = ?"
                )
                join_params.extend([metric, OUTLET_STATION])
                clauses.append(f"{alias}.value < ?")
                clause_params.append(val)
            elif key.endswith("_gte"):
                metric = key[:-4]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ? AND {alias}.station_id = ?"
                )
                join_params.extend([metric, OUTLET_STATION])
                clauses.append(f"{alias}.value >= ?")
                clause_params.append(val)
            elif key.endswith("_lte"):
                metric = key[:-4]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ? AND {alias}.station_id = ?"
                )
                join_params.extend([metric, OUTLET_STATION])
                clauses.append(f"{alias}.value <= ?")
                clause_params.append(val)
            elif key == "crs":
                clauses.append("s.crs_wkt = ?")
                clause_params.append(val)
            elif key == "solver":
                clauses.append("sv.code = ?")
                clause_params.append(val)
            elif key == "solver_category":
                clauses.append("sv.category = ?")
                clause_params.append(val)
            elif key == "status":
                clauses.append("st.code = ?")
                clause_params.append(val)
            elif key == "flow_regime":
                clauses.append("fr.code = ?")
                clause_params.append(val)
            elif key == "mesh_topology":
                clauses.append("mt.code = ?")
                clause_params.append(val)
            elif key in (
                "project",
                "name",
                "name_stem",
                "config_hash",
                "crs_wkt",
                "geographic_fingerprint",
            ):
                clauses.append(f"s.{key} = ?")
                clause_params.append(val)
            else:
                raise ValueError(
                    f"Unknown filter {key!r}. Valid: solver, solver_category, status, "
                    "flow_regime, mesh_topology, project, name, name_stem, config_hash, "
                    "crs, tags, <metric>_gt, <metric>_lt, <metric>_gte, <metric>_lte"
                )

        # Trashed runs are hidden from find() unless explicitly asked for.
        if not has_status_filter:
            clauses.append("st.code <> 'trashed'")

        if joins:
            query += " " + " ".join(joins)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY s.created_at DESC"

        rows = self._backend.fetch_all(query, join_params + clause_params)
        sim_ids = [str(r[0]) for r in rows]
        return RunSet(sim_ids, self)

    def latest(self, project: str | None = None) -> Run:
        """Return the most recently created completed run.

        Parameters
        ----------
        project
            Look only at the runs of this project. ``None`` looks at the
            whole catalog.

        Returns
        -------
        Run
            The newest run whose status is ``completed``.

        Raises
        ------
        KeyError
            If no run is completed (in ``project``, when given).

        Examples
        --------
        >>> run = hmp.open("~/ws/projects/my_project").latest()  # doctest: +SKIP
        """
        from hydromodpy.results.run import Run

        if project is not None:
            row = self._backend.fetch_one(
                "SELECT s.sim_id FROM simulations s "
                "JOIN statuses st ON s.status_id = st.id "
                "WHERE s.project = ? AND st.code = 'completed' "
                "ORDER BY s.created_at DESC LIMIT 1",
                [project],
            )
            where = f"for project '{project}'"
        else:
            row = self._backend.fetch_one(
                "SELECT s.sim_id FROM simulations s "
                "JOIN statuses st ON s.status_id = st.id "
                "WHERE st.code = 'completed' "
                "ORDER BY s.created_at DESC LIMIT 1"
            )
            where = "in the catalog"
        if row is None:
            raise KeyError(f"No completed simulation {where}")
        return Run(str(row[0]), self)

    def diff(
        self,
        ref_a: str,
        ref_b: str,
        *,
        project: str | None = None,
    ) -> dict:
        """Compare two runs' parameters and outlet metrics.

        Returns ``{"a", "b", "params", "metrics"}`` where ``params``/``metrics``
        map each differing key to ``(value_a, value_b)`` (``None`` when absent
        from one side).
        """
        sid_a = self.resolve(ref_a, project=project)
        sid_b = self.resolve(ref_b, project=project)

        def _params(sid: str) -> dict:
            rows = self._backend.fetch_all(
                "SELECT param_name, zone_id, value FROM parameters WHERE sim_id = ?",
                [sid],
            )
            return {(r[0], r[1]): r[2] for r in rows}

        def _metrics(sid: str) -> dict:
            rows = self._backend.fetch_all(
                "SELECT metric_name, station_id, value FROM metrics WHERE sim_id = ?",
                [sid],
            )
            return {(r[0], r[1]): r[2] for r in rows}

        def _delta(map_a: dict, map_b: dict) -> dict:
            keys = sorted(set(map_a) | set(map_b), key=lambda k: (str(k[0]), str(k[1])))
            out: dict = {}
            for key in keys:
                va, vb = map_a.get(key), map_b.get(key)
                if va != vb:
                    out[key] = (va, vb)
            return out

        return {
            "a": sid_a,
            "b": sid_b,
            "params": _delta(_params(sid_a), _params(sid_b)),
            "metrics": _delta(_metrics(sid_a), _metrics(sid_b)),
        }

    def best(self, project: str, metric: str = "nse") -> Run:
        """Return the completed run with the best outlet value of ``metric``.

        Best follows the direction of the metric: the highest ``nse``, the
        lowest ``rmse``, the ``pbias`` closest to zero. A metric with no
        declared direction raises
        :class:`~hydromodpy.results.catalog.constants.UnrankedMetricError`.
        """
        return self.rank(project, metric, n=1)[0]

    def worst(self, project: str, metric: str = "nse") -> Run:
        """Return the completed run with the worst outlet value of ``metric``."""
        return self.rank(project, metric, n=1, best_first=False)[0]

    def rank(
        self,
        project: str,
        metric: str = "nse",
        *,
        ascending: bool | None = None,
        n: int = 1,
        best_first: bool = True,
    ) -> RunSet:
        """Return up to ``n`` completed runs ranked on the outlet ``metric``.

        Without ``ascending`` the runs come best first (``best_first=True``)
        or worst first, following the direction of the metric. ``ascending``
        orders on the raw value instead, for a metric with no direction.
        """
        from hydromodpy.results.run.group import RunSet

        if ascending is None:
            order = metric_rank_sql(metric, best=best_first)
        else:
            order = f"m.value {'ASC' if ascending else 'DESC'}"
        rows = self._backend.fetch_all(
            "SELECT s.sim_id FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE s.project = ? AND st.code = 'completed' "
            "AND m.metric_name = ? AND m.station_id = ? "
            "AND m.value IS NOT NULL AND isfinite(m.value) "
            f"ORDER BY {order} LIMIT ?",
            [project, metric, OUTLET_STATION, n],
        )
        if not rows:
            raise KeyError(
                f"No completed simulation with metric '{metric}' at outlet for project '{project}'"
            )
        return RunSet([str(r[0]) for r in rows], self)
