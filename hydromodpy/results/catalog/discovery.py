"""Reference resolution and Run/Group discovery.

A reference names a result directory the way the project tree names it:

- a run directory name: ``baseline.v2``, ``J0001-base``,
  ``calibration``. It is the directory ``runs/<name>`` and nothing else: the
  bare name is version 1, never "the latest version".
- a relative directory: ``runs/<name>``, ``sessions/<name>`` or
  ``sessions/<name>/trials/<nnnn>``.
- an id: a full ``sim_id`` or a prefix of at least four hex characters.
- a selector: ``@last``, ``@last~N``, ``@best:METRIC``, ``@worst:METRIC``,
  ``@running``. A selector can be narrowed to one site.

Two resolvers read these forms. :class:`DiscoveryMixin` answers for a
:class:`~hydromodpy.results.catalog.Catalog`, from the index, and returns a
``sim_id``. :func:`resolve_rel_dir` answers from the project tree, returns a
relative directory, and opens the index only for an id or a selector: a verb
that moves a directory (delete, rename, rerun, tag) needs no index to find it.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from hydromodpy.core.state.paths import (
    catalog_path_for,
    parse_rel_dir,
    project_roots_under,
    run_dir_rel,
    runs_dir_for,
)
from hydromodpy.results.catalog.constants import (
    MESH_ENGINE_SQL,
    UnrankedMetricError,
    metric_rank_sql,
    metric_sense,
)
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.metric_rule import HEADLINE_WINDOW
from hydromodpy.results.trash import TrashedEntry, list_trash

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
_SELECTOR_FORCE = (
    "name the run by its directory, narrow the selector with --site, or pass "
    "mixed_windows=True to resolve() to rank them anyway"
)
"""How a selector says to force it: the verbs that take one have no ``--mixed-windows``."""

RULE_METRIC_SQL = (
    "m.metric_rule_version IS NOT NULL "
    f"AND m.window_name = '{HEADLINE_WINDOW}' "
    "AND m.station_id IS NOT DISTINCT FROM s.score_station "
    "AND m.variable IS NOT DISTINCT FROM s.score_variable"
)
"""A metric row scored under the run's metric rule, in the headline period, at the
station and on the variable its headline score was read: one row per metric and run."""


def short_id(sim_id: str | UUID) -> str:
    """Return the first 8 hex characters of a simulation UUID (Git-style)."""
    return str(sim_id)[:8]


class ReferenceResolutionError(Exception):
    """Base class for catalog reference resolution failures.

    Deliberately not a :class:`KeyError`: that subclassing doubled the quotes
    in error rendering and collapsed not-found and ambiguous into one exit code.
    """


class SimulationNotFoundError(ReferenceResolutionError):
    """Raised when a reference does not match any run or session."""


class AmbiguousReferenceError(ReferenceResolutionError):
    """Raised when a reference matches more than one run or session.

    ``candidates`` holds ``(key, label)`` pairs. The key is a ``sim_id`` or a
    relative directory, the label says what it is.
    """

    def __init__(self, ref: str, candidates: list[tuple[str, str | None]]) -> None:
        self.ref = ref
        self.candidates = candidates
        head = candidates[:10]
        lines = "\n".join(f"  {_display_key(key)}  {label or ''}".rstrip() for key, label in head)
        suffix = f"\n  ... and {len(candidates) - 10} more" if len(candidates) > 10 else ""
        super().__init__(
            f"Reference '{ref}' is ambiguous; matches {len(candidates)} "
            f"directories:\n{lines}{suffix}"
        )


def _display_key(key: str) -> str:
    return short_id(key) if _UUID_FULL_RE.match(key) else key


def is_id_like(ref: str) -> bool:
    """Return whether ``ref`` can be a ``sim_id`` or a prefix of one."""
    text = ref.strip()
    if _UUID_FULL_RE.match(text):
        return True
    bare = text.replace("-", "")
    return len(bare) >= _MIN_PREFIX_LEN and bool(_HEX_RE.match(bare))


def reference_rel_dir(ref: str) -> str | None:
    """Return the relative directory a path-shaped reference names, else ``None``.

    ``runs/x``, ``sessions/x`` and ``sessions/x/trials/0004`` name themselves;
    a bare directory name ``x`` names ``runs/x``. A selector names no
    directory. A reference with a ``/`` that is not a result directory raises
    :class:`SimulationNotFoundError` with the forms to write.
    """
    text = str(ref).strip()
    if not text or text.startswith("@"):
        return None
    if "/" in text:
        try:
            return parse_rel_dir(text).as_posix()
        except ValueError as exc:
            raise SimulationNotFoundError(str(exc)) from exc
    try:
        return run_dir_rel(text)
    except ValueError:
        return None


def _versions_on_disk(project_root: Path, rel_dir: str) -> list[str]:
    """Return the run directories that are versions of the stem of ``rel_dir``."""
    parsed = parse_rel_dir(rel_dir)
    if parsed.kind != "run":
        return []
    stem = split_stem_version(parsed.name)[0]
    runs = runs_dir_for(Path(project_root))
    if not runs.is_dir():
        return []
    return sorted(
        run_dir_rel(entry.name)
        for entry in runs.iterdir()
        if entry.is_dir() and split_stem_version(entry.name)[0] == stem
    )


def resolve_rel_dir(
    project_root: Path,
    ref: str,
    *,
    site: str | None = None,
    unambiguous: bool = False,
) -> str:
    """Return the relative directory ``ref`` names in the project tree.

    A directory name or a relative directory is checked on disk, without the
    index. An id or a selector is answered by the index, opened read-only.
    With ``unambiguous``, a bare run name whose stem has other versions on
    disk is refused with the list: a purge must name ``x.v2`` or ``x``
    knowing the other one exists. A hex-looking name that is also the prefix
    of another run's id is refused the same way.

    Raises :class:`SimulationNotFoundError` when nothing answers and
    :class:`AmbiguousReferenceError` when several directories do.
    """
    root = Path(project_root)
    text = str(ref).strip()
    if not text:
        raise SimulationNotFoundError("Empty reference")
    rel_dir = reference_rel_dir(text)
    on_disk = rel_dir is not None and (root / rel_dir).is_dir()
    by_id = _rel_dirs_by_index(root, text, site=site) if not on_disk or is_id_like(text) else []

    if on_disk and rel_dir is not None:
        others = [candidate for candidate in by_id if candidate != rel_dir]
        if others:
            raise AmbiguousReferenceError(
                text,
                [(rel_dir, "directory")] + [(other, "id prefix") for other in others],
            )
        if unambiguous and "/" not in text and split_stem_version(text)[1] is None:
            versions = _versions_on_disk(root, rel_dir)
            if len(versions) > 1:
                raise AmbiguousReferenceError(text, [(version, "version") for version in versions])
        return rel_dir
    if len(by_id) == 1:
        return by_id[0]
    if len(by_id) > 1:
        raise AmbiguousReferenceError(text, [(candidate, None) for candidate in by_id])
    if rel_dir is not None:
        raise SimulationNotFoundError(
            f"Reference '{text}' not found: {root / rel_dir} is not a directory. "
            "Run `hmp catalog ls` to list the runs."
        )
    raise SimulationNotFoundError(f"Reference '{text}' not found in {root}.")


def _rel_dirs_by_index(project_root: Path, ref: str, *, site: str | None) -> list[str]:
    """Answer an id or a selector from the index; ``[]`` when it cannot."""
    if not (ref.startswith("@") or is_id_like(ref)):
        return []
    if not catalog_path_for(project_root).is_file():
        if ref.startswith("@"):
            raise SimulationNotFoundError(
                f"'{ref}' is answered by the index and {project_root} has none yet. "
                "Run `hmp catalog reindex` or name the directory."
            )
        return []
    from hydromodpy.results.catalog.facade import Catalog

    with Catalog(project_root) as catalog:
        if ref == "@running":
            return [catalog._newest_running(project=None, site=site)[0]]
        if ref.startswith("@"):
            return [catalog.rel_dir_of(catalog.resolve(ref, site=site))]
        return [catalog.rel_dir_of(sid) for sid in catalog._ids_matching(ref)]


def resolve_trashed(project_root: Path, ref: str) -> TrashedEntry:
    """Return the trash entry ``ref`` names.

    ``ref`` is the name the trash listing shows
    (``runs__baseline_daily.v2@20261014T093000``), or the directory the entry
    came from (``baseline_daily.v2``, ``sessions/calibration``). A directory
    trashed several times is ambiguous and the entries are listed.
    """
    text = str(ref).strip()
    entries = list_trash(Path(project_root))
    exact = [entry for entry in entries if entry.name == text]
    if exact:
        return exact[0]
    rel_dir = reference_rel_dir(text)
    matches = [entry for entry in entries if rel_dir is not None and entry.rel_dir == rel_dir]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AmbiguousReferenceError(
            text, [(entry.name, f"trashed {entry.trashed_at:%Y-%m-%d %H:%M}") for entry in matches]
        )
    raise SimulationNotFoundError(
        f"Nothing named '{text}' in the trash of {project_root}. "
        "Run `hmp catalog trash` to list it."
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
        site: str | None = None,
        mixed_windows: bool = False,
    ) -> str:
        """Resolve a user reference to a simulation UUID.

        Accepted forms, tried in order:

        1. ``@``-selectors: ``@last``, ``@last~N`` (N-th newest completed),
           ``@best:METRIC`` / ``@worst:METRIC`` (the metric scored under the
           run's metric rule; add ``@STATION`` to read another station),
           ``@running``. ``site`` narrows a selector to the runs of one site.
           Best follows the direction of the metric: highest ``nse``, lowest
           ``rmse``, ``pbias`` closest to zero (see
           :data:`~hydromodpy.results.catalog.constants.METRIC_SENSE`).
           ``@best`` and ``@worst`` rank scores, so the runs they rank must
           share one rule (station, variable, window, rule version; with
           ``@STATION``, all but the station): otherwise they raise
           :class:`~hydromodpy.results.run.sealed.MixedWindowsError`, unless
           ``mixed_windows`` is true.
        2. A relative directory: ``runs/<name>``, ``sessions/<name>``,
           ``sessions/<name>/trials/<nnnn>``.
        3. Full UUID (36 chars with dashes).
        4. UUID prefix of >= 4 hex characters, or the run directory name
           ``<name>`` (``runs/<name>``). A hex word that is both a prefix and
           a name of two different runs raises :class:`AmbiguousReferenceError`.

        Raises :class:`SimulationNotFoundError` when nothing matches, with the
        closest directory names suggested.
        """
        ref_s = str(ref).strip()
        if not ref_s:
            raise SimulationNotFoundError("Empty reference")
        if ref_s.startswith("@"):
            return self._resolve_selector(
                ref_s[1:], project=project, site=site, mixed_windows=mixed_windows
            )

        if "/" in ref_s:
            rel_dir = reference_rel_dir(ref_s)
            sid = self._sim_id_at(rel_dir, project) if rel_dir else None
            if sid is None:
                raise SimulationNotFoundError(self._not_found_message(ref_s, project))
            return sid

        candidates = dict.fromkeys(self._ids_matching(ref_s))
        rel_dir = reference_rel_dir(ref_s)
        by_name = self._sim_id_at(rel_dir, project) if rel_dir else None
        if by_name is not None:
            candidates.setdefault(by_name)
        if len(candidates) == 1:
            return next(iter(candidates))
        if len(candidates) > 1:
            raise AmbiguousReferenceError(
                ref_s, [(sid, self.rel_dir_of(sid)) for sid in candidates]
            )
        raise SimulationNotFoundError(self._not_found_message(ref_s, project))

    def _ids_matching(self, ref: str) -> list[str]:
        """Return the ``sim_id`` values ``ref`` names as a full id or an id prefix."""
        text = str(ref).strip()
        if _UUID_FULL_RE.match(text):
            row = self._backend.fetch_one(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
                [text.lower()],
            )
            return [str(row[0])] if row else []
        if not is_id_like(text):
            return []
        rows = self._backend.fetch_all(
            "SELECT CAST(sim_id AS VARCHAR) FROM simulations "
            "WHERE REPLACE(CAST(sim_id AS VARCHAR), '-', '') LIKE ? || '%' "
            "ORDER BY created_at DESC",
            [text.replace("-", "").lower()],
        )
        return [str(row[0]) for row in rows]

    def rel_dir_of(self, sim_id: str | UUID) -> str:
        """Return the relative directory the index holds for ``sim_id``.

        A sealed run answers from ``simulations``; a case still running
        answers from ``cases``, where its attempt recorded the id.
        """
        row = self._backend.fetch_one(
            "SELECT rel_dir FROM simulations WHERE CAST(sim_id AS VARCHAR) = ? "
            "UNION ALL SELECT rel_dir FROM cases WHERE sim_id = ? LIMIT 1",
            [str(sim_id), str(sim_id)],
        )
        if row is None or not row[0]:
            raise SimulationNotFoundError(f"No run with sim_id {short_id(sim_id)} in the index.")
        return str(row[0])

    def _newest_running(self, *, project: str | None, site: str | None) -> tuple[str, str | None]:
        """Return ``(rel_dir, sim_id)`` of the newest running case.

        A running attempt is a case, not a sealed run: it is read from
        ``cases``, and its ``sim_id`` is ``None`` until the run has one.
        """
        scope_sql, scope_params = _scope_clause(project, site)
        row = self._backend.fetch_one(
            "SELECT s.rel_dir, s.sim_id FROM cases s "
            f"WHERE s.status = 'running'{scope_sql} "
            "ORDER BY s.started_at DESC NULLS LAST LIMIT 1",
            scope_params,
        )
        if row is None:
            raise SimulationNotFoundError(f"No running run{_scope_words(project, site)}")
        return str(row[0]), None if row[1] is None else str(row[1])

    def _sim_id_at(self, rel_dir: str, project: str | None) -> str | None:
        sql = "SELECT CAST(sim_id AS VARCHAR) FROM simulations WHERE rel_dir = ?"
        params: list[str] = [rel_dir]
        if project is not None:
            sql += " AND project = ?"
            params.append(project)
        row = self._backend.fetch_one(sql, params)
        return str(row[0]) if row else None

    def _resolve_selector(
        self, body: str, *, project: str | None, site: str | None, mixed_windows: bool
    ) -> str:
        """Resolve an ``@``-selector body (the part after ``@``)."""
        scope_sql, scope_params = _scope_clause(project, site)
        scope = _scope_words(project, site)
        last_match = _LAST_SELECTOR_RE.match(body)
        if last_match:
            offset = int(last_match.group(1) or 0)
            row = self._backend.fetch_one(
                "SELECT CAST(s.sim_id AS VARCHAR) FROM simulations s "
                "JOIN statuses st ON s.status_id = st.id "
                f"WHERE st.code = 'completed'{scope_sql} "
                "ORDER BY s.created_at DESC LIMIT 1 OFFSET ?",
                [*scope_params, offset],
            )
            if row:
                return str(row[0])
            raise SimulationNotFoundError(f"No completed run for '@{body}'{scope}")

        rank_match = _RANK_SELECTOR_RE.match(body)
        if rank_match:
            kind, remainder = rank_match.group(1), rank_match.group(2).strip()
            metric, _, station = remainder.partition("@")
            metric = metric.strip()
            station = station.strip() or None
            try:
                order = metric_rank_sql(metric, best=kind == "best")
            except UnrankedMetricError as exc:
                raise SimulationNotFoundError(f"'@{body}': {exc}") from exc
            sids = self._ranked_sim_ids(
                metric,
                order,
                station=station,
                project=project,
                site=site,
                limit=1,
                mixed_windows=mixed_windows,
                force=_SELECTOR_FORCE,
            )
            if sids:
                return sids[0]
            where = f"at station '{station}'" if station else "under the metric rule"
            raise SimulationNotFoundError(
                f"No completed run with metric '{metric}' {where} for '@{body}'{scope}"
            )

        if body == "running":
            rel_dir, sim_id = self._newest_running(project=project, site=site)
            if sim_id is None:
                raise SimulationNotFoundError(
                    f"The running case {rel_dir} has no sim_id yet. Name its directory."
                )
            return sim_id

        raise SimulationNotFoundError(
            f"Unknown selector '@{body}'. "
            "Known: @last, @last~N, @best:METRIC, @worst:METRIC, @running"
        )

    def _ranked_sim_ids(
        self,
        metric: str,
        order: str,
        *,
        station: str | None,
        project: str | None,
        site: str | None,
        limit: int,
        mixed_windows: bool,
        force: str | None = None,
    ) -> list[str]:
        """Return completed runs ranked on ``metric``, best (or worst) first.

        Without ``station``, the metric is the one scored under the run's
        metric rule, at its gauge and in its window. With ``station``, it is
        the value stored at that station. A missing or non-finite value never
        ranks. The runs that rank must share one rule: the station, the
        variable, the window and the rule version of the ``metrics`` rows.
        Otherwise :class:`~hydromodpy.results.run.sealed.MixedWindowsError` is
        raised, unless ``mixed_windows`` is true; ``force`` says how to force it.
        """
        from hydromodpy.results.run.sealed import FORCE_RANKING, METRICS_RULE, check_one_rule

        scope_sql, scope_params = _scope_clause(project, site)
        rule = ", ".join(f"m.{name}" for name in METRICS_RULE.names)
        sql = (
            f"SELECT CAST(s.sim_id AS VARCHAR), s.rel_dir, {rule} FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            "JOIN metrics m ON s.sim_id = m.sim_id "
            "WHERE st.code = 'completed' AND m.metric_name = ? "
            "AND m.value IS NOT NULL AND isfinite(m.value) "
        )
        params: list = [metric]
        if station is None:
            sql += f"AND {RULE_METRIC_SQL} "
        else:
            sql += "AND m.station_id = ? "
            params.append(station)
        sql += f"{scope_sql} ORDER BY {order}"
        rows = self._backend.fetch_all(sql, [*params, *scope_params])
        if not mixed_windows:
            check_one_rule(
                [dict(zip(METRICS_RULE.names, row[2:], strict=True)) for row in rows],
                metric,
                names=[row[1] for row in rows],
                columns=METRICS_RULE,
                force=force or FORCE_RANKING,
            )
        return [str(row[0]) for row in rows[:limit]]

    def _not_found_message(self, ref: str, project: str | None) -> str:
        """Build a not-found message suggesting the closest directories and tags."""
        context = f" in project '{project}'" if project else ""
        rows = self._backend.fetch_all(
            "SELECT rel_dir FROM simulations WHERE rel_dir IS NOT NULL"
            + (" AND project = ?" if project else ""),
            ([project] if project else []),
        )
        rel_dirs = [str(r[0]) for r in rows]
        names = [parse_rel_dir(rel).name for rel in rel_dirs]
        close = difflib.get_close_matches(ref, [*names, *rel_dirs], n=3, cutoff=0.4)
        if not close:
            tags = [str(r[0]) for r in self._backend.fetch_all("SELECT DISTINCT tag FROM tags")]
            close = difflib.get_close_matches(ref, tags, n=3, cutoff=0.4)
        suggestion = f" Closest: {', '.join(close)}." if close else ""
        return (
            f"Reference '{ref}' not found{context}. Run `hmp catalog ls` to list known runs."
            f"{suggestion}"
        )

    def __getitem__(self, ref: str | UUID) -> Run:
        from hydromodpy.results.run import Run

        sid = self.resolve(ref)
        return Run(sid, self)

    def find(self, *, mixed_windows: bool = False, **filters) -> RunSet:
        """Return the runs that match every filter, newest first.

        Parameters
        ----------
        **filters
            Each keyword narrows the set:

            - ``project``, ``site``, ``site_fingerprint``, ``case_id``,
              ``recipe``, ``rel_dir``, ``name``, ``name_stem``,
              ``config_hash``, ``crs_wkt`` (or ``crs``): exact value of that
              run column.
            - ``solver``, ``solver_category``, ``status``, ``flow_regime``,
              ``mesh_topology``: their code, for example ``solver="modflow6"``
              or ``status="completed"``.
            - ``mesh_engine``: the engine that built the mesh, for example
              ``"voronoi"``, read from the stored configuration.
            - ``tags``: one tag the run carries.
            - ``<metric>_gt``, ``<metric>_gte``, ``<metric>_lt``,
              ``<metric>_lte``: bound on a metric scored under the run's
              metric rule, for example ``nse_gt=0.7``. A bound reads every score
              against one number, so the runs it is applied to must share one
              rule (station, variable, window, rule version): runs that carry
              the metric under different rules raise
              :class:`~hydromodpy.results.run.sealed.MixedWindowsError`.
        mixed_windows
            Apply the bounds although the runs were scored under different
            rules. Refused by default.

        Returns
        -------
        RunSet
            The matching runs. It is empty when nothing matches.

        Raises
        ------
        ValueError
            If a keyword is none of the above, or names a metric the catalog
            does not know (a retired spelling is refused with the name to write).
            The message lists them.
        MixedWindowsError
            If a ``<metric>_gt`` style bound meets runs scored under different
            rules and ``mixed_windows`` is false.

        Examples
        --------
        >>> good = cat.find(
        ...     site="basin_a", status="completed", nse_gt=0.7
        ... )  # doctest: +SKIP
        >>> good.best("nse")  # doctest: +SKIP
        """
        from hydromodpy.results.run.group import RunSet

        query = (
            "SELECT DISTINCT s.sim_id, s.created_at FROM simulations s "
            "JOIN solvers sv ON s.solver_id = sv.id "
            "JOIN statuses st ON s.status_id = st.id "
            "LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id "
            "LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id"
        )
        joins: list[str] = []
        clauses: list[str] = []
        join_params: list = []
        clause_params: list = []
        bounds: list[tuple[str, str]] = []
        bound_clauses: list[str] = []
        bound_params: list = []
        tag_join_added = False

        for key, val in filters.items():
            bound = _metric_bound(key)
            if key == "tags":
                if not tag_join_added:
                    joins.append("JOIN tags tg ON s.sim_id = tg.sim_id")
                    tag_join_added = True
                clauses.append("tg.tag = ?")
                clause_params.append(val)
            elif bound is not None:
                metric, operator = bound
                try:
                    metric_sense(metric)
                except UnrankedMetricError as exc:
                    raise ValueError(f"Filter {key!r}: {exc}") from exc
                alias = f"m_{len(joins)}"
                joins.append(
                    f"JOIN metrics {alias} ON s.sim_id = {alias}.sim_id "
                    f"AND {alias}.metric_name = ? "
                    f"AND {RULE_METRIC_SQL.replace('m.', f'{alias}.')}"
                )
                join_params.append(metric)
                bounds.append((metric, alias))
                bound_clauses.append(f"{alias}.value {operator} ?")
                bound_params.append(val)
            elif key in _CODE_FILTERS:
                clauses.append(f"{_CODE_FILTERS[key]} = ?")
                clause_params.append(val)
            elif key == "mesh_engine":
                clauses.append(f"{MESH_ENGINE_SQL} = ?")
                clause_params.append(val)
            elif key in _COLUMN_FILTERS:
                clauses.append(f"s.{_COLUMN_FILTERS[key]} = ?")
                clause_params.append(val)
            else:
                known = ", ".join(
                    [*_COLUMN_FILTERS, *_CODE_FILTERS, "mesh_engine", "tags"]
                    + ["<metric>_gt", "<metric>_lt", "<metric>_gte", "<metric>_lte"]
                )
                raise ValueError(f"Unknown filter {key!r}. Valid: {known}")

        if bounds and not mixed_windows:
            self._check_bounded_rules(bounds, joins, clauses, join_params + clause_params)
        clauses += bound_clauses
        if joins:
            query += " " + " ".join(joins)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY s.created_at DESC"

        rows = self._backend.fetch_all(query, join_params + clause_params + bound_params)
        return RunSet([str(r[0]) for r in rows], self)

    def _check_bounded_rules(
        self,
        bounds: list[tuple[str, str]],
        joins: list[str],
        clauses: list[str],
        params: list,
    ) -> None:
        """Refuse a ``<metric>_gt`` bound over runs scored under different rules.

        The population is every run that matches the other filters and carries
        the metric under its rule, the runs the bound drops included: one
        threshold means the same thing only under one rule.
        """
        from hydromodpy.results.run.sealed import METRICS_RULE, check_one_rule

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        for metric, alias in bounds:
            rule = ", ".join(f"{alias}.{name}" for name in METRICS_RULE.names)
            rows = self._backend.fetch_all(
                f"SELECT DISTINCT CAST(s.sim_id AS VARCHAR), s.rel_dir, {rule} "
                "FROM simulations s "
                "JOIN solvers sv ON s.solver_id = sv.id "
                "JOIN statuses st ON s.status_id = st.id "
                "LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id "
                "LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id "
                f"{' '.join(joins)}{where}",
                params,
            )
            check_one_rule(
                [dict(zip(METRICS_RULE.names, row[2:], strict=True)) for row in rows],
                metric,
                names=[row[1] for row in rows],
                columns=METRICS_RULE,
            )

    def latest(self, project: str | None = None, *, site: str | None = None) -> Run:
        """Return the most recently created completed run.

        Parameters
        ----------
        project
            Look only at the runs of this project. ``None`` looks at the
            whole catalog.
        site
            Look only at the runs of this site.

        Returns
        -------
        Run
            The newest run whose status is ``completed``.

        Raises
        ------
        KeyError
            If no run is completed in that scope.

        Examples
        --------
        >>> run = hmp.open("~/ws/projects/my_project").latest()  # doctest: +SKIP
        """
        from hydromodpy.results.run import Run

        scope_sql, scope_params = _scope_clause(project, site)
        row = self._backend.fetch_one(
            "SELECT s.sim_id FROM simulations s "
            "JOIN statuses st ON s.status_id = st.id "
            f"WHERE st.code = 'completed'{scope_sql} "
            "ORDER BY s.created_at DESC LIMIT 1",
            scope_params,
        )
        if row is None:
            where = _scope_words(project, site) or " in the catalog"
            raise KeyError(f"No completed simulation{where}")
        return Run(str(row[0]), self)

    def diff(
        self,
        ref_a: str,
        ref_b: str,
        *,
        project: str | None = None,
    ) -> dict:
        """Compare two runs' parameters and metrics.

        Returns ``{"a", "b", "params", "metrics"}``. ``params`` maps each
        differing ``(name, zone)`` to ``(value_a, value_b)``. ``metrics`` maps
        each differing ``(metric, station, variable)`` to one entry per run,
        ``{"value", "window_start", "window_end", "n"}``: the score and the
        window and samples it was computed on. An entry is ``None`` when the
        run holds no such score.
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
                "SELECT metric_name, station_id, variable, value, "
                "window_start, window_end, n_samples FROM metrics "
                "WHERE sim_id = ? AND window_name = ?",
                [sid, HEADLINE_WINDOW],
            )
            return {
                (r[0], r[1], r[2]): {
                    "value": r[3],
                    "window_start": r[4],
                    "window_end": r[5],
                    "n": r[6],
                }
                for r in rows
            }

        def _delta(map_a: dict, map_b: dict) -> dict:
            keys = sorted(set(map_a) | set(map_b), key=lambda k: tuple(str(part) for part in k))
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

    def best(
        self,
        project: str,
        metric: str = "nse",
        *,
        site: str | None = None,
        mixed_windows: bool = False,
    ) -> Run:
        """Return the completed run with the best value of ``metric`` under its rule.

        Best follows the direction of the metric: the highest ``nse``, the
        lowest ``rmse``, the ``pbias`` closest to zero. A metric with no
        declared direction raises
        :class:`~hydromodpy.results.catalog.constants.UnrankedMetricError`.
        Runs scored under different rules (station, variable, window or rule
        version) are not comparable: they raise
        :class:`~hydromodpy.results.run.sealed.MixedWindowsError` unless
        ``mixed_windows`` is true.
        """
        return self.rank(project, metric, n=1, site=site, mixed_windows=mixed_windows)[0]

    def worst(
        self,
        project: str,
        metric: str = "nse",
        *,
        site: str | None = None,
        mixed_windows: bool = False,
    ) -> Run:
        """Return the completed run with the worst value of ``metric`` under its rule.

        The mirror of :meth:`best`, with the same refusal of mixed rules.
        """
        return self.rank(
            project, metric, n=1, best_first=False, site=site, mixed_windows=mixed_windows
        )[0]

    def rank(
        self,
        project: str,
        metric: str = "nse",
        *,
        ascending: bool | None = None,
        n: int = 1,
        best_first: bool = True,
        site: str | None = None,
        mixed_windows: bool = False,
    ) -> RunSet:
        """Return up to ``n`` completed runs ranked on ``metric`` under their metric rule.

        Without ``ascending`` the runs come best first (``best_first=True``)
        or worst first, following the direction of the metric. ``ascending``
        orders on the raw value instead, for a metric with no direction.
        The scores must share one rule: runs scored at different stations, on
        different variables, windows or rule versions raise
        :class:`~hydromodpy.results.run.sealed.MixedWindowsError`, unless
        ``mixed_windows`` is true.
        """
        from hydromodpy.results.run.group import RunSet

        if ascending is None:
            order = metric_rank_sql(metric, best=best_first)
        else:
            order = f"m.value {'ASC' if ascending else 'DESC'}"
        sids = self._ranked_sim_ids(
            metric,
            order,
            station=None,
            project=project,
            site=site,
            limit=n,
            mixed_windows=mixed_windows,
        )
        if not sids:
            raise KeyError(
                f"No completed simulation with metric '{metric}' under its metric rule"
                f"{_scope_words(project, site)}"
            )
        return RunSet(sids, self)


_COLUMN_FILTERS: dict[str, str] = {
    "project": "project",
    "site": "site",
    "site_fingerprint": "site_fingerprint",
    "case_id": "case_id",
    "recipe": "recipe",
    "rel_dir": "rel_dir",
    "name": "name",
    "name_stem": "name_stem",
    "config_hash": "config_hash",
    "crs_wkt": "crs_wkt",
    "crs": "crs_wkt",
}
"""``find`` keyword -> column of ``simulations`` it matches exactly."""

_CODE_FILTERS: dict[str, str] = {
    "solver": "sv.code",
    "solver_category": "sv.category",
    "status": "st.code",
    "flow_regime": "fr.code",
    "mesh_topology": "mt.code",
}
"""``find`` keyword -> code column of a dimension table."""

_METRIC_OPERATORS: tuple[tuple[str, str], ...] = (
    ("_gte", ">="),
    ("_lte", "<="),
    ("_gt", ">"),
    ("_lt", "<"),
)


def _metric_bound(key: str) -> tuple[str, str] | None:
    """Return ``(metric, operator)`` for a ``<metric>_gt`` style keyword."""
    for suffix, operator in _METRIC_OPERATORS:
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)], operator
    return None


def _scope_clause(project: str | None, site: str | None) -> tuple[str, list[str]]:
    """Return the ``AND ...`` clause and parameters narrowing to a project and a site."""
    sql = ""
    params: list[str] = []
    if project is not None:
        sql += " AND s.project = ?"
        params.append(project)
    if site is not None:
        sql += " AND s.site = ?"
        params.append(site)
    return sql, params


def _scope_words(project: str | None, site: str | None) -> str:
    parts = []
    if project is not None:
        parts.append(f"project '{project}'")
    if site is not None:
        parts.append(f"site '{site}'")
    return f" in {' and '.join(parts)}" if parts else ""


__all__ = [
    "AmbiguousReferenceError",
    "DiscoveryMixin",
    "RULE_METRIC_SQL",
    "ReferenceResolutionError",
    "SimulationNotFoundError",
    "is_id_like",
    "iter_project_catalog_roots",
    "reference_rel_dir",
    "resolve_rel_dir",
    "resolve_trashed",
    "short_id",
]
