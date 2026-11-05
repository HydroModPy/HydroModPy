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
- ``[display.overrides.<figure>] timestep`` -> ``time``, a row of
  :data:`RENAMED_KEYS`
- the figure ``calibration_posterior`` -> ``calibration_trial_distribution``, in
  ``[display] figures`` and as a key of ``[display.overrides]`` (:data:`RENAMED_FIGURES`)
- ``[modflow6.tgrid]`` and ``[modflownwt.tgrid]`` dropped: neither backend
  read them
- ``solver_scratch`` and ``persistence.save_lock`` dropped: both drove
  nothing. The solver scratch directory is ``<project>/.hmp/scratch`` and
  no run option writes the lockfile.
- ``[modflow6.sgrid.vertical]`` and ``[modflownwt.sgrid.vertical]`` ->
  ``[domain.layers]``, which every solver reads. When both are written, the
  table of the flow solver is kept (the first solver of the first flow
  process, else ``solver.backend``, else MODFLOW 6) and the other is dropped
  with a line saying whether it held other values. A ``[domain.layers]`` in the
  same file wins over both. The paths come from :data:`MOVED_TABLES`, which the
  changes page of the docs reads too.
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
- ``flow.active_bc`` and ``flow.active_sinks_sources`` folded into the tables they
  listed: a table is active when it is declared. A table present and not listed gets
  ``enabled = false``, and a name listed with no table gets an empty one
  (:func:`_fold_the_activation_lists`), so a file means what it meant. A document that
  writes neither list is read under the new rule: nothing tells it from a new file.
- ``kind`` of a drain: ``cauchy`` and ``robin`` are one linear drain, ``drain``
- the seven keys ``[transport]`` inherited and never read dropped
- ``geographic.catchment.buff_area`` written as a bare number -> ``"N% of sqrt(area)"``,
  the rule of version 1 written out, with the same distance (:func:`_write_out_the_bare_buffer`)
- ``[workspace] catalog_path`` and ``runs_dir`` dropped: the loader refuses them with the
  storage layout contract, the index and the runs of a project have one place and a file
  cannot move them
- ``[workspace] project_root``, ``[display] output_dir`` and
  ``[calibration] rerun_best_with_outputs`` dropped, ``simulation.if_exists =
  "replace"`` rewritten as ``"version"``: the loader refuses each of them with
  the line to delete, and only ``fix_config_file`` makes the edit. The read
  path keeps refusing, so a file that says them is told. ``[site]`` is never
  written here: it names the catchment, which only the user knows.

This is a migration tool, not a backward-compat shim: the runtime model itself
never accepts the old keys (``extra="forbid"``). ``migrate_config_doc`` and
:data:`RENAMED_KEYS` are the document-to-document transforms; two kinds of caller
wrap them. ``fix_config_chain`` (reached through ``hmp doctor --fix-config``)
rewrites on disk each file of a ``base_config`` chain that holds an old form, so a
project catches up for good. The loader of :mod:`hydromodpy.core.toml_io.loader`
reads old forms in memory, through the root-config provider, and warns once per key
and per file, under the name of the file that holds the key.

Order
-----
Each layer of a document (a file of a chain, an overlay, ``--set``,
``HMP_SET_*``) is migrated on its own before the merge
(:func:`migrate_layers`), so an old name in an overlay wins over a new name in its
base as the same key under the new name would. Only the rules that a layer can
apply alone run there: a key or a table under its new path. Reading a value another
layer holds is allowed, and goes through the context, the raw layers merged. Then
every rule runs on the merged document (:func:`migrate_merged_doc`). Three families
wait for it, because they need the whole document or because the merge rule depends
on their shape: a table of toggles that becomes a list, a pair of keys that becomes
one, and an option whose meaning hangs on another key.

Dotted paths
------------
Some keys and values of a document are themselves paths into the document: the
``overrides`` of a calibration phase, ``path`` and ``target`` of a calibration
parameter, the keys of ``[sites.bind]`` and of the ``set`` table of a recipe.
:func:`moved_paths` derives one table from :data:`RENAMED_KEYS` and
:data:`MOVED_TABLES`, so a new row rewrites those too, and :func:`rewrite_dotted_path`
reads it for a path given on a command line.

Deprecation
-----------
Every old form says since which version it is old (:data:`DEPRECATION_DELAY_MINORS`
and :func:`old_forms`). ``[calibration]`` is exempt: a file that writes one of its old
keys is refused with the new name, the doctor rewrites it, and a sealed config still
reads it. Any other form keeps loading for two minor versions, the one that
retired it included, then it leaves this module:
``tests/unit/config/test_config_migration.py`` fails when one outlives its delay.
The policy is ``docs/source/about/versions.md``. A rename from now on is one row of
:data:`RENAMED_KEYS`, a key or a table that changes place one row of
:data:`MOVED_TABLES`. At the end of its delay the row of a rename stays with
``sealed_only=True``, because a run sealed under the old name stays readable for
the whole major line, and only the live file loses it.
"""

from __future__ import annotations

import copy
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
from packaging.version import Version

from hydromodpy.calibration.config import CALIBRATION_RENAMES
from hydromodpy.core.config_kit.base import CANNOT_REWRITE, refuse_old_forms, warn_old_form
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.result_dirs import is_sealed_run_config
from hydromodpy.core.time import parse_step_spec
from hydromodpy.core.toml_io.loader import read_toml_chain
from hydromodpy.core.toml_io.merge import DIRECTIVE_SUFFIXES, merge_toml_payloads
from hydromodpy.core.toml_io.overrides import COMMAND_LINE_SOURCES
from hydromodpy.core.toml_io.paths import DottedPath, parse
from hydromodpy.physics.flow.flow_runtime_config import FLOW_RUNTIME_KEYS
from hydromodpy.physics.flow.property_ids import NEVER_READ_IDS, OLD_PROPERTY_IDS
from hydromodpy.results.exporters.export_spec import RUN_FORMATS, format_from_path

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
    """A table or a key the loader moves, whole, to another path.

    Every key of the table keeps its name under the new path. A dotted path that
    reaches it, ``"<old>.<key>"``, moves to ``"<new>.<key>"`` too
    (:func:`moved_paths`). The migration below and the docs read the same
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

#: What the loader moves to another path: the layering each solver wrote under
#: ``sgrid``, which every solver reads from ``[domain.layers]`` now, and the settings of
#: the Boussinesq solve. Two rows with one ``new`` are alternatives, and the flow solver
#: chooses between them.
MOVED_TABLES: tuple[TableMove, ...] = (
    *(
        TableMove(f"{section}.sgrid.vertical", _LAYERING, since=ALPHA_FORM)
        for section in _SOLVER_SECTIONS
    ),
    *(
        TableMove(f"flow.{old}", f"flow.runtime.{new}", since=ALPHA_FORM)
        for old, new in FLOW_RUNTIME_KEYS.items()
    ),
)


def fix_config_chain(
    path: str | Path, *, dry_run: bool = False, diffs: dict[Path, str] | None = None
) -> dict[Path, list[str]]:
    """Rewrite each file of the ``base_config`` chain of *path* that holds an old form.

    Returns the changes of each file of the chain, root first, an empty list for a
    file already up to date. Nothing is written when the rewrite would change what
    the chain reads: a table several files fill key by key, for example, becomes a
    list one file replaces. That raises :class:`ConfigError` naming the keys. A file
    whose rewrite hangs on a key a file below it writes stays as it is, and its lines
    say what to write (:func:`_left_for_a_child`): another file can inherit it and
    read it otherwise. With *dry_run* every check runs and no file is written. When
    *diffs* is given it receives, for each file that would be rewritten, the unified
    diff of the rewrite. Raises :class:`FileNotFoundError` when a file is missing and a
    TOML error on a malformed one.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"No TOML file at {target}")
    # utf-8-sig: several configs in this repository carry a BOM, and tomlkit
    # reads it as an empty key on line 1, so the doctor could not fix them.
    docs = {
        item.path: tomlkit.parse(item.path.read_text(encoding="utf-8-sig"))
        for item in read_toml_chain(target, migrate=False)
    }
    layers = list(docs.items())
    written = _reading_context(layers)
    current = _under_todays_names(layers, written)
    before = copy.deepcopy(current)
    _every_rule(before)
    changes: dict[Path, list[str]] = {}
    left: set[Path] = set()
    # Read before any layer is rewritten: a layer that folds its list stops saying it.
    readings = [_lists_as_this_layer_reads_them(layers, i, current) for i in range(len(layers))]
    for index, (file, doc) in enumerate(layers):
        reading = readings[index]
        hanging = _left_for_a_child(layers, index, written=written, current=reading)
        if hanging:
            changes[file] = hanging
            left.add(file)
            continue
        changes[file] = _every_rule(doc, written=written, current=reading)
        changes[file].extend(_migrate_refused_keys(doc, context=written))
    after = _under_todays_names(layers, _reading_context(layers))
    _every_rule(after)
    moved = _different_keys(before, after)
    if moved:
        raise ConfigError(
            f"Rewriting {target} and the files it inherits one by one would change what they "
            f"read at {', '.join(moved)}, so nothing was written. Move these keys to one file "
            "by hand, then run this again."
        )
    for file, doc in docs.items():
        if changes[file] and file not in left:
            if diffs is not None:
                diffs[file] = _unified_diff(file, tomlkit.dumps(doc))
            if not dry_run:
                file.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


def _unified_diff(file: Path, after: str) -> str:
    """Return the unified diff from the text of *file* on disk to *after*."""
    import difflib

    before = file.read_text(encoding="utf-8-sig")
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(file),
            tofile=f"{file} (migrated)",
        )
    )


def _lists_as_this_layer_reads_them(
    layers: Sequence[Layer], index: int, current: dict[str, Any]
) -> dict[str, Any]:
    """Return *current* with the activation lists and tables this layer answers for.

    A file writes ``enabled = false`` for the tables it can see. A list held below this
    layer folds there, so a layer that holds none leaves its tables alone. A table
    declared below this layer switches itself off there, so a layer that holds a list
    does not write for it.
    """
    flow = layers[index][1].get("flow")
    above = layers[: index + 1]
    above_flow = _under_todays_names(above, _reading_context(above)).get("flow")
    reading = copy.deepcopy(current)
    read_flow = reading.get("flow")
    if not isinstance(read_flow, dict):
        return reading
    if isinstance(flow, Mapping) and _activation_keys_of(flow):
        lists = {name: read_flow[name] for name in _ACTIVATION_LISTS if name in read_flow}
        read_flow = dict(above_flow) if isinstance(above_flow, Mapping) else {}
        read_flow.update(lists)
    else:
        for name in _ACTIVATION_LISTS:
            read_flow.pop(name, None)
            if isinstance(above_flow, Mapping) and name in above_flow:
                read_flow[name] = above_flow[name]
    reading["flow"] = read_flow
    return reading


def _left_for_a_child(
    layers: Sequence[Layer], index: int, *, written: Any, current: Any
) -> list[str]:
    """Return why layer *index* stays as it is, or nothing when it can be rewritten.

    A rule reads the chain for what a table lacks: the method of a search option, the
    flow solver of a layering, what a width is scored on. Read from a file below,
    the answer holds for that file only, and a sibling can write another one. So the
    layer is rewritten twice on copies, under the whole chain and under itself and
    what it inherits. When the two differ, the rewrite hangs on a child.
    """
    source, doc = layers[index]
    if index == len(layers) - 1:
        return []
    above = layers[: index + 1]
    alone_written = _reading_context(above)
    alone = copy.deepcopy(_plain(doc))
    said_alone = _every_rule(
        alone, written=alone_written, current=_under_todays_names(above, alone_written)
    )
    said_alone.extend(_migrate_refused_keys(alone, context=alone_written))
    whole = copy.deepcopy(_plain(doc))
    said_whole = _every_rule(whole, written=written, current=current)
    said_whole.extend(_migrate_refused_keys(whole, context=written))
    if alone == whole:
        return []
    child, name = Path(str(layers[-1][0])).name, Path(str(source)).name
    hanging = [change for change in said_whole if change not in said_alone] or said_whole
    return [
        f"{change}{CANNOT_REWRITE}that reading comes from a key {child} writes, and another "
        f"file that inherits {name} can write another one. Write the new form in {child} "
        f"and in each such file, then remove the old key from {name}"
        for change in hanging
    ]


def fix_config_file(path: str | Path) -> list[str]:
    """Rewrite the chain of *path*, as :func:`fix_config_chain`; return the changes of *path*."""
    return fix_config_chain(path)[Path(path).expanduser().resolve()]


def _under_todays_names(layers: Sequence[Layer], written: Any) -> dict[str, Any]:
    """Return *layers* merged with their keys under today's names, the layers left as they are.

    One layer stands alone, as in :func:`_reading_context`.
    """
    merged: dict[str, Any] = {}
    for _, doc in layers:
        own = copy.deepcopy(_plain(doc))
        _file_rules(own, context=written, sealed=False)
        _migrate_refused_keys(own, context=written)
        merged = own if len(layers) == 1 else merge_toml_payloads(merged, own)
    return merged


def _different_keys(before: Any, after: Any, *, where: str = "") -> list[str]:
    """Return the dotted paths where two documents differ."""
    if not (isinstance(before, Mapping) and isinstance(after, Mapping)):
        return [] if before == after else [where]
    found: list[str] = []
    for key in sorted({*before, *after}):
        path = f"{where}.{key}" if where else str(key)
        if key not in before or key not in after:
            found.append(path)
        else:
            found.extend(_different_keys(before[key], after[key], where=path))
    return found


def migrate_config_doc(doc: Any) -> list[str]:
    """Apply every migration to a parsed doc in place, reading the doc alone.

    Works on a plain ``dict`` (``tomllib``) or a ``tomlkit`` document. Returns the
    list of human-readable changes applied.
    """
    return _every_rule(doc)


def _every_rule(
    doc: Any, *, written: Any = None, current: Any = None, sealed: bool = False
) -> list[str]:
    """Run the rules of a layer, then those of a whole document, on *doc*.

    *written* is what the layers say as they are written, and *current* what they say
    under today's names. Unset, *doc* stands for both.
    """
    changes = _file_rules(doc, context=doc if written is None else written, sealed=sealed)
    changes.extend(
        _whole_document_rules(doc, context=doc if current is None else current, sealed=sealed)
    )
    if _EMPTY_EXPORT_DROPPED in changes:
        # The older spellings of a table that wrote nothing lead nowhere either.
        changes = [change for change in changes if not change.startswith("export.")]
    return changes


def _file_rules(doc: Any, *, context: Any, sealed: bool) -> list[str]:
    """The rules one layer can apply alone: a key or a table under its new path."""
    changes = _drop_dead_result_options(doc)
    changes.extend(_report_retired_results_tables(doc))
    changes.extend(_move_the_bottom_path(doc))
    changes.extend(_move_the_tables(doc, context))
    changes.extend(_flatten_boundary_conditions(doc))
    changes.extend(_drop_the_solver_time_grids(doc))
    changes.extend(_rename_simulation_keys(doc))
    changes.extend(_rename_export_times(doc))
    changes.extend(_rename_keys(doc, sealed=sealed, context=context))
    changes.extend(_rename_field_values(doc))
    changes.extend(_rename_figures(doc))
    changes.extend(_rename_the_drain_kinds(doc))
    changes.extend(_write_out_the_bare_buffer(doc))
    changes.extend(_rename_the_property_ids(doc))
    changes.extend(_drop_what_transport_never_read(doc))
    return changes


RENAMED_FIELDS: dict[str, str] = {
    "accumulation_flux": "drain_accumulation_flux",
    "mass_accumulated": "mass_seepage_running_sum",
    "fluxes_from_budget": "budget_flux_per_area",
}
"""Fields that took another name, in the values of ``[[export]] variables`` and of a figure."""


def _rename_field_values(doc: Any) -> list[str]:
    """Rewrite a retired field name where a table writes it as a value."""
    changes: list[str] = []
    exports = doc.get("export")
    tables = exports if isinstance(exports, list) else ([exports] if exports else [])
    for position, table in enumerate(tables):
        written = table.get("variables") if isinstance(table, Mapping) else None
        if isinstance(written, str) and written in RENAMED_FIELDS:
            table["variables"] = RENAMED_FIELDS[written]
            changes.append(f"export[{position}].variables: {written} -> {RENAMED_FIELDS[written]}")
        elif isinstance(written, list):
            for index, name in enumerate(written):
                if isinstance(name, str) and name in RENAMED_FIELDS:
                    written[index] = RENAMED_FIELDS[name]
                    changes.append(
                        f"export[{position}].variables: {name} -> {RENAMED_FIELDS[name]}"
                    )
    display = doc.get("display")
    overrides = display.get("overrides") if isinstance(display, Mapping) else None
    for figure, options in (overrides or {}).items():
        written = options.get("variable") if isinstance(options, Mapping) else None
        if isinstance(written, str) and written in RENAMED_FIELDS:
            options["variable"] = RENAMED_FIELDS[written]
            changes.append(
                f"display.overrides.{figure}.variable: {written} -> {options['variable']}"
            )
    return changes


RENAMED_FIGURES: dict[str, str] = {"calibration_posterior": "calibration_trial_distribution"}
"""Figures that took another name, in ``[display] figures`` and as a key of ``[display.overrides]``."""


def _rename_figures(doc: Any) -> list[str]:
    """Rewrite a retired figure name in the list of figures and in their overrides."""
    display = doc.get("display")
    if not isinstance(display, Mapping):
        return []
    changes: list[str] = []
    figures = display.get("figures")
    for index, name in enumerate(figures if isinstance(figures, list) else []):
        if name in RENAMED_FIGURES:
            figures[index] = RENAMED_FIGURES[name]
            changes.append(f"display.figures: {name} -> {RENAMED_FIGURES[name]}")
    overrides = display.get("overrides")
    for name, new in RENAMED_FIGURES.items():
        if isinstance(overrides, Mapping) and name in overrides and new not in overrides:
            _move_key(overrides, name, new, overrides[name])
            changes.append(f"display.overrides.{name} -> {new}")
    return changes


def _whole_document_rules(doc: Any, *, context: Any, sealed: bool) -> list[str]:
    """The rules that wait for the merge.

    A table of toggles becomes a list, and a list does not merge key by key. A
    width and its mode become one key. What a method option counted hangs on the
    method. A ratio is checked on what the files end up saying. A list that activates
    tables hangs on the tables every layer declares.
    """
    changes = _refused(_drop_the_validity_ratio(doc, sealed=sealed))
    changes.extend(_fold_the_activation_lists(doc, context=context))
    export = _migrate_export_variables(doc)
    exploded = _explode_export_table(doc)
    changes.extend(export)
    changes.extend(exploded)
    changes.extend(_refused(_rewrite_search_options(doc, sealed=sealed, context=context)))
    changes.extend(_refused(_rewrite_cost_margin(doc, sealed=sealed, context=context)))
    if sealed:
        # A live file is refused on these forms, and only the doctor rewrites them.
        changes.extend(_migrate_calibration_forms(doc, sealed=True, context=context))
    return changes


def _rename_simulation_keys(doc: Any) -> list[str]:
    """Rewrite the ``[simulation]`` keys whose new name may already be written."""
    simulation = doc.get("simulation")
    if simulation is None:
        return []
    changes: list[str] = []
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
    return changes


#: Keys the loader refuses and a file can drop without changing what a run does.
_DROPPED_KEYS: dict[str, str] = {
    "workspace.project_root": (
        "the project root is the folder that holds project.toml, or the folder of the file"
    ),
    "workspace.catalog_path": (
        "the index of a project is <project>/.hmp/index.duckdb, fixed by the storage layout "
        "contract"
    ),
    "workspace.runs_dir": (
        "the runs of a project are in <project>/runs/, fixed by the storage layout contract"
    ),
    "display.output_dir": "figures are written under runs/<run>/figures/",
    "calibration.rerun_best_with_outputs": (
        "the best trial is promoted by default (save_runs = 'best_n')"
    ),
    **{
        f"calibration.{key}": "no step ever read it"
        for key in (
            "lightweight_extraction",
            "persist_model_distribution",
            "persistence",
            "aggregate.weighting",
            "aggregate.nested_gauges",
            "aggregate.on_member_failure",
        )
    },
}


def _migrate_refused_keys(doc: Any, *, context: Any) -> list[str]:
    """Drop or rewrite the keys the loader refuses, in a file only.

    Not part of :func:`migrate_config_doc`: a load keeps refusing these keys,
    with the line to delete, and ``hmp doctor --fix-config`` makes the edit.
    The calibration phases write the same keys as dotted ``overrides``, and
    those are carried across too. *context* is what the layers write together,
    so a step or a gauge can sit in a parent.
    """
    changes = _migrate_refused_scope(doc, where="")
    changes.extend(_migrate_calibration_forms(doc, sealed=False, context=context))
    for label, phase in _tables_at(doc, _PHASES):
        overrides = phase.get("overrides")
        if isinstance(overrides, Mapping):
            where = f"{label}.overrides."
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


def _migrate_calibration_forms(doc: Any, *, sealed: bool, context: Any) -> list[str]:
    """Rewrite the ``[calibration]`` forms a count, a station, a default or a flat table stood for.

    A live file is refused on them and the doctor writes the new form. A sealed
    config reads in silence: a replay reads its stored scores and never scores
    again, so a burn-in or a station it carries is dropped, whatever its value.
    """
    return [
        *_rewrite_the_warmup(doc, sealed=sealed, context=context),
        *_fold_the_station_into_the_gauge(doc, sealed=sealed, context=context),
        *_write_the_block_metric(doc),
        *_drop_an_objective_beside_blocks(doc, sealed=sealed),
        *_rewrite_the_network_outputs(doc, sealed=sealed, context=context),
    ]


def _rewrite_the_warmup(doc: Any, *, sealed: bool, context: Any) -> list[str]:
    """Turn ``warmup_periods`` into the ``window`` start it stood for.

    ``N`` samples skipped are ``N`` steps past ``[simulation.time] start_datetime``,
    which the doctor writes when the chain holds both. The old count ran from the
    first sample aligned with the record, so the date equals it only when the
    record starts at ``start_datetime``, and the change says so. A count of zero
    skipped nothing and goes. The ``warmup`` of one block has no date, since a
    window bounds every block: it is left, with the reason.
    """
    changes: list[str] = []
    targets = [
        (where, table, "warmup_periods") for where, table in _tables_at(doc, "calibration")
    ] + [(where, table, "warmup") for where, table in _tables_at(doc, _BLOCKS)]
    for where, table, key in targets:
        if key not in table:
            continue
        label, count = f"{where}.{key}", _plain(table[key])
        if sealed or not count:
            del table[key]
            changes.append(f"{label} dropped ({'sealed' if sealed else '0 skipped nothing'})")
            continue
        try:
            if key == "warmup" or "window" in table:
                raise _CannotRewrite(
                    "write window = {start = <date>} on [calibration], once for all blocks"
                    if key == "warmup"
                    else "window is given too, keep one"
                )
            window = tomlkit.inline_table()
            window["start"] = _start_after_steps(count, context)
        except _CannotRewrite as reason:
            changes.append(f"{label}{CANNOT_REWRITE}{reason}")
            continue
        _move_key(table, key, "window", window)
        changes.append(
            f"{label} -> window (start {window['start']}, counted from start_datetime; the old "
            "count ran from the first aligned sample, so the date equals it only when the "
            "record starts at start_datetime)"
        )
    return changes


def _fold_the_station_into_the_gauge(doc: Any, *, sealed: bool, context: Any) -> list[str]:
    """Move ``observed_station_id`` to ``[site] gauge``, which names the station of the catchment.

    The key is dropped when the gauge of the chain says the same. It is written to
    the gauge when the chain has none, and left, with both names, when the gauge differs.
    """
    changes: list[str] = []
    for scope in ("calibration", _PHASES, "calibration.protocol"):
        for where, table in _tables_at(doc, scope):
            if "observed_station_id" not in table:
                continue
            label, station = f"{where}.observed_station_id", _plain(table["observed_station_id"])
            gauge = _value_at(doc, "site.gauge")
            if gauge is None:
                gauge = _value_at(context, "site.gauge")
            if gauge not in (None, station) and not sealed:
                changes.append(f"{label}{CANNOT_REWRITE}[site] gauge is {gauge!r}, keep one")
                continue
            if gauge is None and not sealed:
                _set_at(doc, "site.gauge", station)
            del table["observed_station_id"]
            changes.append(f"{label} dropped ({'sealed' if sealed else 'now [site] gauge'})")
    return changes


def _write_the_block_metric(doc: Any) -> list[str]:
    """Write ``metric = "rmse"``, the old default, on a block that left it out."""
    changes: list[str] = []
    for where, block in _tables_at(doc, _BLOCKS):
        if "metric" not in block:
            _set_key(block, "metric", "rmse", after="name")
            changes.append(f"{where}.metric = 'rmse' (the old default, now required)")
    return changes


def _drop_an_objective_beside_blocks(doc: Any, *, sealed: bool) -> list[str]:
    """Drop the section ``objective`` written beside blocks, which score by their own metric.

    A phase that scores a ``variable`` and writes no ``objective`` reads the
    section's, so the key stays for it and is left with the reason.
    """
    calibration = doc.get("calibration")
    if not (isinstance(calibration, Mapping) and calibration.get("objective_blocks")):
        return []
    if "objective" not in calibration:
        return []
    for _, phase in _tables_at(doc, _PHASES):
        if phase.get("variable") is not None and phase.get("objective") is None and not sealed:
            return [
                "calibration.objective"
                f"{CANNOT_REWRITE}a phase scores a variable and reads it; write it on the phase"
            ]
    del calibration["objective"]
    return ["calibration.objective dropped (the blocks score by their own metric)"]


_OUTPUTS = "calibration.outputs.{*}"
_OUTPUT_EXTENT = "calibration.outputs.{*}.extent"
_NETWORK_FORMS = {
    f"{scope}.{old}": f"{_OUTPUTS}.{new}"
    for scope in (_OUTPUTS, _OUTPUT_EXTENT)
    for old, (new, _meaning) in CALIBRATION_RENAMES[scope].items()
}
"""Where each flat key of a network output went, in the grammar of the old forms."""
_RIVER_NETWORK = "geographic.river_network"
_PERMANENT_KEYS = ("minimal_stream_geometry_path", "minimal_observed_network")


def _rewrite_the_network_outputs(doc: Any, *, sealed: bool, context: Any) -> list[str]:
    """Move the flat keys of a network output to its tables ``map``, ``model`` and ``verdict``.

    Runs after the extent rules, so a duration is already a duration. *context* says
    what the chain writes, since ``support`` or the other map can sit in another file.
    The role of two maps is written: one state was scored on the permanent map and two
    bounds shared the value by the old weights, so no stored number moves.
    """
    chain = dict(_tables_at(context, _OUTPUTS))
    changes: list[str] = []
    for where, output in _tables_at(doc, _OUTPUTS):
        seen = _plain(chain.get(where, output))
        if seen.get("support") != "network":
            continue
        if any(old in output for old in CALIBRATION_RENAMES[_OUTPUTS]) and not _is_a_real_table(
            doc, where
        ):
            changes.append(f"{where}{CANNOT_REWRITE}write the output as a table [{where}]")
            continue
        role = _role_of_the_maps(output, seen)
        written_role = _plain(output.get("map", {}).get("calibrate_on"))
        clash = None not in (written_role, role) and written_role != role
        rule, length = seen.get("observed_rasterization"), seen.get("validity_length")
        for old, (new, _meaning) in CALIBRATION_RENAMES[_OUTPUTS].items():
            if old not in output:
                continue
            label, value = f"{where}.{old}", _plain(output[old])
            if old.startswith("heads_") and rule not in (None, "heads"):
                del output[old]
                changes.append(f"{label} dropped (drawn by {rule!r}, which never read it)")
            elif old == "observed_position_accuracy" and length not in (None, "auto"):
                del output[old]
                changes.append(f"{label} dropped (validity_length is a length, it was never read)")
            elif value == _RIVER_NETWORK and sealed:
                del output[old]
                _holder_of(output, ["map"], doc)
                changes.append(f"{label} dropped (sealed)")
            elif value == _RIVER_NETWORK:
                changes.append(
                    f"{label}{CANNOT_REWRITE}a network the DEM derives is no observation; write "
                    "map.complete = 'data.hydrography' or the path of a vector file"
                )
            elif old == "diagonal_neighbors" and not isinstance(value, bool):
                changes.append(f"{label}{CANNOT_REWRITE}{value!r} is neither true nor false")
            elif old == "extent" and "weights" in value and clash:
                changes.append(
                    f"{label}{CANNOT_REWRITE}its weights say {role!r} and map.calibrate_on says "
                    f"{written_role!r}, keep one"
                )
            else:
                if old == "diagonal_neighbors":
                    value = "D8" if value else "D4"
                changes.append(_move_across(output, old, new, value, label, doc))
        changes.extend(_rewrite_the_extent_keys(where, output, role, doc))
    return changes


def _is_a_real_table(doc: Any, where: str) -> bool:
    """Say whether a table added under *where* is written there.

    tomlkit misplaces it, or fails on a removed key, when dotted keys of a parent table
    hold the output. So the addition is tried on a copy of the text.
    """
    if not isinstance(doc, tomlkit.TOMLDocument):
        return True
    trial = tomlkit.parse(tomlkit.dumps(doc))
    _holder_of(dict(_tables_at(trial, _OUTPUTS))[where], ["trial"], trial)
    read_back = dict(_tables_at(tomllib.loads(tomlkit.dumps(trial)), _OUTPUTS))
    return "trial" in read_back[where]


def _role_of_the_maps(output: Mapping[str, Any], seen: Mapping[str, Any]) -> Any:
    """Return the ``calibrate_on`` this layer has to write, or ``None``.

    A layer writes it when it holds the permanent map or an extent, and only when the
    chain declares both maps, under the old names or in the ``map`` of a parent already
    rewritten. A chain with one map scored one bound, and its role goes.

    One state scored the permanent map, and an extent shared the value by the old
    weights, half and half when none is written. A role a rewritten layer writes beside
    its maps stands, except against old weights or an extent this layer adds under a role
    of one state, since that old form scored two bounds. A role with no map beside it
    comes from a child, so it does not change what this layer writes for its siblings.
    """
    drawn, model = seen.get("map", {}), seen.get("model", {})
    complete = any(key in seen for key in ("stream_geometry_path", "observed_network"))
    permanent = any(key in seen for key in _PERMANENT_KEYS)
    holds = any(key in output for key in _PERMANENT_KEYS) or "extent" in output
    if not ((complete or "complete" in drawn) and (permanent or "permanent" in drawn) and holds):
        return None
    written = drawn.get("calibrate_on")
    weights = seen.get("extent", {}).get("weights", {})
    share = {"permanent": weights.get("minimal", 0.5), "complete": weights.get("maximal", 0.5)}
    if weights or ("extent" in output and not isinstance(written, Mapping)):
        return share
    if written is not None and ("complete" in drawn or "permanent" in drawn):
        return None
    if "extent" in seen or ("extent" in model and written is None):
        return share
    return "permanent"


def _rewrite_the_extent_keys(where: str, output: Any, role: Any, doc: Any) -> list[str]:
    """Rename what the moved extent table holds, then write the role of the maps."""
    changes: list[str] = []
    model = output.get("model")
    extent = model.get("extent") if isinstance(model, Mapping) else None
    label = f"{where}.extent"
    if isinstance(extent, Mapping) and "weights" in extent:
        del extent["weights"]
        if role is None:
            changes.append(f"{label}.weights dropped (one map, nothing to share)")
    for old, (new, _meaning) in CALIBRATION_RENAMES[_OUTPUT_EXTENT].items():
        if isinstance(extent, Mapping) and old in extent:
            rule = KeyRename(_OUTPUT_EXTENT, old, new.rsplit(".", 1)[-1], since=ALPHA_FORM)
            changes.extend(_rename_one(extent, rule, f"{label}.{old}", context=doc, sealed=False))
    if role is not None:
        holder = _holder_of(output, ["map"], doc)
        if "calibrate_on" not in holder:
            holder["calibrate_on"] = role
            changes.append(f"{where}.map.calibrate_on = {role!r} (what the old form scored on)")
    return changes


def _holder_of(table: Any, parents: Sequence[str], doc: Any) -> Any:
    """Return the table at *parents* under *table*, made on the way when it is missing."""
    holder = table
    for part in parents:
        if part not in holder:
            inline = isinstance(holder, tomlkit.items.InlineTable)
            holder[part] = tomlkit.inline_table() if inline else _an_empty_table(doc)
        holder = holder[part]
    return holder


def _move_across(table: Any, old: str, new: str, value: Any, label: str, doc: Any) -> str:
    """Move ``old`` of *table* to the dotted ``new``, with the comment of its line, and say so."""
    *parents, name = new.split(".")
    holder = _holder_of(table, parents, doc)
    if name in holder:
        return f"{label}{CANNOT_REWRITE}{new!r} is given too, keep one"
    comment = _comment_of(table, old)
    written = _position(table, old) is not None
    original = table[old]
    del table[old]
    item = (_moved_table(original) or _scalar_item(value, comment)) if written else None
    holder[name] = value if item is None else item
    return f"{label} -> {new}"


def _start_after_steps(count: Any, doc: Any) -> str:
    """Return the day *count* steps past ``[simulation.time] start_datetime`` of *doc*."""
    import pandas as pd

    step, unit = _time_step_of(count, doc, "write the date of the first sample scored")
    time = doc["simulation"]["time"]
    if time.get("start_datetime") is None:
        raise _CannotRewrite(
            "[simulation.time] start_datetime is not in this file or the files it inherits"
        )
    start = pd.Timestamp(_plain(time["start_datetime"])) + pd.DateOffset(
        **{f"{unit}s": step * count}
    )
    return start.date().isoformat()


class _CannotRewrite(Exception):
    """A renamed key whose value the doctor cannot carry over; it is left, with the reason."""


@dataclass(frozen=True)
class KeyRename:
    """One key a loader refuses under its old name, and what it is called now.

    ``scope`` is the table that holds it, written as the path of the document:
    ``calibration``, ``calibration.protocol``. ``name[*]`` walks each table of a
    list (``calibration.phases[*]``) and ``{*}`` the tables a table holds under
    free names (``calibration.parameters.{*}``). One row is enough: the dotted paths
    that name the key follow (:func:`moved_paths`), and so do the directives
    ``<old>__append``, ``<old>__merge`` and ``<old>__delete``.

    ``convert(value, doc)`` returns the value to write under the new name, or
    raises :class:`_CannotRewrite` with the reason when it cannot decide: the
    doctor then leaves the key and says why. *doc* is the context, what the layers
    of the document say together.

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

    @property
    def refused_on_load(self) -> bool:
        """Whether a file is refused on this key at once, and only the doctor rewrites it."""
        return self.scope.split(".", 1)[0] == "calibration"


class _Refused(str):
    """A change the doctor makes and a load refuses: a ``[calibration]`` key has no delay."""


def _refused(changes: Sequence[str]) -> list[str]:
    """Mark *changes* as refused on load. A key left as it is goes on to the refusal of its model."""
    return [change if CANNOT_REWRITE in change else _Refused(change) for change in changes]


def _time_step_of(value: Any, doc: Any, instead: str) -> tuple[int, str]:
    """Return the ``[simulation.time]`` step of *doc* that a count of timesteps is read on.

    *doc* is what the layers say together, so the step can sit in a parent.
    *instead* says what to write when the count cannot be converted.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _CannotRewrite(f"{value!r} is not a count of timesteps")
    simulation = doc.get("simulation") if isinstance(doc, Mapping) else None
    time = simulation.get("time") if isinstance(simulation, Mapping) else None
    if not isinstance(time, Mapping) or time.get("step_value") is None:
        raise _CannotRewrite(
            "the timestep is not in this file or the files it inherits ([simulation.time] "
            f"step_value), so the count cannot be converted; {instead}"
        )
    if _a_phase_sets_the_step(doc):
        raise _CannotRewrite(
            f"a phase overrides the timestep, so the count has no single value; {instead}"
        )
    try:
        return parse_step_spec(_plain(time["step_value"]), _plain(time.get("step_unit")))
    except ValueError as exc:
        raise _CannotRewrite(f"the timestep cannot be read ({exc})") from exc


def _steps_to_duration(value: Any, doc: Any) -> str:
    """Turn a count of timesteps into the duration it spanned, in the step's own unit.

    The extent rules of a network output were counts of timesteps and are now
    durations. ``N`` steps of the ``[simulation.time]`` step are written as
    ``N`` times that step (``2`` monthly steps are ``"2 months"``), which the run
    converts back to exactly ``N`` steps.
    """
    step, unit = _time_step_of(value, doc, "write the duration, such as '1 month'")
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
)
"""Where the two extent rules are written: the output and the figure."""

_EXTENT_RULE_KEYS = (
    ("maximal_flowing_steps", "maximal_flowing_duration"),
    ("minimal_dry_steps", "minimal_dry_duration"),
)

RENAMED_KEYS: tuple[KeyRename, ...] = (
    *(
        KeyRename(scope, old, new, since=ALPHA_FORM)
        for scope, renames in CALIBRATION_RENAMES.items()
        if not scope.startswith(_OUTPUTS)
        for old, (new, _meaning) in renames.items()
    ),
    KeyRename("display.overrides.{*}", "timestep", "time", since=ALPHA_FORM),
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
    KeyRename("flow.bc.{*}.forcing", "mode", "kind", since=ALPHA_FORM),
    KeyRename("flow.ic", "type", "kind", since=ALPHA_FORM),
    KeyRename("flow.ic.h", "type", "kind", since=ALPHA_FORM),
    KeyRename("flow.param.{*}.field_vertical_profile", "mode", "kind", since=ALPHA_FORM),
    KeyRename("flow.sinks_sources.lakes.{*}.outlets[*]", "couttype", "kind", since=ALPHA_FORM),
    KeyRename("flow.sinks_sources.lakes.{*}", "stageinit", "initial_stage", since=ALPHA_FORM),
    KeyRename("geographic.catchment", "catch_def", "kind", since=ALPHA_FORM),
    KeyRename("simulation.process[*]", "type", "kind", since=ALPHA_FORM),
    KeyRename("solver.backend", "backend", "kind", since=ALPHA_FORM),
    *(
        KeyRename("transport.modflow6prt.parameters", f"{name}_days", name, since=ALPHA_FORM)
        for name in (
            "release_times",
            "track_times",
            "track_time_step",
            "stop_time",
            "stop_travel_time",
        )
    ),
    *(KeyRename("flow.param", old, new, since=ALPHA_FORM) for old, new in OLD_PROPERTY_IDS.items()),
)
"""Every key a file wrote under another name, with the name that replaced it.

A load reads the old name under the new one and warns; ``hmp doctor --fix-config``
rewrites the file. A row of ``[calibration]`` is refused on load instead
(:attr:`KeyRename.refused_on_load`). A sealed run config is renamed on read, in silence,
so a run on disk replays. Each model lists the old key in ``model_refused_keys`` or
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
    changes = _rename_keys(doc, sealed=True)
    changes.extend(_rename_figures(doc))
    changes.extend(_rewrite_search_options(doc, sealed=True))
    changes.extend(_rewrite_cost_margin(doc, sealed=True))
    changes.extend(_migrate_refused_scope(doc, where=""))
    changes.extend(_migrate_calibration_forms(doc, sealed=True, context=doc))
    return changes


def _rename_keys(doc: Any, *, sealed: bool, context: Any = None) -> list[str]:
    """Apply :data:`RENAMED_KEYS` to *doc*, then to the dotted paths it writes."""
    reading = doc if context is None else context
    changes = _rename_tables(doc, context=reading, sealed=sealed)
    changes.extend(_rewrite_dotted_paths(doc, context=reading, sealed=sealed))
    return changes


def _rename_tables(doc: Any, *, context: Any, sealed: bool, prefix: str = "") -> list[str]:
    """Apply :data:`RENAMED_KEYS` to the tables of *doc*, a document or one written nested."""
    changes: list[str] = []
    for rule in RENAMED_KEYS:
        if rule.sealed_only and not sealed:
            continue
        for where, table in _tables_at(doc, rule.scope):
            base = f"{prefix}{where}"
            label = f"{base}.{rule.old}" if base else rule.old
            told = _rename_directives(table, rule, label)
            if rule.old in table:
                told.extend(_rename_one(table, rule, label, context=context, sealed=sealed))
            changes.extend(_refused(told) if rule.refused_on_load else told)
    return changes


def _rename_one(
    table: Any, rule: KeyRename, label: str, *, context: Any, sealed: bool
) -> list[str]:
    """Rename one key of *table*, or say why it stays."""
    if sealed and rule.sealed_drop:
        del table[rule.old]
        return [f"{label} dropped (sealed)"]
    if rule.new in table:
        return [f"{label}{CANNOT_REWRITE}{rule.new!r} is given too, keep one"]
    value = _plain(table[rule.old])
    if rule.convert is not None:
        try:
            value = rule.convert(value, context)
        except _CannotRewrite as reason:
            if sealed and rule.sealed_drop_unconverted:
                del table[rule.old]
                return [f"{label} dropped (sealed): {reason}"]
            return [f"{label}{CANNOT_REWRITE}{reason}"]
    _move_key(table, rule.old, rule.new, value)
    return [f"{label} -> {rule.new}"]


def _rename_directives(table: Any, rule: KeyRename, label: str) -> list[str]:
    """Rename ``<old>__append``, ``<old>__merge`` and ``<old>__delete``, which name the key too."""
    changes: list[str] = []
    for suffix in DIRECTIVE_SUFFIXES:
        old, new = rule.old + suffix, rule.new + suffix
        if old not in table:
            continue
        if new in table:
            changes.append(f"{label}{suffix}{CANNOT_REWRITE}{new!r} is given too, keep one")
            continue
        _move_key(table, old, new, _plain(table[old]))
        changes.append(f"{label}{suffix} -> {new}")
    return changes


@dataclass(frozen=True)
class MovedPath:
    """One dotted path that moved: a row of :data:`RENAMED_KEYS` or :data:`MOVED_TABLES`.

    ``old`` and ``new`` are the parts of the path, with ``{*}`` for a free name. A
    path under ``old`` moves with it, whatever follows.
    """

    old: tuple[str, ...]
    new: tuple[str, ...]
    rule: KeyRename | TableMove

    def rewrite(self, path: str) -> str | None:
        """Return *path* under the new name, or ``None`` when it does not start with ``old``."""
        try:
            parts = list(parse(path).parts)
        except ValueError:
            # Not a path this table can read: the place that reads it refuses it.
            return None
        suffix = next((s for s in DIRECTIVE_SUFFIXES if parts[-1].endswith(s)), "")
        parts[-1] = parts[-1].removesuffix(suffix)
        if len(parts) < len(self.old):
            return None
        free: list[str] = []
        for token, part in zip(self.old, parts, strict=False):
            if token == "{*}":
                free.append(part)
            elif token != part:
                return None
        names = iter(free)
        moved = [next(names) if token == "{*}" else token for token in self.new]
        return f"{DottedPath((*moved, *parts[len(self.old) :]))}{suffix}"

    @property
    def converts(self) -> bool:
        """Whether the value changes form on the way, which a path alone cannot do."""
        return isinstance(self.rule, KeyRename) and self.rule.convert is not None

    @property
    def refused_on_load(self) -> bool:
        """Whether a load refuses this path, as :attr:`KeyRename.refused_on_load` says."""
        return isinstance(self.rule, KeyRename) and self.rule.refused_on_load


def moved_paths(*, sealed: bool = False) -> tuple[MovedPath, ...]:
    """Return every dotted path that moved, in the order of the two tables.

    It is read at each call, so a new row of :data:`RENAMED_KEYS` or
    :data:`MOVED_TABLES` reaches every place a path is written. A row whose scope
    walks a list has no dotted path: a path takes no index.
    """
    rows = [
        MovedPath(
            (*rule.scope.split("."), rule.old),
            (*rule.scope.split("."), rule.new),
            rule,
        )
        for rule in RENAMED_KEYS
        if "[*]" not in rule.scope and (sealed or not rule.sealed_only)
    ]
    rows.extend(
        MovedPath(tuple(move.old.split(".")), tuple(move.new.split(".")), move)
        for move in MOVED_TABLES
    )
    return tuple(rows)


def rewrite_dotted_path(path: str, *, sealed: bool = False) -> str:
    """Return a dotted path of the document under its current name.

    A path whose value changes form on the way stays as it is, and the place that
    reads it refuses it.
    """
    for row in moved_paths(sealed=sealed):
        if not row.converts:
            path = row.rewrite(path) or path
    return path


_PHASES = "calibration.phases[*]"
_BLOCKS = "calibration.objective_blocks[*]"
_PATH_KEYS = ("sites.bind", "sites.recipes.{*}.set")
"""Tables of the document whose keys are dotted paths, besides the overrides of a phase."""

_PARAMETERS = "calibration.parameters.{*}"
_PATH_VALUES = ("path", "target")
"""The keys of a calibration parameter whose value is a dotted path."""


def _rewrite_dotted_paths(doc: Any, *, context: Any, sealed: bool) -> list[str]:
    """Rewrite the paths *doc* writes as keys and values, by :func:`moved_paths`."""
    changes: list[str] = []
    for where, phase in _tables_at(doc, _PHASES):
        overrides = phase.get("overrides")
        if isinstance(overrides, Mapping):
            label = f"{where}.overrides"
            changes.extend(_rewrite_path_keys(overrides, label, context=context, sealed=sealed))
            # A phase may write the same keys as nested tables instead.
            changes.extend(
                _rename_tables(overrides, context=context, sealed=sealed, prefix=f"{label}.")
            )
            changes.extend(_move_the_tables(overrides, context))
    for scope in _PATH_KEYS:
        for where, table in _tables_at(doc, scope):
            changes.extend(
                _rewrite_path_keys(
                    table, where, context=context, sealed=sealed, holds_values=scope != "sites.bind"
                )
            )
    changes.extend(_rewrite_path_values(doc, sealed=sealed))
    return changes


def _rewrite_path_keys(
    table: Any, where: str, *, context: Any, sealed: bool, holds_values: bool = True
) -> list[str]:
    """Rewrite the dotted keys of *table*. *holds_values* says its values are key values."""
    changes: list[str] = []
    beaten = _beaten_moves(table, context)
    for row in moved_paths(sealed=sealed):
        for key in [str(key) for key in table]:
            renamed = row.rewrite(key)
            if renamed is None:
                continue
            label = f'{where}."{key}"'
            if row.rule in beaten:
                del table[key]
                changes.append(f"{label} dropped ({beaten[row.rule].section} is the flow solver)")
            elif renamed in table:
                changes.append(f'{label}{CANNOT_REWRITE}"{renamed}" is given too, keep one')
            elif sealed and isinstance(row.rule, KeyRename) and row.rule.sealed_drop:
                del table[key]
                changes.append(f"{label} dropped (sealed)")
            else:
                moved = _move_path_key(
                    table, key, renamed, row, label, context, sealed, holds_values
                )
                changes.extend(_refused(moved) if row.refused_on_load else moved)
    return changes


def _move_path_key(
    table: Any,
    key: str,
    renamed: str,
    row: MovedPath,
    label: str,
    context: Any,
    sealed: bool,
    holds_values: bool,
) -> list[str]:
    """Move one dotted key to its new path, with its value in the new form."""
    value = _plain(table[key])
    if row.converts:
        if not holds_values:
            return [
                f"{label}{CANNOT_REWRITE}the value of this key changes form under its new "
                "name, and a bind line holds a column; write the new key and its values by hand"
            ]
        try:
            value = row.rule.convert(value, context)
        except _CannotRewrite as reason:
            if sealed and row.rule.sealed_drop_unconverted:
                del table[key]
                return [f"{label} dropped (sealed): {reason}"]
            return [f"{label}{CANNOT_REWRITE}{reason}"]
    _move_key(table, key, renamed, value)
    return [f'{label} -> "{renamed}"']


def _rewrite_path_values(doc: Any, *, sealed: bool) -> list[str]:
    """Rewrite ``path`` and ``target`` of the calibration parameters."""
    changes: list[str] = []
    for where, table in _tables_at(doc, _PARAMETERS):
        for name in _PATH_VALUES:
            value = _plain(table.get(name))
            if not isinstance(value, str):
                continue
            label = f"{where}.{name}"
            moved = rewrite_dotted_path(value, sealed=sealed)
            if moved != value:
                table[name] = moved
                changes.append(f"{label} {value!r} -> {moved!r}")
            if any(row.converts and row.rewrite(moved) for row in moved_paths(sealed=sealed)):
                changes.append(
                    f"{label}{CANNOT_REWRITE}the key {moved!r} takes another form under its "
                    "new name, so a search cannot move it as it is; write its new path and "
                    "its bounds by hand"
                )
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


def _rewrite_cost_margin(doc: Any, *, sealed: bool, context: Any = None) -> list[str]:
    """Turn ``tolerance`` and ``mode`` of the uncertainty tables into one ``cost_margin``.

    The unit is the one the old mode implied: a relative width, or one left
    unwritten on a search that is no network distance, was a share of the best
    cost (``"5%"``); an absolute one, or one left unwritten on a search scored
    only by network distances, was in meters. A phase read its keys over the
    section's, so the pair a phase read is rewritten into the phase. What the
    doctor cannot decide it leaves, with the reason. A sealed config drops what
    it cannot write: the width only qualifies a calibrated value, it never
    moved one, so the run replays the same. What the search scores and what a
    phase inherits are read from *context*, since a parent file can hold them.
    """
    calibration = doc.get("calibration") if isinstance(doc, Mapping) else None
    if not isinstance(calibration, Mapping):
        return []
    section = calibration.get("uncertainty")
    reading = (doc if context is None else context).get("calibration")
    if not isinstance(reading, Mapping):
        reading = calibration
    read_section = reading.get("uncertainty")
    inherited = (
        (_plain(read_section.get("tolerance")), _plain(read_section.get("mode")))
        if isinstance(read_section, Mapping)
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
                        _scored_on_distances(reading, phase),
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
                _scored_on_distances(reading, None),
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
    normalized cost is no longer in meters. ``None`` when a protocol still has
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


def _rewrite_search_options(doc: Any, *, sealed: bool, context: Any = None) -> list[str]:
    """Rewrite the method options that bounded a search, now that ``max_trials`` does.

    An option that counted evaluations (``maxfev``, ``max_evaluations``, the
    ``max_iter`` of gp_mapping) is moved into the budget of the table that
    writes it, the smaller of the two when both are written, since the search
    stopped at the first one it met. ``maxiter`` counts iterations or
    generations, not evaluations: the doctor leaves it, with the reason. A
    sealed config drops both, because a run on disk is replayed as one solve and
    never searches again. The chain of ``da_mh_gp`` is ``chain_length``. The method
    and the budget can sit in a parent, so *context* is read for what the table lacks.
    """
    changes: list[str] = []
    for search in _SEARCH_SCOPES:
        source = doc if context is None else context
        read = dict(_tables_at(source, search.scope))
        # A phase that writes no method or budget takes the ones of [calibration].
        section = source.get("calibration") if search.scope == "calibration.phases[*]" else None
        for where, table in _tables_at(doc, search.scope):
            inherited = {**(section if isinstance(section, Mapping) else {}), **read.get(where, {})}
            method = (
                _plain(table.get(search.method))
                or _plain(inherited.get(search.method))
                or search.default_method
            )
            for options_key in search.options:
                options = table.get(options_key)
                if not isinstance(options, Mapping):
                    continue
                prefix = f"{where}.{options_key}" if where else options_key
                before = len(changes)
                for key in [key for key in options if key in _OPTION_NAMES]:
                    label = f"{prefix}.{key}"
                    changes.extend(
                        _rewrite_option(
                            table, options, key, method, label, search, inherited, sealed=sealed
                        )
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
    inherited: Mapping[str, Any],
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
    declared = _plain(table.get(search.budget, inherited.get(search.budget)))
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
    comment = _comment_of(table, old)
    del table[old]
    item = _moved_table(original) or _scalar_item(value, comment)
    if position is None or item is None:
        table[new] = value
        if comment.startswith("#") and hasattr(table[new], "comment"):
            table[new].comment(comment[1:].strip())
        return
    table.value._insert_at(position, new, item)


def _comment_of(table: Any, key: str) -> str:
    """Return the comment of the line of ``key``, empty for a plain mapping."""
    # A tomlkit table hands out a boolean as a plain bool, which holds no comment.
    item = table.value.item(key) if _position(table, key) is not None else table.get(key)
    return getattr(getattr(item, "trivia", None), "comment", "") or ""


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
    if not isinstance(value, int | float | str):
        return None
    item = tomlkit.item(value)
    if comment.startswith("#"):
        item.comment(comment[1:].strip())
    return item


def _tables_at(doc: Any, scope: str) -> list[tuple[str, Any]]:
    """Return every table of *doc* that *scope* names, with where it sits.

    ``a.b`` descends by name, ``a[*]`` walks the tables of a list, ``{*}`` walks
    the tables under free names. A name that leads to no table is skipped. A list
    a file adds to or merges is walked too: ``a__append`` and ``a__merge`` hold the
    same tables as ``a``.
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
                for name in (token[:-3], f"{token[:-3]}__append", f"{token[:-3]}__merge"):
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


Layer = tuple[str | Path | None, Any]
"""Where a part of a document came from, and what it writes."""


def _is_sealed(source: str | Path | None) -> bool:
    """Whether *source* is the frozen config of a run, which no one edits."""
    return (
        source is not None and source not in COMMAND_LINE_SOURCES and is_sealed_run_config(source)
    )


def _reading_context(layers: Sequence[Layer]) -> dict[str, Any]:
    """Return the layers merged as they are written, for a rule that reads another key.

    One layer stands alone: an overlay read by itself holds directives that have
    nothing to apply to yet.
    """
    if len(layers) == 1:
        return copy.deepcopy(_plain(layers[0][1]))
    merged: dict[str, Any] = {}
    for _, doc in layers:
        merged = merge_toml_payloads(merged, copy.deepcopy(_plain(doc)))
    return merged


def _tell(source: str | Path | None, changes: Sequence[str]) -> None:
    """Warn about *changes* under the name of *source*, in silence for a sealed file."""
    if _is_sealed(source):
        if changes:
            _logger.debug("%s: sealed config read as renamed: %s", source, "; ".join(changes))
        return
    rewritable = source not in COMMAND_LINE_SOURCES
    refused = [change for change in changes if isinstance(change, _Refused)]
    if refused:
        refuse_old_forms(source, refused, rewritable=rewritable)
    for change in changes:
        if change in _QUIET_CHANGES:
            _logger.debug("%s: %s", source or "config", change)
        else:
            warn_old_form(source, change, rewritable=rewritable)


def migrate_layers(layers: Sequence[Layer]) -> list[str]:
    """Migrate each layer of a document on its own, in place, before the merge.

    A key is told under the name of the layer that holds it. A key a rule cannot
    move yet stays, and :func:`migrate_merged_doc` has the last word on it, since the
    merged document may hold what the rule needed. Never touches a file.
    """
    context = _reading_context(layers)
    changes: list[str] = []
    for source, doc in layers:
        own = _file_rules(doc, context=context, sealed=_is_sealed(source))
        _tell(source, [change for change in own if CANNOT_REWRITE not in change])
        changes.extend(own)
    return changes


def _change_label(change: str) -> str:
    """Return the key a change speaks of: what comes before its verb."""
    for verb in (" -> ", CANNOT_REWRITE, " dropped", " ("):
        change = change.split(verb, 1)[0]
    return change


def _labels_of(doc: Any) -> set[str]:
    """Return the keys the rules would touch in *doc*, which stays as it is."""
    try:
        return {_change_label(change) for change in _every_rule(copy.deepcopy(_plain(doc)))}
    except ValueError:
        # A value only the whole document can refuse: the merged pass says it.
        return set()


def migrate_merged_doc(doc: Any, layers: Sequence[Layer] = ()) -> list[str]:
    """Run every rule on the merged document, in place, for what waited for the merge.

    A change is told under the last layer that holds its key, and in silence with no
    *layers*, for a document whose layers were told already.
    """
    leaf = layers[-1][0] if layers else None
    sealed = _is_sealed(leaf)
    if not _every_rule(copy.deepcopy(_plain(doc)), sealed=sealed):
        return []
    held = [(source, _labels_of(own)) for source, own in layers]
    changes = _every_rule(doc, sealed=sealed)
    for change in changes if layers else ():
        label = _change_label(change)
        holder = next(
            (
                source
                for source, labels in reversed(held)
                if any(label.startswith(key) or key.startswith(label) for key in labels)
            ),
            leaf,
        )
        _tell(holder, [change])
    return changes


def migrate_config_doc_on_load(doc: Any, *, source: str | Path | None = None) -> list[str]:
    """Apply every migration to *doc* in memory, for one document read on its own.

    Reading a file goes through :func:`migrate_layers` and :func:`migrate_merged_doc`,
    which the loader calls. This is both of them on a payload that came whole. Never
    touches the file *doc* came from. Warns once per key and per file, naming the old
    key, the new key and the doctor; says nothing when the document was already current.

    A *source* that is the frozen config of a run already on disk
    (:func:`~hydromodpy.core.state.result_dirs.is_sealed_run_config`) is read in silence,
    with the rules of :func:`migrate_sealed_config_doc`: no one edits a sealed file.
    """
    layers = [(source, doc)]
    changes = migrate_layers(layers)
    changes.extend(migrate_merged_doc(doc, layers))
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
# not an export any more: `hmp publish --container tar` writes it from a sealed run.
_ARCHIVE_FORMAT = "hmp"
_ARCHIVE_SUFFIX = ".hmp"
_ARCHIVE_DROPPED = (
    '[export] archive request(s) dropped (package = true, fmt = "hmp", a .hmp file): the '
    "archive of a run is written by hmp publish --container tar, not by an export"
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


def _drop_the_validity_ratio(doc: Any, *, sealed: bool) -> list[str]:
    """Drop ``roptim_max`` from the network outputs, replaced by ``validity_length``.

    The bound of Eq. 4 is a length now. ``roptim_max = 2`` said "two cells",
    which ``validity_length = "auto"``, the default, says too, so the key goes.
    Another ratio has no exact length without the cell size of the run, which
    a TOML file does not hold: it is refused with the length to write instead.
    A sealed config drops it whatever its value, since a replay never recomputes Eq. 4.
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
        if sealed:
            del output["roptim_max"]
            changes.append(f"{path} dropped (sealed)")
            continue
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
    dropped: list[str] = []
    for label, phase in _tables_at(doc, _PHASES):
        overrides = phase.get("overrides")
        if not isinstance(overrides, Mapping):
            continue
        where = f"{label}.overrides"
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


_OLD_DRAIN_KINDS = frozenset({"cauchy", "robin"})


def _rename_the_drain_kinds(doc: Any) -> list[str]:
    """Rewrite ``kind = 'cauchy'`` and ``kind = 'robin'`` as ``kind = 'drain'``.

    Both built one linear drain under every solver, with the same numbers. Nothing read
    the difference, and the Boussinesq closure has its own key.
    """
    changes: list[str] = []
    for where, table in _tables_at(doc, "flow.bc.{*}"):
        if _plain(table.get("kind")) in _OLD_DRAIN_KINDS:
            changes.append(f"{where}.kind {_plain(table['kind'])!r} -> 'drain'")
            table["kind"] = "drain"
    for where, table in _path_tables(doc):
        for key in [str(key) for key in table]:
            parts = key.split(".")
            if (
                len(parts) == 4
                and parts[:2] == ["flow", "bc"]
                and parts[3] == "kind"
                and _plain(table[key]) in _OLD_DRAIN_KINDS
            ):
                changes.append(f"{where}.\"{key}\" {_plain(table[key])!r} -> 'drain'")
                table[key] = "drain"
    return changes


def _write_out_the_bare_buffer(doc: Any) -> list[str]:
    """Rewrite a bare number ``buff_area = 10`` as ``"10% of sqrt(area)"``.

    A bare number has always been the rule of version 1, a distance of that percent of
    the square root of the catchment area. The explicit form draws the same distance,
    so the domain does not move, and the file says what the number means.
    """
    changes: list[str] = []
    for where, table in _tables_at(doc, "geographic.catchment"):
        value = _plain(table.get("buff_area"))
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            continue
        table["buff_area"] = f"{float(value):g}% of sqrt(area)"
        changes.append(f"{where}.buff_area {value!r} -> '{float(value):g}% of sqrt(area)'")
    return changes


def _rename_the_property_ids(doc: Any) -> list[str]:
    """Rewrite what names a property next to its key: ``param_list``, and the id of its field.

    The key itself is a row of :data:`RENAMED_KEYS`.
    """
    flow = doc.get("flow") if isinstance(doc, Mapping) else None
    if not isinstance(flow, Mapping):
        return []
    changes: list[str] = []
    listed = _plain(flow.get("param_list"))
    if isinstance(listed, list) and any(name in OLD_PROPERTY_IDS for name in listed):
        renamed = [OLD_PROPERTY_IDS.get(name, name) for name in listed]
        flow["param_list"] = renamed
        changes.append(f"flow.param_list {listed!r} -> {renamed!r}")
    for where, field_table in _tables_at(doc, "flow.param.{*}.field"):
        if _plain(field_table.get("id")) in OLD_PROPERTY_IDS:
            old = _plain(field_table["id"])
            field_table["id"] = OLD_PROPERTY_IDS[old]
            changes.append(f"{where}.id {old!r} -> {OLD_PROPERTY_IDS[old]!r}")
    return changes


_TRANSPORT_NEVER_READ = (
    "param_list",
    "param",
    "ic",
    "bc",
    "sinks_sources",
    "active_sinks_sources",
    "active_bc",
)
"""Keys ``[transport]`` inherited from a base class. No transport solver read them."""


def _drop_what_transport_never_read(doc: Any) -> list[str]:
    """Drop the inherited keys of ``[transport]``, whatever they held."""
    transport = doc.get("transport") if isinstance(doc, Mapping) else None
    if not isinstance(transport, Mapping):
        return []
    changes: list[str] = []
    for key in _TRANSPORT_NEVER_READ:
        if key in transport:
            del transport[key]
            changes.append(f"transport.{key} dropped (no transport solver read it)")
    return changes


_ACTIVATION_LISTS = ("active_bc", "active_sinks_sources")
_LAKE_NAMES = frozenset({"lake", "reservoir"})
_COLLECTIONS = {"lakes": "active_bc", "sfr": "active_bc", "wells": "active_sinks_sources"}
"""The tables of ``sinks_sources`` that hold entries under free names, and the list that named them."""


def _activation_keys_of(flow: Mapping[str, Any]) -> list[str]:
    """Return the keys of a flow section that write a list, a directive of one included."""
    keys: list[str] = []
    for key in flow:
        name = str(key)
        for suffix in DIRECTIVE_SUFFIXES:
            name = name.removesuffix(suffix)
        if name in _ACTIVATION_LISTS:
            keys.append(str(key))
    return keys


def _sections_of(flow: Any) -> list[tuple[str, str, str]]:
    """Return the tables a flow section declares: their path under it, their list, their name."""
    if not isinstance(flow, Mapping):
        return []
    found: list[tuple[str, str, str]] = []
    bc = flow.get("bc")
    if isinstance(bc, Mapping):
        found.extend(
            (f"bc.{key}", "active_bc", str(key))
            for key, table in bc.items()
            if isinstance(table, Mapping)
        )
    tables = flow.get("sinks_sources")
    if isinstance(tables, Mapping):
        for name in ("recharge", "etp"):
            if isinstance(tables.get(name), Mapping):
                found.append((f"sinks_sources.{name}", "active_sinks_sources", name))
        for collection, listed_in in _COLLECTIONS.items():
            entries = tables.get(collection)
            if isinstance(entries, Mapping):
                name = "lake" if collection == "lakes" else collection
                found.extend(
                    (f"sinks_sources.{collection}.{key}", listed_in, name)
                    for key, table in entries.items()
                    if isinstance(table, Mapping)
                )
    return found


def _is_listed(name: str, listed: Sequence[str]) -> bool:
    """Whether *listed* names a table called *name*: ``reservoir`` was another word for lake."""
    return name in listed or (name in _LAKE_NAMES and bool(_LAKE_NAMES & set(listed)))


def _path_of_a_name(list_name: str, name: str) -> str:
    """Return the table a name of a list stands for, under ``flow``."""
    if list_name == "active_bc" and name in _LAKE_NAMES:
        return "sinks_sources.lakes"
    if list_name == "active_bc" and name == "sfr":
        return "sinks_sources.sfr"
    return f"bc.{name}" if list_name == "active_bc" else f"sinks_sources.{name}"


def _list_of(flow: Any, list_name: str) -> list[str] | None:
    """Return what a flow section lists, or ``None`` when it writes no list."""
    value = _plain(flow.get(list_name)) if isinstance(flow, Mapping) else None
    if isinstance(value, list):
        return [str(item).strip() for item in value]
    return None


def _an_empty_table(doc: Any) -> Any:
    return tomlkit.table() if isinstance(doc, tomlkit.TOMLDocument) else {}


def _fold_the_activation_lists(doc: Any, *, context: Any) -> list[str]:
    """Fold ``flow.active_bc`` and ``flow.active_sinks_sources`` into the tables, keeping the meaning.

    A list said what was active, so a table it does not name gets ``enabled = false``,
    a name with no table gets an empty one, and the list goes. *context* is what the
    layers say together, since a list and the tables it speaks of can sit in two files.
    The layer that holds the list writes for all of them. A layer that holds only tables
    switches off its own. A document with no list at all reads under the new rule.
    """
    changes = _fold_the_lists_of_a_path_table(doc, context=context)
    flow = doc.get("flow") if isinstance(doc, Mapping) else None
    reading = context.get("flow") if isinstance(context, Mapping) else None
    if not isinstance(flow, Mapping) or not isinstance(reading, Mapping):
        return changes
    listed = {name: _list_of(reading, name) for name in _ACTIVATION_LISTS}
    if all(value is None for value in listed.values()):
        return changes
    held = _activation_keys_of(flow)
    own = {path for path, _, _ in _sections_of(flow)}
    sections = _sections_of(reading)
    for path, list_name, name in sections:
        if _is_listed(name, listed[list_name] or ()):
            continue
        if listed[list_name] is None and path not in own:
            # No list says anything about a table another file declares: that file was
            # already read under the new rule, or it never had a list to fold.
            continue
        if held or path in own:
            _set_at(doc, f"flow.{path}.enabled", False)
            changes.append(f"flow.{path} not listed in flow.{list_name} -> enabled = false")
    if held:
        declared = {path for path, _, _ in sections}
        for list_name, names in listed.items():
            for name in names or ():
                path = _path_of_a_name(list_name, name)
                if path in declared or any(p.startswith(f"{path}.") for p in declared):
                    continue
                declared.add(path)
                if _value_at(doc, f"flow.{path}") is None:
                    _set_at(doc, f"flow.{path}", _an_empty_table(doc))
                changes.append(f"flow.{list_name} names {name!r} -> [flow.{path}]")
    # Fetched again: a write can leave a proxy of an out-of-order table stale.
    flow = doc["flow"]
    for key in held:
        del flow[key]
        changes.append(f"flow.{key} folded into the tables it listed")
    if not flow:
        del doc["flow"]
    return changes


def _path_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return the tables whose keys are dotted paths: the overrides of a phase, the set of a recipe."""
    found = [
        (f"{where}.overrides", phase["overrides"])
        for where, phase in _tables_at(doc, _PHASES)
        if isinstance(phase.get("overrides"), Mapping)
    ]
    found.extend(_tables_at(doc, "sites.recipes.{*}.set"))
    return found


def _fold_the_lists_of_a_path_table(doc: Any, *, context: Any) -> list[str]:
    """Rewrite a list a phase or a recipe overrides as one ``enabled`` per table.

    A nested ``flow`` table in an override folds on its own. A line of ``[sites.bind]``
    holds a column and no list, so the file keeps it and the loader refuses it.
    """
    reading = context.get("flow") if isinstance(context, Mapping) else None
    sections = _sections_of(reading)
    named: list[tuple[str, str, str]] = []
    for list_name in _ACTIVATION_LISTS:
        for name in _list_of(reading, list_name) or ():
            path = _path_of_a_name(list_name, name)
            if path not in {section[0] for section in sections} and path not in _ANY_ENTRY:
                named.append((path, list_name, name))
    changes: list[str] = []
    for where, table in _path_tables(doc):
        for list_name in _ACTIVATION_LISTS:
            key = f"flow.{list_name}"
            value = _plain(table.get(key))
            if not isinstance(value, list):
                continue
            listed = [str(item).strip() for item in value]
            known = [*sections, *named]
            for path, owner, name in known:
                if owner != list_name:
                    continue
                table[f"flow.{path}.enabled"] = _is_listed(name, listed)
            for name in listed:
                path = _path_of_a_name(list_name, name)
                if path in _ANY_ENTRY or any(section[0] == path for section in known):
                    continue
                table[f"flow.{path}.enabled"] = True
            del table[key]
            changes.append(f'{where}."{key}" -> one enabled per table')
        nested = table.get("flow")
        if isinstance(nested, Mapping) and any(name in nested for name in _ACTIVATION_LISTS):
            merged = {"flow": {**dict(_plain(reading) or {}), **dict(_plain(nested))}}
            changes.extend(_fold_the_activation_lists(table, context=merged))
    return changes


_ANY_ENTRY = frozenset({"sinks_sources.lakes", "sinks_sources.sfr", "sinks_sources.wells"})
"""A name that stands for all the entries of a table, and names no table of its own."""


def _persistence_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return every ``(path, table)`` pair holding a persistence section."""
    results = (doc.get("simulation") or {}).get("results")
    candidates = [
        ("persistence", doc.get("persistence")),
        ("simulation.results.persistence", (results or {}).get("persistence")),
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
            kind = str(process.get("kind", process.get("type", ""))).strip().lower()
            solvers = process.get("solvers")
            process_id = process.get("id")
        else:
            kind = str(getattr(process, "kind", "")).strip().lower()
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
            tag = name.get("kind", name.get("backend"))
            name = name.get("name") if tag == "custom" else tag
    return _SOLVER_SECTION_OF.get(str(name or "").strip().lower(), "modflow6")


def _difference(dropped: Any, kept: Any) -> str:
    """Return where a dropped value departs from the kept one, or an empty string."""
    dropped, kept = _plain(dropped), _plain(kept)
    if not (isinstance(dropped, Mapping) and isinstance(kept, Mapping)):
        return "" if dropped == kept else f"{dropped!r} against {kept!r}"

    def shown(table: Mapping[str, Any], key: str) -> str:
        return repr(table[key]) if key in table else "unset"

    differences = [
        f"{key} = {shown(dropped, key)} against {shown(kept, key)}"
        for key in sorted(set(dropped) | set(kept))
        if dropped.get(key) != kept.get(key)
    ]
    return ", ".join(differences)


def _value_at(doc: Any, path: str) -> Any:
    """Return what *doc* holds at the dotted *path*, or ``None``."""
    *parents, key = path.split(".")
    table = _descend(doc, parents)
    return None if table is None else table.get(key)


def _set_at(doc: Any, path: str, value: Any) -> None:
    """Write *value* at the dotted *path* of *doc*, creating the tables on the way."""
    *parents, key = path.split(".")
    is_file = isinstance(doc, tomlkit.TOMLDocument)
    table = doc
    for part in parents:
        child = table.get(part)
        if not isinstance(child, Mapping):
            table[part] = tomlkit.table(is_super_table=True) if is_file else {}
            child = table[part]
        table = child
    moved = _moved_table(value)
    table[key] = value if moved is None else moved


def _moves_by_target() -> dict[str, list[TableMove]]:
    """Return the rows of :data:`MOVED_TABLES`, by the path they lead to."""
    grouped: dict[str, list[TableMove]] = {}
    for move in MOVED_TABLES:
        grouped.setdefault(move.new, []).append(move)
    return grouped


def _kept_move(written: Sequence[TableMove], context: Any) -> TableMove:
    """Return the one of several moves to one path that wins: the flow solver's."""
    if len(written) > 1:
        section = _flow_solver_section(context)
        for move in written:
            if move.section == section:
                return move
    return written[0]


def _move_the_tables(doc: Any, context: Any) -> list[str]:
    """Move what :data:`MOVED_TABLES` lists to its new path.

    Several old paths can lead to one, as the table of each solver leads to
    ``[domain.layers]``. When the document writes more than one, *context* decides:
    the one of the flow solver is kept, since it built the runs of the file, and the
    others are dropped with a line that says whether they held other values. The new
    path written in the same file wins over all of them.
    """
    changes: list[str] = []
    for target, moves in _moves_by_target().items():
        found = [move for move in moves if _value_at(doc, move.old) is not None]
        if found:
            changes.extend(_move_to(doc, target, moves, found, context))
        changes.extend(_move_directives(doc, target, moves))
    return changes


def _move_to(
    doc: Any, target: str, moves: Sequence[TableMove], found: Sequence[TableMove], context: Any
) -> list[str]:
    """Move or drop each of the old paths *found* in *doc*."""
    written = [move for move in moves if _value_at(context, move.old) is not None] or found
    kept = _kept_move(written, context)
    existing = _value_at(doc, target)
    winner = existing if existing is not None else _value_at(context, kept.old)
    changes: list[str] = []
    moved = None
    for move in found:
        value = _value_at(doc, move.old)
        _drop_table(doc, move.old)
        if existing is None and move == kept:
            moved = value
            changes.append(f"{move.old} -> [{target}]")
            continue
        owner = (
            f"[{target}] already set"
            if existing is not None
            else (f"{kept.section} is the flow solver")
        )
        difference = _difference(value, winner)
        held = f"it held other values: {difference}" if difference else "same values"
        changes.append(f"{move.old} dropped ({owner}; {held})")
    if moved is not None:
        _set_at(doc, target, moved)
    return changes


def _move_directives(doc: Any, target: str, moves: Sequence[TableMove]) -> list[str]:
    """Move ``<old>__delete``, ``<old>__append`` and ``<old>__merge`` of a moved path."""
    changes: list[str] = []
    for move in moves:
        for suffix in DIRECTIVE_SUFFIXES:
            value = _value_at(doc, move.old + suffix)
            if value is None:
                continue
            _drop_table(doc, move.old + suffix)
            _set_at(doc, target + suffix, _plain(value))
            changes.append(f"{move.old}{suffix} -> {target}{suffix}")
    return changes


def _beaten_moves(table: Any, context: Any) -> dict[TableMove, TableMove]:
    """Return the moves a table of dotted keys writes that lose, with the one that wins."""
    beaten: dict[TableMove, TableMove] = {}
    for moves in _moves_by_target().values():
        written = [
            move
            for move in moves
            if any(key == move.old or str(key).startswith(f"{move.old}.") for key in table)
        ]
        if len(written) > 1:
            kept = _kept_move(written, context)
            beaten.update({move: kept for move in written if move != kept})
    return beaten


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


_PERSISTENCE = "simulation.results.persistence", "persistence"

HAND_WRITTEN_FORMS: tuple[OldForm, ...] = (
    OldForm("simulation.on_collision", "simulation.if_exists", ALPHA_FORM),
    OldForm("simulation.run_id", "simulation.name", ALPHA_FORM),
    OldForm("simulation.results.export", "export", ALPHA_FORM),
    OldForm("simulation.results.solver_scratch", None, ALPHA_FORM),
    *(OldForm(f"{path}.save_lock", None, ALPHA_FORM) for path in _PERSISTENCE),
    OldForm("calibration.warmup_periods", "calibration.window", ALPHA_FORM),
    OldForm("calibration.objective_blocks[*].warmup", "calibration.window", ALPHA_FORM),
    *(
        OldForm(f"{scope}.observed_station_id", "site.gauge", ALPHA_FORM)
        for scope in ("calibration", "calibration.phases[*]", "calibration.protocol")
    ),
    *(OldForm(table, None, ALPHA_FORM) for table in RETIRED_RESULTS_TABLES),
    *(
        OldForm(f"export.{key}", "export", ALPHA_FORM)
        for key in (*_EXPORT_TOGGLES, "csv_timeseries", "package", "output_dir", "artifacts")
    ),
    OldForm("export.variables.{*}", "export.variables", ALPHA_FORM),
    OldForm("export.times", "export.time", ALPHA_FORM),
    *(OldForm(f"{section}.tgrid", None, ALPHA_FORM) for section in _SOLVER_SECTIONS),
    OldForm("geographic.bottom_path", "data.substratum.sources", ALPHA_FORM),
    OldForm(
        "calibration.outputs.{*}.roptim_max",
        "calibration.outputs.{*}.verdict.validity_length",
        ALPHA_FORM,
    ),
    *(OldForm(old, new, ALPHA_FORM) for old, new in _NETWORK_FORMS.items()),
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
    OldForm("flow.active_bc", "flow.bc", ALPHA_FORM),
    OldForm("flow.active_sinks_sources", "flow.sinks_sources", ALPHA_FORM),
    *(OldForm(f"transport.{key}", None, ALPHA_FORM) for key in _TRANSPORT_NEVER_READ),
)
"""The old forms a function of this module rewrites, one line for each key it reads."""

OLD_VALUES: tuple[tuple[str, str, str], ...] = (
    ("flow.bc.kind", "cauchy", "drain"),
    ("flow.bc.kind", "robin", "drain"),
    ("geographic.catchment.buff_area", "10", "10% of sqrt(area)"),
)
"""Values a rule rewrites under a key that keeps its name, as (key, old value, new value)."""

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
    OldForm("data.project_crs", "geographic.crs_project", ALPHA_FORM, rewritten=False),
    OldForm(
        "calibration.outputs.{*}.max_unreachable_fraction",
        "calibration.outputs.{*}.verdict.max_catchment_mismatch",
        ALPHA_FORM,
        rewritten=False,
    ),
    OldForm("data.hydrography.sources[*].typename", None, ALPHA_FORM, rewritten=False),
    *(
        OldForm(f"flow.param.{old}", f"flow.param.{new}", ALPHA_FORM, rewritten=False)
        for old, new in NEVER_READ_IDS.items()
    ),
)
"""The old forms no rule here carries: the models refuse them, or read and ignore them."""


def old_forms() -> tuple[OldForm, ...]:
    """Return every old form of the grammar this build still knows, with its ``since``."""
    return (
        *(
            OldForm(
                f"{rule.scope}.{rule.old}",
                _NETWORK_FORMS.get(f"{rule.scope}.{rule.new}", f"{rule.scope}.{rule.new}"),
                rule.since,
            )
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
    "OLD_VALUES",
    "REFUSED_OR_RETIRED_FORMS",
    "RENAMED_KEYS",
    "RETIRED_RESULTS_TABLES",
    "KeyRename",
    "Layer",
    "MovedPath",
    "OldForm",
    "TableMove",
    "document_path",
    "drop_retired_results_tables",
    "fix_config_chain",
    "fix_config_file",
    "migrate_config_doc",
    "migrate_config_doc_on_load",
    "migrate_layers",
    "migrate_merged_doc",
    "migrate_sealed_config_doc",
    "moved_paths",
    "old_forms",
    "outlived_forms",
    "rewrite_dotted_path",
]
