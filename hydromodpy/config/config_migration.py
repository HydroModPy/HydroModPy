"""One-shot TOML config migration for the simulation-management refactor.

Rewrites legacy ``[simulation]`` keys in place, preserving comments and layout:

- ``on_collision`` -> ``if_exists``, ``"replace"`` becoming ``"version"``
- ``run_id`` -> ``name`` (when ``name`` is not already set)
- ``[simulation.results.export]`` -> top-level ``[export]``
- ``[export.variables]`` boolean submodel (``head``, ``concentration``,
  ``derived``, and the dead ``budget``/``pathlines`` toggles) -> flat
  ``export.variables`` list of the names it turned on
- ``export.times`` -> ``export.time`` (when ``time`` is not already set)
- the ``[export]`` table of format toggles and ``[[export.artifacts]]`` -> one
  ``[[export]]`` request per toggle and per artifact; a table with every
  format off wrote nothing and is dropped without a word
- ``[display.overrides.<figure>] timestep`` -> ``time``, and the dotted
  calibration phase override ``"display.overrides.<figure>.timestep"`` ->
  ``"display.overrides.<figure>.time"``
- ``[modflow6.tgrid]`` and ``[modflownwt.tgrid]`` dropped: neither backend
  read them
- ``solver_scratch`` and ``persistence.save_lock`` dropped: both drove
  nothing. The solver scratch directory is ``<project>/.hmp/scratch`` and
  no run option writes the lockfile.
- ``[modflow6.sgrid.vertical]`` and ``[modflownwt.sgrid.vertical]`` ->
  ``[domain.layers]``, which every solver reads. When both are written, the
  table of the flow solver is kept (the first solver of the first flow
  process, else ``solver.backend``, else MODFLOW 6) and the other is dropped
  with a line saying whether it held other values. An existing
  ``[domain.layers]`` wins over both. The dotted override
  ``"<solver>.sgrid.vertical.<key>"`` of a calibration phase ->
  ``"domain.layers.<key>"``, under the same rule. The paths come from
  :data:`MOVED_TABLES`, which the changes page of the docs reads too.
- ``geographic.bottom_path`` -> one ``[[data.substratum.sources]]`` entry,
  ``[domain.depth_model]`` left as it is (the old key was never read)
- ``[simulation.results.derived]`` and ``[simulation.results.budget]`` dropped,
  whatever they held: a run keeps its whole per-cell budget and rebuilds every
  derived field on read, so neither table has anything left to switch
- ``maximal_flowing_steps`` and ``minimal_dry_steps`` of a network output's
  ``extent`` table, of ``[display.overrides.network_extent_bounds_map]`` and of
  the dotted phase override of that figure -> ``maximal_flowing_duration`` and
  ``minimal_dry_duration``: ``N`` timesteps become ``N`` times the
  ``[simulation.time]`` step (``2`` monthly steps are ``"2 months"``). A file
  that does not hold its step is left with the reason
- ``roptim_max`` of a network output under ``[calibration.outputs.<name>]``
  dropped when it is 2, the paper's bound, which ``validity_length = "auto"``
  reproduces; any other value is refused, since a ratio has no length without
  the cell size of the run
- ``[workspace] project_root``, ``[display] output_dir`` and
  ``[calibration] rerun_best_with_outputs`` dropped, ``simulation.if_exists =
  "replace"`` rewritten as ``"version"``: the loader refuses each of them with
  the line to delete, and only ``fix_config_file`` makes the edit. The read
  path keeps refusing, so a file that says them is told. ``[site]`` is never
  written here: it names the catchment, which only the user knows.

This is a migration tool, not a backward-compat shim: the runtime model itself
never accepts the old keys (``extra="forbid"``). ``migrate_config_doc`` and
:data:`RENAMED_KEYS` are the document-to-document transforms; two callers wrap
them. ``fix_config_file`` (reached through ``hmp doctor --fix-config``) rewrites a
file on disk once, so a project TOML catches up for good.
``migrate_config_doc_on_load`` runs the same transforms in memory on a payload
already parsed by a caller, without touching the file it came from, and warns once
per key and per file. ``HydroModPyConfig.from_toml`` calls it on the raw payload,
before validation, so a config written for an earlier schema still loads without
the doctor having run on it first. The calibration loader reaches it through the
root-config provider, since the calibration layer does not import this one.

Deprecation
-----------
Every old form says since which version it is old (:data:`DEPRECATION_DELAY_MINORS`
and :func:`old_forms`). A form keeps loading for two minor versions, the one that
retired it included, then it leaves this module:
``tests/unit/config/test_config_migration.py`` fails when one outlives its delay.
The policy is ``docs/source/about/versions.md``. A rename from now on is one row of
:data:`RENAMED_KEYS`. At the end of its delay the row stays with
``sealed_only=True``, because a run sealed under the old name stays readable for
the whole major line, and only the live file loses it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
from packaging.version import Version

from hydromodpy.core.config_kit.base import warn_old_form
from hydromodpy.core.config_kit.export_spec import RUN_FORMATS, format_from_path
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import is_sealed_run_config
from hydromodpy.core.time import parse_step_spec

_logger = get_logger(__name__)

_SOLVER_SECTIONS = ("modflow6", "modflownwt")

DEPRECATION_DELAY_MINORS = 2
"""How many minor versions an old form loads, the one that retired it included.

``since = "2.3.0"`` loads, with a warning, in 2.3 and in 2.4, and goes in 2.5.
"""

ALPHA_FORM = "2.0.0"
"""``since`` of a form only an alpha wrote. Its delay counts from the first stable version."""


@dataclass(frozen=True)
class OldForm:
    """One old spelling of the grammar: what it was, what it is now, since when.

    ``old`` and ``new`` are written as the path of the document, with ``[*]`` for
    each table of a list and ``{*}`` for the tables under free names. ``new`` is
    ``None`` for a key that left with nothing in its place. ``rewritten`` says that
    this module carries the old form across. A form it does not (a field whose old
    shape has no exact new one) is refused by the loader with what to write instead.
    """

    old: str
    new: str | None
    since: str
    rewritten: bool = True

    @property
    def removal(self) -> str:
        """The first version that may no longer hold this form."""
        major, minor = Version(self.since).release[:2]
        return f"{major}.{minor + DEPRECATION_DELAY_MINORS}.0"

    def outlived_by(self, version: str) -> bool:
        """Whether *version*, a pre-release included, is past the delay of this form."""
        return Version(version).release[:2] >= Version(self.removal).release[:2]


#: The result tables a run no longer reads. A stored config and a user file both
#: drop them, and the docs list them as migrated keys.
RETIRED_RESULTS_TABLES: tuple[str, ...] = (
    "simulation.results.derived",
    "simulation.results.budget",
)


@dataclass(frozen=True)
class TableMove:
    """A table the loader moves, whole, to another path.

    Every key of the table keeps its name under the new path. A calibration phase
    that sets one by its dotted path, ``"<old>.<key>"`` in ``overrides``, is moved
    to ``"<new>.<key>"`` too. The migration below and the docs read the same
    declaration, so the changes page lists the move the loader makes.
    """

    old: str
    new: str
    since: str

    @property
    def section(self) -> str:
        """The top-level section of the old path, the solver that wrote the table."""
        return self.old.split(".", 1)[0]


_LAYERING = "domain.layers"

#: The tables the loader moves to another path: the layering each solver wrote
#: under ``sgrid``, which every solver reads from ``[domain.layers]`` now.
MOVED_TABLES: tuple[TableMove, ...] = tuple(
    TableMove(f"{section}.sgrid.vertical", _LAYERING, since=ALPHA_FORM)
    for section in _SOLVER_SECTIONS
)


def fix_config_file(path: str | Path) -> list[str]:
    """Rewrite legacy ``[simulation]`` keys in ``path`` in place.

    Returns the list of human-readable changes applied (empty when the file is
    already up to date). Raises :class:`FileNotFoundError` when the path is
    missing and :class:`tomlkit.exceptions.ParseError` on malformed TOML.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No TOML file at {path}")

    # utf-8-sig: several configs in this repository carry a BOM, and tomlkit
    # reads it as an empty key on line 1, so the doctor could not fix them.
    doc = tomlkit.parse(path.read_text(encoding="utf-8-sig"))
    changes = migrate_config_doc(doc)
    changes.extend(_migrate_refused_keys(doc))
    changes.extend(_rename_keys(doc, sealed=False))
    if changes:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


def migrate_config_doc(doc: Any) -> list[str]:
    """Apply the legacy ``[simulation]`` key migrations to a parsed doc in place.

    Works on a plain ``dict`` (``tomllib``) or a ``tomlkit`` document, so
    ``fix_config_file`` can rewrite a file while ``migrate_config_doc_on_load``
    migrates an in-memory payload for the read path. Returns the list of
    human-readable changes applied.
    """
    changes: list[str] = _drop_dead_result_options(doc)
    changes.extend(_report_retired_results_tables(doc))
    changes.extend(_move_the_bottom_path(doc))
    changes.extend(_move_the_layering(doc))
    changes.extend(_move_the_phase_layering(doc))
    changes.extend(_flatten_boundary_conditions(doc))
    changes.extend(_drop_the_solver_time_grids(doc))
    changes.extend(_drop_the_validity_ratio(doc))

    simulation = doc.get("simulation")
    if simulation is None:
        return _finish(doc, changes)

    if "on_collision" in simulation:
        value = simulation["on_collision"]
        if "if_exists" not in simulation:
            # "replace" is gone: a run never overwrites an earlier one.
            if value == "replace":
                value = "version"
            simulation["if_exists"] = value
            changes.append(f"simulation.on_collision -> if_exists ({value!r})")
        else:
            changes.append("simulation.on_collision dropped (if_exists already set)")
        del simulation["on_collision"]

    if "run_id" in simulation:
        value = simulation["run_id"]
        if not simulation.get("name"):
            simulation["name"] = value
            changes.append(f"simulation.run_id -> name ({value!r})")
        else:
            changes.append("simulation.run_id dropped (name already set)")
        del simulation["run_id"]

    changes.extend(_promote_export(doc, simulation))
    return _finish(doc, changes)


#: Keys the loader refuses and a file can drop without changing what a run does.
_DROPPED_KEYS: dict[str, str] = {
    "workspace.project_root": (
        "the project root is the folder that holds project.toml, or the folder of the file"
    ),
    "display.output_dir": "figures are written under runs/<run>/figures/",
    "calibration.rerun_best_with_outputs": (
        "the best trial is promoted by default (save_runs = 'best_n')"
    ),
}


def _migrate_refused_keys(doc: Any) -> list[str]:
    """Drop or rewrite the keys the loader refuses, in a file only.

    Not part of :func:`migrate_config_doc`: a load keeps refusing these keys,
    with the line to delete, and ``hmp doctor --fix-config`` makes the edit.
    The calibration phases write the same keys as dotted ``overrides``, and
    those are carried across too.
    """
    changes = _migrate_refused_scope(doc, where="")
    phases = (doc.get("calibration") or {}).get("phases")
    if isinstance(phases, Mapping):
        phases = [phases]
    for index, phase in enumerate(phases or ()):
        overrides = phase.get("overrides") if isinstance(phase, Mapping) else None
        if isinstance(overrides, Mapping):
            where = f"calibration.phases[{index}].overrides."
            changes.extend(_migrate_refused_dotted(overrides, where))
            changes.extend(_migrate_refused_scope(overrides, where=where))
    return changes


def _migrate_refused_scope(scope: Any, *, where: str) -> list[str]:
    """Apply the refused-key rules to one config-shaped table."""
    changes: list[str] = []
    for path, reason in _DROPPED_KEYS.items():
        *parents, key = path.split(".")
        table = _descend(scope, parents)
        if table is None or key not in table:
            continue
        del table[key]
        changes.append(f"{where}{path} dropped ({reason})")
        if not parents:
            continue
        # The section is left empty: a bare header says nothing, so it goes.
        parent = _descend(scope, parents[:-1])
        if parent is not None and not table:
            del parent[parents[-1]]
    simulation = _descend(scope, ["simulation"])
    if simulation is not None and simulation.get("if_exists") == "replace":
        simulation["if_exists"] = "version"
        changes.append(
            f"{where}simulation.if_exists 'replace' -> 'version' (a run is never replaced)"
        )
    return changes


def _migrate_refused_dotted(overrides: Any, where: str) -> list[str]:
    """Apply the refused-key rules to the dotted keys of a phase's overrides."""
    changes: list[str] = []
    for key in list(overrides):
        if str(key) in _DROPPED_KEYS:
            del overrides[key]
            changes.append(f'{where}"{key}" dropped ({_DROPPED_KEYS[str(key)]})')
        elif str(key) == "simulation.if_exists" and overrides[key] == "replace":
            overrides[key] = "version"
            changes.append(f"{where}\"{key}\" 'replace' -> 'version' (a run is never replaced)")
    return changes


def _descend(scope: Any, parents: list[str]) -> Any:
    """Return the nested table at ``parents`` of *scope*, or ``None``."""
    node = scope
    for part in parents:
        node = node.get(part) if isinstance(node, Mapping) else None
    return node if isinstance(node, Mapping) else None


class _CannotRewrite(Exception):
    """A renamed key whose value the doctor cannot carry over; it is left, with the reason."""


@dataclass(frozen=True)
class KeyRename:
    """One key a loader refuses under its old name, and what it is called now.

    ``scope`` is the table that holds it, written as the path of the document:
    ``calibration``, ``calibration.protocol``. ``name[*]`` walks each table of a
    list (``calibration.phases[*]``) and ``{*}`` the tables a table holds under
    free names (``calibration.parameters.{*}``).

    ``convert(value, doc)`` returns the value to write under the new name, or
    raises :class:`_CannotRewrite` with the reason when it cannot decide: the
    doctor then leaves the key and says why.

    ``sealed_drop`` makes the read of a sealed config drop the key instead of
    renaming it, for an option that no longer exists and that a replay of the
    run never needed. ``sealed_drop_unconverted`` drops it only when ``convert``
    cannot decide, so the key falls back to the default of the new one and the
    sealed run still reads.

    ``since`` is the version that retired the old name. ``sealed_only`` ends the
    delay: a live file is refused again and only a sealed config still reads it.
    """

    scope: str
    old: str
    new: str
    convert: Callable[[Any, Any], Any] | None = None
    sealed_drop: bool = False
    sealed_drop_unconverted: bool = False
    since: str = field(kw_only=True)
    sealed_only: bool = False


def _steps_to_duration(value: Any, doc: Any) -> str:
    """Turn a count of timesteps into the duration it spanned, in the step's own unit.

    The extent rules of a network output were counts of timesteps and are now
    durations. ``N`` steps of the ``[simulation.time]`` step are written as
    ``N`` times that step (``2`` monthly steps are ``"2 months"``), which the run
    converts back to exactly ``N`` steps. A file that does not carry its step,
    because ``base_config`` does, cannot be converted.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _CannotRewrite(f"{value!r} is not a count of timesteps")
    simulation = doc.get("simulation") if isinstance(doc, Mapping) else None
    time = simulation.get("time") if isinstance(simulation, Mapping) else None
    if not isinstance(time, Mapping) or time.get("step_value") is None:
        raise _CannotRewrite(
            "the timestep is not in this file ([simulation.time] step_value), so the count "
            "cannot be turned into a duration; write the duration, such as '1 month'"
        )
    if _a_phase_sets_the_step(doc):
        raise _CannotRewrite(
            "a phase overrides the timestep, so the count has no single duration; write "
            "the duration, such as '1 month'"
        )
    try:
        step, unit = parse_step_spec(_plain(time["step_value"]), _plain(time.get("step_unit")))
    except ValueError as exc:
        raise _CannotRewrite(f"the timestep cannot be read ({exc})") from exc
    count = value * step
    return f"{count} {unit}{'' if count == 1 else 's'}"


def _a_phase_sets_the_step(doc: Any) -> bool:
    """Whether a calibration phase overrides ``simulation.time.step_value`` or ``step_unit``."""
    for _, phase in _tables_at(doc, "calibration.phases[*]"):
        overrides = phase.get("overrides")
        if isinstance(overrides, Mapping) and any(
            str(key).startswith("simulation.time.step") for key in overrides
        ):
            return True
    return False


_EXTENT_RULE_SCOPES = (
    "calibration.outputs.{*}.extent",
    "display.overrides.network_extent_bounds_map",
    "calibration.phases[*].overrides.display.overrides.network_extent_bounds_map",
)
"""Where the two extent rules are written: the output, the figure, a phase's figure."""

_EXTENT_RULE_KEYS = (
    ("maximal_flowing_steps", "maximal_flowing_duration"),
    ("minimal_dry_steps", "minimal_dry_duration"),
)

RENAMED_KEYS: tuple[KeyRename, ...] = (
    KeyRename("calibration", "max_iter", "max_trials", since=ALPHA_FORM),
    KeyRename("calibration.phases[*]", "max_iter", "max_trials", since=ALPHA_FORM),
    KeyRename("calibration.protocol", "steady_max_iter", "steady_max_trials", since=ALPHA_FORM),
    KeyRename(
        "calibration.protocol", "transient_max_iter", "transient_max_trials", since=ALPHA_FORM
    ),
    KeyRename("calibration", "tolerance", "precision", since=ALPHA_FORM),
    KeyRename("calibration.phases[*]", "tolerance", "precision", since=ALPHA_FORM),
    KeyRename("calibration.protocol", "steady_tolerance", "steady_precision", since=ALPHA_FORM),
    KeyRename(
        "calibration.protocol", "transient_tolerance", "transient_precision", since=ALPHA_FORM
    ),
    KeyRename("calibration.parameters.{*}", "transform", "search_space", since=ALPHA_FORM),
    KeyRename("calibration.parameters.{*}", "prior", "sampling", since=ALPHA_FORM),
    KeyRename("calibration.objective_blocks[*]", "transform", "cost_transform", since=ALPHA_FORM),
    KeyRename("calibration", "optimizer_kwargs", "method_options", since=ALPHA_FORM),
    KeyRename("calibration.phases[*]", "optimizer_kwargs", "method_options", since=ALPHA_FORM),
    KeyRename(
        "calibration.protocol", "steady_engine_options", "steady_method_options", since=ALPHA_FORM
    ),
    KeyRename(
        "calibration.protocol",
        "transient_engine_options",
        "transient_method_options",
        since=ALPHA_FORM,
    ),
    *(
        KeyRename(
            scope,
            old,
            new,
            convert=_steps_to_duration,
            sealed_drop_unconverted=True,
            since=ALPHA_FORM,
        )
        for scope in _EXTENT_RULE_SCOPES
        for old, new in _EXTENT_RULE_KEYS
    ),
)
"""Every key a file wrote under another name, with the name that replaced it.

A load reads the old name under the new one and warns; ``hmp doctor --fix-config``
rewrites the file. A sealed run config is renamed on read, in silence, so a run on
disk replays. Each model lists the old key in ``model_refused_keys`` or
``model_legacy_keys``, for a config built in Python; its new field declares
``renamed_from`` so the generated docs list the rename. The two keys of
``[calibration.uncertainty]`` that said how wide an interval is, ``tolerance`` and
``mode``, become one ``cost_margin`` and are rewritten apart
(:func:`_rewrite_cost_margin`): the unit of the new value is read off what the
search scores.
"""


def migrate_sealed_config_doc(doc: Any) -> list[str]:
    """Rename, in memory, the keys a sealed run config wrote under an older name.

    The frozen ``config.toml`` of a run is replayed as it was written, so the
    loader reads it under the names of today. Runs before the protocol is
    expanded: a protocol stage sealed with an old key would otherwise read as a
    contradiction of the protocol that wrote it.
    """
    return _rename_keys(doc, sealed=True)


def _rename_keys(doc: Any, *, sealed: bool) -> list[str]:
    """Apply :data:`RENAMED_KEYS` to *doc*, for a file (the doctor) or a sealed read."""
    changes: list[str] = []
    for rule in RENAMED_KEYS:
        if rule.sealed_only and not sealed:
            continue
        for where, table in _tables_at(doc, rule.scope):
            if rule.old not in table:
                continue
            label = f"{where}.{rule.old}" if where else rule.old
            if sealed and rule.sealed_drop:
                del table[rule.old]
                changes.append(f"{label} dropped (sealed)")
                continue
            if rule.new in table:
                changes.append(f"{label} left: {rule.new!r} is given too, keep one")
                continue
            value = _plain(table[rule.old])
            if rule.convert is not None:
                try:
                    value = rule.convert(value, doc)
                except _CannotRewrite as reason:
                    if sealed and rule.sealed_drop_unconverted:
                        del table[rule.old]
                        changes.append(f"{label} dropped (sealed): {reason}")
                    else:
                        changes.append(f"{label} left: {reason}")
                    continue
            _move_key(table, rule.old, rule.new, value)
            changes.append(f"{label} -> {rule.new}")
    changes.extend(_rename_dotted_figure_overrides(doc, sealed=sealed))
    changes.extend(_rewrite_search_options(doc, sealed=sealed))
    changes.extend(_rewrite_cost_margin(doc, sealed=sealed))
    return changes


def _rename_dotted_figure_overrides(doc: Any, *, sealed: bool) -> list[str]:
    """Rename the extent rules a calibration phase writes as a dotted figure override.

    A phase reaches a figure option by its dotted path, such as
    ``"display.overrides.network_extent_bounds_map.maximal_flowing_steps"``, as
    :func:`_rename_phase_timesteps` does for ``timestep``. The same rule rewrites
    the key and its value; a path whose new name is also written is left.
    """
    figure = _EXTENT_RULE_SCOPES[1]
    rules = {f"{figure}.{rule.old}": rule for rule in RENAMED_KEYS if rule.scope == figure}
    changes: list[str] = []
    for where, phase in _tables_at(doc, "calibration.phases[*]"):
        overrides = phase.get("overrides")
        if not isinstance(overrides, Mapping):
            continue
        for key in list(overrides):
            rule = rules.get(str(key))
            if rule is None:
                continue
            label = f'{where}.overrides."{key}"'
            renamed = f"{figure}.{rule.new}"
            if renamed in overrides:
                changes.append(f"{label} left: {renamed!r} is given too, keep one")
                continue
            try:
                value = rule.convert(_plain(overrides[key]), doc) if rule.convert else None
            except _CannotRewrite as reason:
                if sealed and rule.sealed_drop_unconverted:
                    del overrides[key]
                    changes.append(f"{label} dropped (sealed): {reason}")
                else:
                    changes.append(f"{label} left: {reason}")
                continue
            _move_key(overrides, str(key), renamed, value)
            changes.append(f'{label} -> "{renamed}"')
    return changes


_NETWORK_ESTIMATORS = frozenset({"distance_gap", "distance_mean"})
_PROTOCOL_UNDECIDED = (
    "the search it covers is written by a protocol, so it is not known whether it is scored "
    "by network distances; write cost_margin by hand, '5%' or a length such as '25 m'"
)
_NO_UNIT_TO_WRITE = (
    "an absolute width on a search that is no network distance was in the unit of the "
    "cost, which has no unit to write; write a share such as '5%'"
)


def _rewrite_cost_margin(doc: Any, *, sealed: bool) -> list[str]:
    """Turn ``tolerance`` and ``mode`` of the uncertainty tables into one ``cost_margin``.

    The unit is the one the old mode implied: a relative width, or one left
    unwritten on a search that is no network distance, was a share of the best
    cost (``"5%"``); an absolute one, or one left unwritten on a search scored
    only by network distances, was in metres. A phase read its keys over the
    section's, so the pair a phase read is rewritten into the phase. What the
    doctor cannot decide it leaves, with the reason. A sealed config drops what
    it cannot write: the width only qualifies a calibrated value, it never
    moved one, so the run replays the same.
    """
    calibration = doc.get("calibration") if isinstance(doc, Mapping) else None
    if not isinstance(calibration, Mapping):
        return []
    section = calibration.get("uncertainty")
    inherited = (
        (_plain(section.get("tolerance")), _plain(section.get("mode")))
        if isinstance(section, Mapping)
        else (None, None)
    )
    changes: list[str] = []
    phases = calibration.get("phases")
    if isinstance(phases, Sequence) and not isinstance(phases, str):
        for index, phase in enumerate(phases):
            table = phase.get("uncertainty") if isinstance(phase, Mapping) else None
            if isinstance(table, Mapping) and _has_a_width(table):
                changes.extend(
                    _rewrite_one_margin(
                        phase,
                        table,
                        f"calibration.phases[{index}].uncertainty",
                        inherited,
                        _scored_on_distances(calibration, phase),
                        sealed=sealed,
                    )
                )
    if isinstance(section, Mapping) and _has_a_width(section):
        changes.extend(
            _rewrite_one_margin(
                calibration,
                section,
                "calibration.uncertainty",
                (None, None),
                _scored_on_distances(calibration, None),
                sealed=sealed,
            )
        )
    return changes


def _has_a_width(table: Mapping[str, Any]) -> bool:
    return "tolerance" in table or "mode" in table


@dataclass(frozen=True)
class _Left:
    """A width the doctor cannot rewrite, with the reason."""

    reason: str


def _rewrite_one_margin(
    parent: Any,
    table: Any,
    label: str,
    inherited: tuple[Any, Any],
    distances: bool | None,
    *,
    sealed: bool,
) -> list[str]:
    """Rewrite one uncertainty table, reading the keys it lacks from *inherited*."""
    if "cost_margin" in table:
        return [f"{label}.tolerance left: 'cost_margin' is given too, keep one"]
    tolerance = _plain(table["tolerance"]) if "tolerance" in table else inherited[0]
    mode = _plain(table["mode"]) if "mode" in table else inherited[1]
    verdict = _margin_text(tolerance, mode, distances)
    if isinstance(verdict, _Left):
        if not sealed:
            return [f"{label} left: {verdict.reason}"]
        for key in ("tolerance", "mode"):
            table.pop(key, None)
        return [f"{label}.tolerance dropped (sealed)"]
    kept = "tolerance" in table
    if isinstance(verdict, str):
        if kept:
            _move_key(table, "tolerance", "cost_margin", verdict)
        else:
            table["cost_margin"] = verdict
    table.pop("mode", None)
    table.pop("tolerance", None)
    if isinstance(table, tomlkit.items.InlineTable):
        fresh = tomlkit.inline_table()
        fresh.update(table.unwrap())
        parent["uncertainty"] = fresh
    return [
        f"{label}.tolerance -> cost_margin = {verdict!r}"
        if isinstance(verdict, str)
        else f"{label}.mode dropped"
    ]


def _margin_text(tolerance: Any, mode: Any, distances: bool | None) -> str | _Left | None:
    """Return the ``cost_margin`` the old pair wrote, ``None`` to drop a mode, or why not."""
    if tolerance is None:
        consistent = (mode == "relative" and distances is False) or (
            mode == "absolute" and distances is True
        )
        if consistent:
            return None
        if distances is None:
            return _Left(_PROTOCOL_UNDECIDED)
        return _Left(
            f"mode = {mode!r} wrote no width, and it does not match what this search scores"
        )
    if isinstance(tolerance, bool) or not isinstance(tolerance, int | float):
        return _Left(f"tolerance = {tolerance!r} is not a number")
    if mode == "relative":
        return f"{round(float(tolerance) * 100.0, 10):g}%"
    if distances is None:
        return _Left(_PROTOCOL_UNDECIDED)
    if distances:
        return f"{float(tolerance):g} m"
    if mode == "absolute":
        return _Left(_NO_UNIT_TO_WRITE)
    return f"{round(float(tolerance) * 100.0, 10):g}%"


def _scored_on_distances(
    calibration: Mapping[str, Any], phase: Mapping[str, Any] | None
) -> bool | None:
    """Whether the search a table covers is scored only by network distances, or ``None``.

    Read off the blocks of the document as the loader reads them: a phase scores
    the blocks it names, or its own ``objective``, or every block; a search with
    no block scores the section's ``objective``. A block with a cost transform or a
    normalised cost is no longer in metres. ``None`` when a protocol still has
    to write the phases and the blocks.
    """
    blocks = [
        _plain(block)
        for block in (calibration.get("objective_blocks") or ())
        if isinstance(block, Mapping)
    ]
    if phase is not None:
        named = _plain(phase.get("objective_blocks"))
        if named:
            blocks = [block for block in blocks if block.get("name") in list(named)]
        elif phase.get("objective") is not None:
            return str(_plain(phase["objective"])) in _NETWORK_ESTIMATORS
    if blocks:
        return all(
            block.get("metric") in _NETWORK_ESTIMATORS
            and block.get("cost_transform", "identity") == "identity"
            and not block.get("normalize_cost")
            for block in blocks
        )
    if calibration.get("protocol") is not None and not calibration.get("phases"):
        return None
    return str(_plain(calibration.get("objective", "nse"))) in _NETWORK_ESTIMATORS


@dataclass(frozen=True)
class _SearchScope:
    """A table that writes one search: its method, its options and its budget."""

    scope: str
    method: str
    options: tuple[str, ...]
    budget: str
    default_method: str | None = None


_SEARCH_SCOPES = (
    _SearchScope("calibration", "method", ("method_options", "optimizer_kwargs"), "max_trials"),
    _SearchScope(
        "calibration.phases[*]", "method", ("method_options", "optimizer_kwargs"), "max_trials"
    ),
    _SearchScope(
        "calibration.protocol",
        "steady_method",
        ("steady_method_options", "steady_engine_options"),
        "steady_max_trials",
        default_method="bisection",
    ),
    _SearchScope(
        "calibration.protocol",
        "transient_method",
        ("transient_method_options", "transient_engine_options"),
        "transient_max_trials",
        default_method="scipy_nelder_mead",
    ),
)

# What a method option used to count, by (method, option). The budget of a search
# is `max_trials` and nothing else: an option that counted evaluations moves into
# it, one that counted something else is refused and left for the user.
_BUDGET_OPTIONS = frozenset(
    {("scipy_nelder_mead", "maxfev"), ("cma_es", "max_evaluations"), ("gp_mapping", "max_iter")}
)
_ITERATION_OPTIONS = frozenset({("scipy_nelder_mead", "maxiter"), ("scipy_de", "maxiter")})
_RENAMED_OPTIONS = {("da_mh_gp", "max_iter"): "chain_length"}
_OPTION_NAMES = frozenset({"maxfev", "max_evaluations", "max_iter", "maxiter"})


def _rewrite_search_options(doc: Any, *, sealed: bool) -> list[str]:
    """Rewrite the method options that bounded a search, now that ``max_trials`` does.

    An option that counted evaluations (``maxfev``, ``max_evaluations``, the
    ``max_iter`` of gp_mapping) is moved into the budget of the table that
    writes it, the smaller of the two when both are written, since the search
    stopped at the first one it met. ``maxiter`` counts iterations or
    generations, not evaluations: the doctor leaves it, with the reason. A
    sealed config drops both, because a run on disk is replayed as one solve and
    never searches again. The chain of ``da_mh_gp`` is ``chain_length``.
    """
    changes: list[str] = []
    for search in _SEARCH_SCOPES:
        for where, table in _tables_at(doc, search.scope):
            method = _plain(table.get(search.method)) or search.default_method
            for options_key in search.options:
                options = table.get(options_key)
                if not isinstance(options, Mapping):
                    continue
                prefix = f"{where}.{options_key}" if where else options_key
                before = len(changes)
                for key in [key for key in options if key in _OPTION_NAMES]:
                    label = f"{prefix}.{key}"
                    changes.extend(
                        _rewrite_option(table, options, key, method, label, search, sealed=sealed)
                    )
                if not options:
                    del table[options_key]
                elif len(changes) > before and isinstance(options, tomlkit.items.InlineTable):
                    # A key taken out of an inline table leaves its spacing behind.
                    fresh = tomlkit.inline_table()
                    fresh.update(options.unwrap())
                    table[options_key] = fresh
    return changes


def _rewrite_option(
    table: Any,
    options: Any,
    key: str,
    method: Any,
    label: str,
    search: _SearchScope,
    *,
    sealed: bool,
) -> list[str]:
    """Rewrite one method option, or say why it stays."""
    if not isinstance(method, str):
        return [f"{label} left: no method is written, so it is not known what {key} counted"]
    pair = (method, key)
    if pair in _RENAMED_OPTIONS:
        new = _RENAMED_OPTIONS[pair]
        if new in options:
            return [f"{label} left: {new!r} is given too, keep one"]
        _move_key(options, key, new, _plain(options[key]))
        return [f"{label} -> {new}"]
    if pair in _ITERATION_OPTIONS:
        if sealed:
            del options[key]
            return [f"{label} dropped (sealed)"]
        return [
            f"{label} left: {key} is not an evaluation count (it counts the iterations of "
            f"{method}); set {search.budget} to bound the search and drop {key}"
        ]
    if pair not in _BUDGET_OPTIONS:
        return []
    if sealed:
        del options[key]
        return [f"{label} dropped (sealed)"]
    value = _plain(options[key])
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return [f"{label} left: {value!r} is not a positive integer"]
    declared = _plain(table.get(search.budget))
    kept = min(value, declared) if isinstance(declared, int) else value
    del options[key]
    _set_key(table, search.budget, kept, after=search.method)
    return [f"{label} -> {search.budget} = {kept}"]


def _moved_table(original: Any) -> Any:
    """Return a tomlkit table as an item for its new key, with its comments, or ``None``.

    A ``[header]`` table renders under the name it was parsed with, so its items go
    into a fresh table. An inline table has no header and moves as it is.
    """
    if isinstance(original, tomlkit.items.InlineTable):
        return original
    if not isinstance(original, tomlkit.items.Table):
        return None
    fresh = tomlkit.table()
    for key, item in original.value.body:
        fresh.append(key, item)
    return fresh


def _move_key(table: Any, old: str, new: str, value: Any) -> None:
    """Write *value* under ``new`` where ``old`` stood, and keep the comment of the line.

    A file the doctor rewrites keeps its order, so the key stays under the
    comment that introduces it.
    """
    position = _position(table, old)
    original = table.get(old)
    comment = getattr(getattr(original, "trivia", None), "comment", "") or ""
    del table[old]
    item = _moved_table(original) or _scalar_item(value, comment)
    if position is None or item is None:
        table[new] = value
        if comment.startswith("#") and hasattr(table[new], "comment"):
            table[new].comment(comment[1:].strip())
        return
    table.value._insert_at(position, new, item)


def _set_key(table: Any, key: str, value: Any, *, after: str) -> None:
    """Write ``key`` in *table*, just under ``after`` when the table has it."""
    if key in table:
        table[key] = value
        return
    position = _position(table, after)
    item = _scalar_item(value, "")
    if position is None or item is None:
        table[key] = value
        return
    table.value._insert_at(position + 1, key, item)


def _position(table: Any, key: str) -> int | None:
    """Return where a tomlkit table holds ``key``, or ``None`` for any other mapping."""
    found = getattr(getattr(getattr(table, "value", None), "_map", None), "get", None)
    where = found(key) if callable(found) else None
    return where if isinstance(where, int) and hasattr(table.value, "_insert_at") else None


def _scalar_item(value: Any, comment: str) -> Any:
    """Return *value* as a tomlkit item carrying *comment*, or ``None`` for a table or a list."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    item = tomlkit.item(value)
    if comment.startswith("#"):
        item.comment(comment[1:].strip())
    return item


def _tables_at(doc: Any, scope: str) -> list[tuple[str, Any]]:
    """Return every table of *doc* that *scope* names, with where it sits.

    ``a.b`` descends by name, ``a[*]`` walks the tables of a list, ``{*}`` walks
    the tables under free names. A name that leads to no table is skipped.
    """
    found: list[tuple[str, Any]] = [("", doc)]
    for token in scope.split("."):
        stepped: list[tuple[str, Any]] = []
        for where, node in found:
            if not isinstance(node, Mapping):
                continue
            join = f"{where}." if where else ""
            if token == "{*}":
                stepped.extend(
                    (f"{join}{key}", child)
                    for key, child in node.items()
                    if isinstance(child, Mapping)
                )
            elif token.endswith("[*]"):
                name = token[:-3]
                child = node.get(name)
                members = [child] if isinstance(child, Mapping) else child
                if isinstance(members, Sequence) and not isinstance(members, str):
                    stepped.extend(
                        (f"{join}{name}[{index}]", member)
                        for index, member in enumerate(members)
                        if isinstance(member, Mapping)
                    )
            elif isinstance(node.get(token), Mapping):
                stepped.append((f"{join}{token}", node[token]))
        found = stepped
    return found


def migrate_config_doc_on_load(doc: Any, *, source: str | Path | None = None) -> list[str]:
    """Apply every migration to *doc* in memory, for a config being read, not fixed.

    Meant for ``HydroModPyConfig.from_toml``: called on the freshly parsed
    payload, before Pydantic validation, so a config written for an earlier
    schema still loads. Never touches the file *doc* came from - only
    ``fix_config_file`` writes to disk. Warns once per key and per file, naming
    the old key, the new key and the doctor; says nothing when the document was
    already current.

    A *source* that is the frozen config of a run already on disk
    (:func:`~hydromodpy.core.state.paths.is_sealed_run_config`) is read in silence,
    with the rules of :func:`migrate_sealed_config_doc`: no one edits a sealed file.
    """
    changes = migrate_config_doc(doc)
    sealed = source is not None and is_sealed_run_config(source)
    changes.extend(_rename_keys(doc, sealed=sealed))
    if sealed:
        if changes:
            _logger.debug("%s: sealed config read as renamed: %s", source, "; ".join(changes))
        return changes
    for change in changes:
        if change in _QUIET_CHANGES:
            _logger.debug("%s: %s", source or "config", change)
        else:
            warn_old_form(source, change)
    return changes


def _finish(doc: Any, changes: list[str]) -> list[str]:
    """Run the migrations that must see the promoted top-level tables."""
    export_changes = _migrate_export_variables(doc)
    export_changes.extend(_rename_export_times(doc))
    exploded = _explode_export_table(doc)
    if _EMPTY_EXPORT_DROPPED in exploded:
        # The older spellings of a table that wrote nothing lead nowhere either.
        changes.extend(exploded)
    else:
        changes.extend(export_changes)
        changes.extend(exploded)
    changes.extend(_rename_display_timestep(doc))
    return changes


_EMPTY_EXPORT_DROPPED = "[export] dropped: every format was off, so it wrote nothing"

# Changes that alter nothing a run does. Every sealed run holds such a table in
# its resolved config.toml, and `hmp run --resume` replays it, so saying it on
# every load would be noise.
_QUIET_CHANGES = frozenset({_EMPTY_EXPORT_DROPPED})

# The keys of the [export] table of format toggles, in the order its exports ran.
_EXPORT_TOGGLES = ("netcdf", "vtu", "geotiff", "shapefile", "geopackage")
_EXPORT_TABLE_KEYS = frozenset(
    {
        *_EXPORT_TOGGLES,
        "csv_timeseries",
        "package",
        "output_dir",
        "variables",
        "time",
        "resolution",
        "artifacts",
    }
)
# The selectors a request writing the whole run refuses.
_RUN_REFUSED_KEYS = ("period", "crs", "resolution", "layer")
# The archive of a run (`package = true`, `fmt = "hmp"`, a `.hmp` file) is
# not an export any more: `hmp publish --format tar` writes it from a sealed run.
_ARCHIVE_FORMAT = "hmp"
_ARCHIVE_SUFFIX = ".hmp"
_ARCHIVE_DROPPED = (
    '[export] archive request(s) dropped (package = true, fmt = "hmp", a .hmp file): the '
    "archive of a run is written by hmp publish --format tar, not by an export"
)
_ARTIFACT_KEYS = {
    "var": "variables",
    "fmt": "format",
    "dest": "file",
    "time": "time",
    "layer": "layer",
    "resolution": "resolution",
    "crs": "crs",
    "nodata": "nodata",
}


def _plain(value: Any) -> Any:
    """Return a tomlkit item as the plain Python value it holds."""
    return value.unwrap() if hasattr(value, "unwrap") else value


def _export_block(block: dict[str, Any], *, time: Any, folder: Any) -> dict[str, Any]:
    """Add the time and the folder the old table gave every export."""
    if time is not None and time != "all":
        block["time"] = time
    if folder:
        block["folder"] = folder
    return block


def _is_archive(block: Mapping[str, Any]) -> bool:
    """Return whether an old artifact asked for the archive of the run."""
    if block.get("format") == _ARCHIVE_FORMAT:
        return True
    file = block.get("file")
    return file is not None and str(file).lower().endswith(_ARCHIVE_SUFFIX)


def _artifact_block(artifact: Mapping[str, Any], folder: Any) -> dict[str, Any] | None:
    """Return one ``[[export.artifacts]]`` entry as an ``[[export]]`` request.

    An artifact that asked for the archive of the run returns ``None``: it is
    dropped, and the caller says what writes an archive today.
    """
    block: dict[str, Any] = {}
    for old, new in _ARTIFACT_KEYS.items():
        if old in artifact:
            block[new] = _plain(artifact[old])
    if _is_archive(block):
        return None
    if block.get("variables") == "*":
        block["variables"] = "all"
    time = block.pop("time", None)
    if _writes_the_run(block):
        # The old spec let an archive carry a variable and selectors, and wrote
        # the whole run anyway. The request says so, and keeps no selector.
        block["variables"] = "all"
        for key in _RUN_REFUSED_KEYS:
            block.pop(key, None)
        time = None
    return _export_block(block, time=time, folder=folder)


def _writes_the_run(block: Mapping[str, Any]) -> bool:
    """Return whether a request writes the whole run, by its format or its file."""
    fmt = block.get("format")
    if fmt is None and block.get("file") is not None:
        named = format_from_path(str(block["file"]))
        fmt = named.value if named is not None else None
    return fmt in {run_format.value for run_format in RUN_FORMATS}


def _export_blocks(table: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Return the requests the old ``[export]`` table made, and the archives dropped.

    A format toggle wrote every name of ``variables`` at ``time``, into
    ``output_dir``; ``csv_timeseries`` wrote every series. The defaults are
    the ones the table had. ``package = true`` and the artifacts asking for
    the archive are counted, not kept: no export writes an archive.
    """
    export = _plain(table)
    folder = export.get("output_dir")
    variables = list(export.get("variables", ["head"]))
    time = export.get("time", "last")
    blocks: list[dict[str, Any]] = []
    if export.get("csv_timeseries"):
        blocks.append(
            _export_block({"variables": "all", "format": "csv"}, time=None, folder=folder)
        )
    for toggle in _EXPORT_TOGGLES:
        if not export.get(toggle):
            continue
        block: dict[str, Any] = {"variables": variables, "format": toggle}
        if toggle == "geotiff" and export.get("resolution") is not None:
            block["resolution"] = export["resolution"]
        blocks.append(_export_block(block, time=time, folder=folder))
    dropped = 1 if export.get("package") else 0
    for artifact in export.get("artifacts") or ():
        block = _artifact_block(artifact, folder)
        if block is None:
            dropped += 1
        else:
            blocks.append(block)
    return blocks, dropped


def _explode_export_table(doc: Any) -> list[str]:
    """Rewrite the ``[export]`` table of format toggles as ``[[export]]`` requests.

    The table crossed every format turned on with one variable list and one
    time, and ``[[export.artifacts]]`` described single files with keys of its
    own. Each toggle and each artifact becomes one request. A table with
    every format off and no artifact wrote nothing and is dropped.

    A table holding a key the old table never had is left as it is: it is a
    request written as a table, and the loader says to write ``[[export]]``.
    """
    table = doc.get("export")
    if not isinstance(table, Mapping) or not set(table) <= _EXPORT_TABLE_KEYS:
        return []
    blocks, dropped = _export_blocks(table)
    changes = [_ARCHIVE_DROPPED] if dropped else []
    if not blocks:
        del doc["export"]
        return [*changes, _EMPTY_EXPORT_DROPPED]
    if hasattr(table, "unwrap"):
        requests = tomlkit.aot()
        for block in blocks:
            item = tomlkit.table()
            item.update(block)
            item.add(tomlkit.nl())
            requests.append(item)
        doc["export"] = requests
    else:
        doc["export"] = blocks
    formats = ", ".join(str(block.get("format", "by extension")) for block in blocks)
    return [
        *changes,
        f"[export] toggles and artifacts -> {len(blocks)} [[export]] block(s) ({formats})",
    ]


def _rename_timestep(table: Any, where: str) -> list[str]:
    """Rename the ``timestep`` of one figure's options to ``time``.

    A table holding both is left as it is: the two may name different
    instants, and the display loader refuses it with the line to delete.
    """
    if not isinstance(table, Mapping) or "timestep" not in table or "time" in table:
        return []
    value = table["timestep"]
    del table["timestep"]
    table["time"] = value
    return [f"{where}.timestep -> {where}.time ({_plain(value)!r})"]


def _rename_display_timestep(doc: Any) -> list[str]:
    """Rename the figure option ``timestep`` to ``time``, a date or a step.

    It is written in ``[display.overrides.<figure>]`` and, as a dotted path,
    in the ``overrides`` of a calibration phase.
    """
    changes: list[str] = []
    overrides = (doc.get("display") or {}).get("overrides")
    if isinstance(overrides, Mapping):
        for figure in list(overrides):
            changes.extend(_rename_timestep(overrides[figure], f"display.overrides.{figure}"))
    phases = (doc.get("calibration") or {}).get("phases")
    if isinstance(phases, Mapping):
        phases = [phases]
    for index, phase in enumerate(phases or ()):
        phase_overrides = phase.get("overrides") if isinstance(phase, Mapping) else None
        if isinstance(phase_overrides, Mapping):
            changes.extend(_rename_phase_timesteps(phase_overrides, index))
    return changes


def _rename_phase_timesteps(overrides: Any, index: int) -> list[str]:
    """Rename the ``timestep`` a calibration phase writes into a figure's options."""
    where = f"calibration.phases[{index}].overrides"
    changes: list[str] = []
    for key in list(overrides):
        parts = str(key).split(".")
        if len(parts) != 4 or parts[:2] != ["display", "overrides"] or parts[3] != "timestep":
            continue
        renamed = ".".join([*parts[:3], "time"])
        if renamed in overrides:
            # Both reach the figure once the phase is applied; the display
            # loader refuses that pair and names the line to delete.
            continue
        value = overrides[key]
        del overrides[key]
        overrides[renamed] = value
        changes.append(f'{where}."{key}" -> "{renamed}"')
    nested = (overrides.get("display") or {}).get("overrides")
    if isinstance(nested, Mapping):
        for figure in list(nested):
            changes.extend(_rename_timestep(nested[figure], f"{where}.display.overrides.{figure}"))
    return changes


def _migrate_export_variables(doc: Any) -> list[str]:
    """Rewrite the ``[export.variables]`` boolean submodel as a flat list.

    ``[export.variables]`` used to be a table of booleans: ``head`` and
    ``derived`` (expanding to ``watertable_elevation``, ``watertable_depth``,
    ``seepage_mask``) and ``concentration`` gated a real export; ``budget`` and
    ``pathlines`` gated nothing and were already dead. The schema now carries
    the active set directly as ``export.variables = [...]``, so the table is
    expanded into the names it turned on; the dead toggles simply do not
    survive the expansion.
    """
    export = doc.get("export")
    if not isinstance(export, Mapping):
        return []
    variables = export.get("variables")
    if variables is None or not isinstance(variables, Mapping):
        return []
    names: list[str] = []
    if variables.get("head", False):
        names.append("head")
    if variables.get("concentration", False):
        names.append("concentration")
    if variables.get("derived", False):
        names.extend(["watertable_elevation", "watertable_depth", "seepage_mask"])
    export["variables"] = names
    return [f"export.variables (boolean table) -> list {names!r}"]


def _rename_export_times(doc: Any) -> list[str]:
    """Rename ``export.times`` to ``export.time``, matching ``[[export.artifacts]]``."""
    export = doc.get("export")
    if not isinstance(export, Mapping) or "times" not in export:
        return []
    value = export["times"]
    if "time" not in export:
        export["time"] = value
        changes = [f"export.times -> export.time ({value!r})"]
    else:
        changes = ["export.times dropped (export.time already set)"]
    del export["times"]
    return changes


def _drop_the_solver_time_grids(doc: Any) -> list[str]:
    """Drop ``[modflow6.tgrid]`` and ``[modflownwt.tgrid]``, both removed.

    Neither backend ever read the section back. MODFLOW 6 lost it first and the
    runtime refuses it outright, so a file still carrying it does not load at
    all. MODFLOW-NWT kept it longer as a mirror the launcher overwrote from
    ``[simulation.time]``, which made it worse than inert: a file could declare
    ``itmuni = "days"`` next to a run executing in seconds.

    """
    changes: list[str] = []
    for name in _SOLVER_SECTIONS:
        table = doc.get(name)
        if not isinstance(table, Mapping) or "tgrid" not in table:
            continue
        del table["tgrid"]
        changes.append(f"{name}.tgrid dropped (removed from the schema, never read)")
    return changes


#: The ratio bound of Eq. 4 that ``validity_length = "auto"`` reproduces.
_PAPER_ROPTIM_MAX = 2.0


def _drop_the_validity_ratio(doc: Any) -> list[str]:
    """Drop ``roptim_max`` from the network outputs, replaced by ``validity_length``.

    The bound of Eq. 4 is a length now. ``roptim_max = 2`` said "two cells",
    which ``validity_length = "auto"``, the default, says too, so the key goes.
    Another ratio has no exact length without the cell size of the run, which
    a TOML file does not hold: it is refused with the length to write instead.
    """
    outputs = (doc.get("calibration") or {}).get("outputs")
    if not isinstance(outputs, Mapping):
        return []
    changes: list[str] = []
    for name in list(outputs):
        output = outputs[name]
        if not isinstance(output, Mapping) or "roptim_max" not in output:
            continue
        value = output["roptim_max"]
        path = f"calibration.outputs.{name}.roptim_max"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path} = {value!r} is not a number; remove it.")
        if float(value) != _PAPER_ROPTIM_MAX:
            raise ValueError(
                f"{path} = {float(value):g} has no exact equivalent: the bound of Eq. 4 is "
                "now 'validity_length', a length. Replace it by validity_length = "
                f'"<{float(value):g} times the cell size> m" and remove roptim_max.'
            )
        del output["roptim_max"]
        changes.append(f"{path} dropped (2 cells is validity_length = 'auto', the default)")
    return changes


def drop_retired_results_tables(doc: Any) -> list[str]:
    """Drop :data:`RETIRED_RESULTS_TABLES` from *doc* in place; return the paths dropped.

    The root is read, and so are the ``overrides`` of the calibration phases,
    which write dotted paths into the project config. A table goes whatever it
    holds: the ``spatial_fields`` of a sealed config is always false, and
    carrying it to the new key would make every resume lose the per-cell
    budget again.
    """
    names = [table.rsplit(".", 1)[1] for table in RETIRED_RESULTS_TABLES]
    dropped: list[str] = []
    for name in names:
        # Fetched again per delete: on an out-of-order tomlkit document a
        # delete leaves the earlier proxy of [simulation.results] stale.
        results = _results_table(doc)
        if results is not None and name in results:
            del results[name]
            dropped.append(f"simulation.results.{name}")
    dropped.extend(_drop_retired_phase_overrides(doc))
    return dropped


def _drop_retired_phase_overrides(doc: Any) -> list[str]:
    """Drop the retired tables a calibration phase writes in its ``overrides``."""
    phases = (doc.get("calibration") or {}).get("phases")
    if isinstance(phases, Mapping):
        phases = [phases]
    dropped: list[str] = []
    for index, phase in enumerate(phases or ()):
        overrides = phase.get("overrides") if isinstance(phase, Mapping) else None
        if not isinstance(overrides, Mapping):
            continue
        where = f"calibration.phases[{index}].overrides"
        for key in list(overrides):
            if any(str(key) == t or str(key).startswith(f"{t}.") for t in RETIRED_RESULTS_TABLES):
                del overrides[key]
                dropped.append(f'{where}."{key}"')
        for table in RETIRED_RESULTS_TABLES:
            *parents, name = table.split(".")
            node: Any = overrides
            for part in parents:
                node = node.get(part) if isinstance(node, Mapping) else None
            if isinstance(node, Mapping) and name in node:
                del node[name]
                dropped.append(f"{where}.{table}")
    return dropped


def _results_table(scope: Any) -> Mapping[str, Any] | None:
    """Return the ``[simulation.results]`` table of a config-shaped *scope*, if any."""
    simulation = scope.get("simulation")
    results = simulation.get("results") if isinstance(simulation, Mapping) else None
    return results if isinstance(results, Mapping) else None


def _report_retired_results_tables(doc: Any) -> list[str]:
    """Drop the retired result tables of a user file, with the new default."""
    dropped = drop_retired_results_tables(doc)
    if not dropped:
        return []
    return [
        f"{', '.join(dropped)} dropped: a run now keeps its whole per-cell budget, "
        "storage terms included, and rebuilds every derived field on read; "
        "[simulation.results] keep_per_cell_budget = false keeps less"
    ]


def _flatten_boundary_conditions(doc: Any) -> list[str]:
    """Rewrite ``[flow.bc.<kind>.<id>]`` as ``[flow.bc.<id>]`` with a kind field.

    A boundary is keyed by what it is; its kind is an attribute the registry
    declares and the table only has to carry when it departs from that default.
    The nested form said the same thing twice and let the two disagree.
    """
    changes: list[str] = []
    flow = doc.get("flow")
    if flow is not None:
        prefix = "flow"
        bc = flow.get("bc")
        if bc is None:
            return changes
        for kind in ("dirichlet", "cauchy", "robin"):
            nested = bc.get(kind)
            if nested is None:
                continue
            for bc_id in list(nested):
                entry = nested[bc_id]
                if bc_id in bc:
                    changes.append(
                        f"{prefix}.bc.{kind}.{bc_id} dropped ({prefix}.bc.{bc_id} already set)"
                    )
                    continue
                try:
                    entry["kind"] = kind
                    entry.pop("id", None)
                except (TypeError, AttributeError):
                    # A scalar or list under a family key is not a boundary
                    # payload. The loader refuses it with its own message, so
                    # carry it across unchanged rather than mask that error here.
                    pass
                bc[bc_id] = entry
                changes.append(
                    f"{prefix}.bc.{kind}.{bc_id} -> {prefix}.bc.{bc_id} (kind = {kind!r})"
                )
            del bc[kind]
    return changes


def _persistence_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return every ``(path, table)`` pair holding a persistence section."""
    results = (doc.get("simulation") or {}).get("results")
    candidates = [
        ("persistence", doc.get("persistence")),
        ("simulation.results.persistence", (results or {}).get("persistence")),
        ("calibration.persistence", (doc.get("calibration") or {}).get("persistence")),
    ]
    return [(path, table) for path, table in candidates if table is not None]


def _drop_dead_result_options(doc: Any) -> list[str]:
    """Remove the two result options that never drove anything."""
    changes: list[str] = []
    results = (doc.get("simulation") or {}).get("results")
    if results is not None and "solver_scratch" in results:
        del results["solver_scratch"]
        changes.append("simulation.results.solver_scratch dropped (never read)")
    for path, persistence in _persistence_tables(doc):
        if "save_lock" in persistence:
            del persistence["save_lock"]
            changes.append(f"{path}.save_lock dropped (never read)")
    return changes


def _move_the_bottom_path(doc: Any) -> list[str]:
    """Move ``geographic.bottom_path`` to one ``[[data.substratum.sources]]`` entry.

    The key named a bottom raster that nothing read. It moves to the variable
    that reads one. ``[domain.depth_model]`` is left alone: every run of this
    config was built by its declared depth model, and switching the kind here
    would change the results the config reproduces.
    """
    geographic = doc.get("geographic")
    if geographic is None or "bottom_path" not in geographic:
        return []
    value = geographic["bottom_path"]
    del geographic["bottom_path"]
    path = str(value.unwrap() if hasattr(value, "unwrap") else value)
    data = doc.get("data")
    if data is not None and "substratum" in data:
        return ["geographic.bottom_path dropped ([data.substratum] already set)"]
    if data is None:
        doc["data"] = {}
        data = doc["data"]
    data["substratum"] = {"sources": [{"source": "custom", "path": path}]}
    return [
        "geographic.bottom_path -> [[data.substratum.sources]] "
        "(read only with [domain.depth_model] kind = 'raster_substratum' "
        "or 'raster_thickness')"
    ]


def _raw_flow_process_solver(simulation: Any) -> tuple[str, str] | None:
    """Return the id and first solver of the first flow process, before validation."""
    if isinstance(simulation, Mapping):
        processes = simulation.get("process")
    else:
        processes = getattr(simulation, "process", None)
    if not isinstance(processes, list | tuple):
        return None
    for process in processes:
        if isinstance(process, Mapping):
            kind = str(process.get("type", "")).strip().lower()
            solvers = process.get("solvers")
            process_id = process.get("id")
        else:
            kind = str(getattr(process, "type", "")).strip().lower()
            solvers = getattr(process, "solvers", None)
            process_id = getattr(process, "id", None)
        if kind != "flow" or not isinstance(solvers, list | tuple):
            continue
        names = [str(name).strip() for name in solvers if name and str(name).strip()]
        if names:
            return str(process_id or "flow"), names[0]
    return None


#: The section that holds the ``sgrid`` table of each flow solver name.
_SOLVER_SECTION_OF = {
    "modflow6": "modflow6",
    "modflow6_prt": "modflow6",
    "modflow_nwt": "modflownwt",
}


def _flow_solver_section(doc: Any) -> str:
    """Return the solver section whose layering a run of *doc* used.

    The first solver of the first flow process, else ``solver.backend``,
    else MODFLOW 6.
    """
    flow = _raw_flow_process_solver(doc.get("simulation"))
    if flow is not None:
        name: Any = flow[1]
    else:
        solver = doc.get("solver")
        name = solver.get("backend") if isinstance(solver, Mapping) else None
        if isinstance(name, Mapping):
            name = name.get("name") if name.get("backend") == "custom" else name.get("backend")
    return _SOLVER_SECTION_OF.get(str(name or "").strip().lower(), "modflow6")


def _layering_difference(dropped: Mapping[str, Any], kept: Mapping[str, Any]) -> str:
    """Return the keys where *dropped* departs from *kept*, or an empty string."""
    dropped, kept = _plain(dropped), _plain(kept)

    def shown(table: Mapping[str, Any], key: str) -> str:
        return repr(table[key]) if key in table else "unset"

    differences = [
        f"{key} = {shown(dropped, key)} against {shown(kept, key)}"
        for key in sorted(set(dropped) | set(kept))
        if dropped.get(key) != kept.get(key)
    ]
    return ", ".join(differences)


def _move_the_layering(doc: Any) -> list[str]:
    """Move ``[modflow6.sgrid.vertical]`` and ``[modflownwt.sgrid.vertical]`` to ``[domain.layers]``.

    The layering describes the aquifer, so one table serves every solver. When
    both solver tables exist, the one of the flow solver is kept, since it built
    the runs of the file. The other is dropped with a line that says whether it
    held other values. An existing ``[domain.layers]`` wins over both.
    """
    found: dict[str, Any] = {}
    for move in MOVED_TABLES:
        table = _descend(doc, move.old.split("."))
        if table is not None:
            found[move.section] = table
    if not found:
        return []
    parent_key, layers_key = _LAYERING.split(".")
    domain = doc.get(parent_key)
    layers = domain.get(layers_key) if isinstance(domain, Mapping) else None
    kept = None
    if not isinstance(layers, Mapping):
        kept = _flow_solver_section(doc) if len(found) > 1 else next(iter(found))
        layers = found[kept]
    changes: list[str] = []
    old_of = {move.section: move.old for move in MOVED_TABLES}
    for name, table in found.items():
        _drop_table(doc, old_of[name])
        if name == kept:
            changes.append(f"{old_of[name]} -> [{_LAYERING}]")
            continue
        owner = f"[{_LAYERING}] already set" if kept is None else f"{kept} is the flow solver"
        difference = _layering_difference(table, layers)
        held = f"it held other values: {difference}" if difference else "same values"
        changes.append(f"{old_of[name]} dropped ({owner}; {held})")
    if kept is not None:
        if not isinstance(domain, Mapping):
            is_file = isinstance(doc, tomlkit.TOMLDocument)
            doc[parent_key] = tomlkit.table(is_super_table=True) if is_file else {}
            domain = doc[parent_key]
        domain[layers_key] = layers
    return changes


def _move_the_phase_layering(doc: Any) -> list[str]:
    """Move the dotted ``<solver>.sgrid.vertical`` overrides of a calibration phase to ``domain.layers``.

    A phase writes the layering by dotted path. When it writes the paths of
    both solvers, those of the flow solver are kept, as
    :func:`_move_the_layering` keeps its table, and the others are dropped.
    """
    changes: list[str] = []
    for where, phase in _tables_at(doc, "calibration.phases[*]"):
        overrides = phase.get("overrides")
        if not isinstance(overrides, Mapping):
            continue
        found: dict[str, list[str]] = {}
        for move in MOVED_TABLES:
            keys = [
                str(key) for key in overrides if key == move.old or key.startswith(f"{move.old}.")
            ]
            if keys:
                found[move.section] = keys
        if not found:
            continue
        old_of = {move.section: move for move in MOVED_TABLES}
        kept = _flow_solver_section(doc) if len(found) > 1 else next(iter(found))
        for name, keys in found.items():
            for key in keys:
                label = f'{where}.overrides."{key}"'
                if name != kept:
                    del overrides[key]
                    changes.append(f"{label} dropped ({kept} is the flow solver)")
                    continue
                moved = old_of[name].new + key.removeprefix(old_of[name].old)
                if moved in overrides:
                    changes.append(f'{label} left: "{moved}" is given too, keep one')
                    continue
                _move_key(overrides, key, moved, _plain(overrides[key]))
                changes.append(f'{label} -> "{moved}"')
    return changes


def _drop_table(doc: Any, path: str) -> None:
    """Delete the table at *path*, then each parent table it leaves empty."""
    parts = path.split(".")
    while parts:
        parent = _descend(doc, parts[:-1])
        del parent[parts[-1]]
        parts.pop()
        if parent:
            return


def _promote_export(doc: Any, simulation: Any) -> list[str]:
    """Move ``[simulation.results.export]`` to the top-level ``[export]`` table."""
    results = simulation.get("results")
    if results is None or "export" not in results:
        return []
    if "export" in doc:
        # A top-level [export] already exists: drop the buried duplicate.
        del results["export"]
        return ["simulation.results.export dropped (top-level [export] already set)"]
    export_value = results["export"]
    if hasattr(export_value, "unwrap"):
        doc["export"] = tomlkit.item(export_value.unwrap())
    else:
        doc["export"] = export_value
    del results["export"]
    return ["simulation.results.export -> [export]"]


_PERSISTENCE = "simulation.results.persistence", "persistence", "calibration.persistence"

HAND_WRITTEN_FORMS: tuple[OldForm, ...] = (
    OldForm("simulation.on_collision", "simulation.if_exists", ALPHA_FORM),
    OldForm("simulation.run_id", "simulation.name", ALPHA_FORM),
    OldForm("simulation.results.export", "export", ALPHA_FORM),
    OldForm("simulation.results.solver_scratch", None, ALPHA_FORM),
    *(OldForm(f"{path}.save_lock", None, ALPHA_FORM) for path in _PERSISTENCE),
    *(OldForm(table, None, ALPHA_FORM) for table in RETIRED_RESULTS_TABLES),
    *(
        OldForm(f"export.{key}", "export", ALPHA_FORM)
        for key in (*_EXPORT_TOGGLES, "csv_timeseries", "package", "output_dir", "artifacts")
    ),
    OldForm("export.variables.{*}", "export.variables", ALPHA_FORM),
    OldForm("export.times", "export.time", ALPHA_FORM),
    OldForm("display.overrides.{*}.timestep", "display.overrides.{*}.time", ALPHA_FORM),
    *(OldForm(f"{section}.tgrid", None, ALPHA_FORM) for section in _SOLVER_SECTIONS),
    OldForm("geographic.bottom_path", "data.substratum.sources", ALPHA_FORM),
    OldForm(
        "calibration.outputs.{*}.roptim_max", "calibration.outputs.{*}.validity_length", ALPHA_FORM
    ),
    *(
        OldForm(f"flow.bc.{kind}.{{*}}", "flow.bc.{*}", ALPHA_FORM)
        for kind in ("dirichlet", "cauchy", "robin")
    ),
    OldForm("calibration.uncertainty.tolerance", "calibration.uncertainty.cost_margin", ALPHA_FORM),
    OldForm("calibration.uncertainty.mode", "calibration.uncertainty.cost_margin", ALPHA_FORM),
    OldForm(
        "calibration.phases[*].uncertainty.tolerance",
        "calibration.phases[*].uncertainty.cost_margin",
        ALPHA_FORM,
    ),
    OldForm(
        "calibration.phases[*].uncertainty.mode",
        "calibration.phases[*].uncertainty.cost_margin",
        ALPHA_FORM,
    ),
    *(
        OldForm(
            f"{search.scope}.{search.options[0]}.{key}",
            f"{search.scope}.{search.budget}",
            ALPHA_FORM,
        )
        for search in _SEARCH_SCOPES
        for key in sorted({option for _, option in _BUDGET_OPTIONS})
    ),
    *(OldForm(path, None, ALPHA_FORM) for path in _DROPPED_KEYS),
)
"""The old forms a function of this module rewrites, one line for each key it reads."""

REFUSED_OR_RETIRED_FORMS: tuple[OldForm, ...] = (
    *(
        OldForm(path, "mesh", ALPHA_FORM, rewritten=False)
        for path in (
            "mesh_catchment",
            "mesh_input",
            "modflow6.sgrid.planar",
            "modflownwt.sgrid.planar",
            "modflow6.sgrid.grid_dual",
            "modflownwt.sgrid.grid_dual",
        )
    ),
    *(
        OldForm(f"calibration.aggregate.{key}", None, ALPHA_FORM, rewritten=False)
        for key in ("weighting", "nested_gauges", "on_member_failure")
    ),
    *(
        OldForm(f"calibration.{key}", None, ALPHA_FORM, rewritten=False)
        for key in ("lightweight_extraction", "persist_model_distribution", "persistence")
    ),
    OldForm("data.project_crs", "geographic.crs_project", ALPHA_FORM, rewritten=False),
    OldForm("data.hydrography.sources[*].typename", None, ALPHA_FORM, rewritten=False),
)
"""The old forms no rule here carries: the models refuse them, or read and ignore them."""


def old_forms() -> tuple[OldForm, ...]:
    """Return every old form of the grammar this build still knows, with its ``since``."""
    return (
        *(
            OldForm(f"{rule.scope}.{rule.old}", f"{rule.scope}.{rule.new}", rule.since)
            for rule in RENAMED_KEYS
            if not rule.sealed_only
        ),
        *(OldForm(move.old, move.new, move.since) for move in MOVED_TABLES),
        *HAND_WRITTEN_FORMS,
        *REFUSED_OR_RETIRED_FORMS,
    )


def outlived_forms(version: str) -> tuple[OldForm, ...]:
    """Return the old forms *version* should no longer hold."""
    return tuple(form for form in old_forms() if form.outlived_by(version))


def document_path(form_path: str) -> str:
    """Return a form's path as the docs and the snapshots write it, with no list marker."""
    return form_path.replace("[*]", "").replace(".{*}", "")


__all__ = [
    "ALPHA_FORM",
    "DEPRECATION_DELAY_MINORS",
    "HAND_WRITTEN_FORMS",
    "MOVED_TABLES",
    "REFUSED_OR_RETIRED_FORMS",
    "RENAMED_KEYS",
    "RETIRED_RESULTS_TABLES",
    "KeyRename",
    "OldForm",
    "TableMove",
    "document_path",
    "drop_retired_results_tables",
    "fix_config_file",
    "migrate_config_doc",
    "migrate_config_doc_on_load",
    "migrate_sealed_config_doc",
    "old_forms",
    "outlived_forms",
]
