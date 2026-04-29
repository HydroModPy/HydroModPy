"""Reference resolution and Run/Group discovery.

``resolve`` is the canonical lookup that turns a user reference (full UUID,
prefix, or ``name`` within a project) into a simulation ``sim_id``.
``__getitem__`` / ``find`` / ``latest`` / ``best`` build :class:`Run` and
:class:`SimulationGroup` views on top of it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from hydromodpy.results.run import Run
    from hydromodpy.results.simulation_group import SimulationGroup

_MIN_PREFIX_LEN = 4
_UUID_FULL_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)


def short_id(sim_id: str | UUID) -> str:
    """Return the first 8 hex characters of a simulation UUID (Git-style)."""
    return str(sim_id)[:8]


class SimulationNotFoundError(KeyError):
    """Raised when a reference does not match any simulation in the catalog."""


class AmbiguousReferenceError(KeyError):
    """Raised when a UUID prefix matches more than one simulation."""

    def __init__(self, ref: str, candidates: list[tuple[str, str | None]]) -> None:
        self.ref = ref
        self.candidates = candidates
        head = candidates[:10]
        lines = "\n".join(f"  {short_id(sid)}  {name or '(no name)'}" for sid, name in head)
        suffix = f"\n  … and {len(candidates) - 10} more" if len(candidates) > 10 else ""
        super().__init__(
            f"Reference '{ref}' is ambiguous; matches {len(candidates)} "
            f"simulations:\n{lines}{suffix}"
        )


class DiscoveryMixin:
    """Reference-resolution and view-builder methods for :class:`SimulationCatalog`.

    Relies on ``self._db``.
    """

    def resolve(
        self,
        ref: str | UUID,
        *,
        project: str | None = None,
    ) -> str:
        """Resolve a user reference to a simulation UUID.

        Accepts three forms, tried in order:

        1. Full UUID (with dashes, 36 chars).
        2. UUID prefix of ≥ 4 hex characters (no dashes). Must match a single
           simulation globally; raises :class:`AmbiguousReferenceError`
           otherwise.
        3. Exact ``name`` within ``project`` - requires the ``project``
           keyword.

        Raises :class:`SimulationNotFoundError` when nothing matches.
        """
        ref_s = str(ref).strip()
        if not ref_s:
            raise SimulationNotFoundError("Empty reference")

        if _UUID_FULL_RE.match(ref_s):
            row = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
                [ref_s.lower()],
            ).fetchone()
            if row:
                return str(row[0])

        ref_nodash = ref_s.replace("-", "").lower()
        if _HEX_RE.match(ref_nodash) and len(ref_nodash) >= _MIN_PREFIX_LEN:
            rows = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR), name FROM simulations "
                "WHERE REPLACE(CAST(sim_id AS VARCHAR), '-', '') LIKE ? || '%'",
                [ref_nodash],
            ).fetchall()
            if len(rows) == 1:
                return str(rows[0][0])
            if len(rows) > 1:
                raise AmbiguousReferenceError(
                    ref_s,
                    [(str(r[0]), r[1]) for r in rows],
                )

        if project is not None:
            row = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE project = ? AND name = ?",
                [project, ref_s],
            ).fetchone()
            if row:
                return str(row[0])
        else:
            rows = self._db.execute(
                "SELECT CAST(sim_id AS VARCHAR), project FROM simulations WHERE name = ?",
                [ref_s],
            ).fetchall()
            if len(rows) == 1:
                return str(rows[0][0])
            if len(rows) > 1:
                raise AmbiguousReferenceError(
                    ref_s,
                    [(str(r[0]), f"{ref_s} (project={r[1]})") for r in rows],
                )

        where = f"'{ref_s}'"
        context = f" in project '{project}'" if project else ""
        raise SimulationNotFoundError(
            f"Reference {where} not found{context}. "
            "Try `hmp list <project>` or `catalog.simulations` to see known runs."
        )

    def __getitem__(self, ref: str | UUID) -> Run:
        from hydromodpy.results.run import Run

        sid = self.resolve(ref)
        return Run(sid, self)

    def find(self, **filters) -> SimulationGroup:
        from hydromodpy.results.simulation_group import SimulationGroup

        query = "SELECT DISTINCT s.sim_id FROM simulations s"
        joins: list[str] = []
        clauses: list[str] = []
        # SQL binds positional placeholders in the order they appear in the
        # query text (JOINs before WHEREs), so keep the two bind lists separate
        # instead of one ordered by filter-insertion.
        join_params: list = []
        clause_params: list = []

        for key, val in filters.items():
            if key == "tags":
                clauses.append("list_contains(s.tags, ?)")
                clause_params.append(val)
            elif key.endswith("_gt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id AND {alias}.metric_name = ?"
                )
                join_params.append(metric)
                clauses.append(f"{alias}.value > ?")
                clause_params.append(val)
            elif key.endswith("_lt"):
                metric = key[:-3]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id AND {alias}.metric_name = ?"
                )
                join_params.append(metric)
                clauses.append(f"{alias}.value < ?")
                clause_params.append(val)
            elif key.endswith("_gte"):
                metric = key[:-4]
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id AND {alias}.metric_name = ?"
                )
                join_params.append(metric)
                clauses.append(f"{alias}.value >= ?")
                clause_params.append(val)
            elif key == "crs":
                clauses.append("s.crs_wkt = ?")
                clause_params.append(val)
            elif key in (
                "project",
                "solver",
                "solver_category",
                "flow_regime",
                "status",
                "name",
                "crs_wkt",
                "mesh_topology",
                "geographic_fingerprint",
            ):
                clauses.append(f"s.{key} = ?")
                clause_params.append(val)
            else:
                raise ValueError(f"Unknown filter: '{key}'")

        if joins:
            query += " " + " ".join(joins)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY s.created_at DESC"

        rows = self._db.execute(query, join_params + clause_params).fetchall()
        sim_ids = [str(r[0]) for r in rows]
        return SimulationGroup(sim_ids, self)

    def latest(self, project: str) -> Run:
        from hydromodpy.results.run import Run

        row = self._db.execute(
            "SELECT sim_id FROM simulations "
            "WHERE project = ? AND status = 'completed' "
            "ORDER BY created_at DESC LIMIT 1",
            [project],
        ).fetchone()
        if row is None:
            raise KeyError(f"No completed simulation for project '{project}'")
        return Run(str(row[0]), self)

    def best(self, project: str, metric: str = "nse") -> Run:
        from hydromodpy.results.run import Run

        row = self._db.execute(
            "SELECT s.sim_id FROM simulations s "
            "JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE s.project = ? AND s.status = 'completed' "
            "AND m.metric_name = ? "
            "ORDER BY m.value DESC LIMIT 1",
            [project, metric],
        ).fetchone()
        if row is None:
            raise KeyError(
                f"No completed simulation with metric '{metric}' for project '{project}'"
            )
        return Run(str(row[0]), self)
