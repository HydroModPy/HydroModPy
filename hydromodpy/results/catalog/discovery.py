"""Reference resolution and Run/Group discovery.

``resolve`` is the canonical lookup that turns a user reference (full UUID,
prefix, or ``name`` within a project) into a simulation ``sim_id``.
``__getitem__`` / ``find`` / ``latest`` / ``best`` build :class:`Run` and
:class:`SimulationGroup` views on top of it.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.results.catalog.constants import OUTLET_STATION

if TYPE_CHECKING:
    from hydromodpy.results.run import Run
    from hydromodpy.results.simulation_group import SimulationGroup

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
    """Reference-resolution and view-builder methods for :class:`SimulationCatalog`.

    Relies on the facade attribute ``self._backend`` (CatalogBackend port).
    """

    def resolve(
        self,
        ref: str | UUID,
        *,
        project: str | None = None,
    ) -> str:
        """Resolve a user reference to a simulation UUID.

        Accepted forms, tried in order:

        1. ``@``-selectors: ``@last``, ``@last~N`` (N-th newest completed),
           ``@best:METRIC`` / ``@worst:METRIC`` (canonical outlet scope),
           ``@running``.
        2. Full UUID (36 chars with dashes).
        3. UUID prefix of >= 4 hex characters. Must match a single simulation;
           raises :class:`AmbiguousReferenceError` otherwise.
        4. Exact ``name`` (globally, or within ``project``).
        5. ``name_stem``: a bare name resolves to the latest live version of
           that stem (``cheze_baseline`` -> ``cheze_baseline.v3``).

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
            if len(rows) == 1:
                return str(rows[0][0])
            if len(rows) > 1:
                raise AmbiguousReferenceError(
                    ref_s,
                    [(str(r[0]), r[1]) for r in rows],
                )

        # Exact name match.
        if project is not None:
            row = self._backend.fetch_one(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE project = ? AND name = ?",
                [project, ref_s],
            )
            if row:
                return str(row[0])
        else:
            rows = self._backend.fetch_all(
                "SELECT CAST(sim_id AS VARCHAR), project FROM simulations WHERE name = ?",
                [ref_s],
            )
            if len(rows) == 1:
                return str(rows[0][0])
            if len(rows) > 1:
                raise AmbiguousReferenceError(
                    ref_s,
                    [(str(r[0]), f"{ref_s} (project={r[1]})") for r in rows],
                )

        # Bare stem -> latest live version of the stem.
        stem_sql = (
            "SELECT CAST(sim_id AS VARCHAR), project FROM simulations "
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
                return str(stem_rows[0][0])
            raise AmbiguousReferenceError(
                ref_s,
                [(str(r[0]), f"{ref_s} (project={r[1]})") for r in stem_rows],
            )

        raise SimulationNotFoundError(self._not_found_message(ref_s, project))

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
            kind, metric = rank_match.group(1), rank_match.group(2).strip()
            order = "DESC" if kind == "best" else "ASC"
            row = self._backend.fetch_one(
                "SELECT CAST(s.sim_id AS VARCHAR) FROM simulations s "
                "JOIN statuses st ON s.status_id = st.id "
                "JOIN metrics m ON s.sim_id = m.sim_id "
                "WHERE st.code = 'completed' AND m.metric_name = ? "
                "AND m.station_id = ? "
                + ("AND s.project = ? " if project else "")
                + f"ORDER BY m.value {order} LIMIT 1",
                ([metric, OUTLET_STATION, project] if project else [metric, OUTLET_STATION]),
            )
            if row:
                return str(row[0])
            scope = f" in project '{project}'" if project else ""
            raise SimulationNotFoundError(
                f"No completed run with metric '{metric}' at outlet for '@{body}'{scope}"
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
        return f"Reference '{ref}' not found{context}. Run `hmp ls` to list known runs.{suggestion}"

    def __getitem__(self, ref: str | UUID) -> Run:
        from hydromodpy.results.run import Run

        sid = self.resolve(ref)
        return Run(sid, self)

    def find(self, **filters) -> SimulationGroup:
        from hydromodpy.results.simulation_group import SimulationGroup

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
                    "crs, tags, <metric>_gt, <metric>_lt, <metric>_gte"
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
        return SimulationGroup(sim_ids, self)

    def latest(self, project: str | None = None) -> Run:
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
        return self.rank(project, metric, ascending=False, n=1)[0]

    def worst(self, project: str, metric: str = "nse") -> Run:
        return self.rank(project, metric, ascending=True, n=1)[0]

    def rank(
        self,
        project: str,
        metric: str = "nse",
        *,
        ascending: bool = False,
        n: int = 1,
    ) -> SimulationGroup:
        from hydromodpy.results.simulation_group import SimulationGroup

        order = "ASC" if ascending else "DESC"
        rows = self._backend.fetch_all(
            "SELECT s.sim_id FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE s.project = ? AND st.code = 'completed' "
            "AND m.metric_name = ? AND m.station_id = ? "
            f"ORDER BY m.value {order} LIMIT ?",
            [project, metric, OUTLET_STATION, n],
        )
        if not rows:
            raise KeyError(
                f"No completed simulation with metric '{metric}' at outlet for project '{project}'"
            )
        return SimulationGroup([str(r[0]) for r in rows], self)
