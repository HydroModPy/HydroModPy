"""TOML config migration for the simulation-management refactor.

Rewrites legacy keys of a parsed document in memory, before validation:

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
  the lockfile is written on every run.
- ``geographic.bottom_path`` -> one ``[[data.substratum.sources]]`` entry,
  ``[domain.depth_model]`` left as it is (the old key was never read)
- ``[simulation.results.derived]`` and ``[simulation.results.budget]`` dropped,
  whatever they held: a run keeps its whole per-cell budget and rebuilds every
  derived field on read, so neither table has anything left to switch
- ``roptim_max`` of a network output under ``[calibration.outputs.<name>]``
  dropped when it is 2, the paper's bound, which ``validity_length = "auto"``
  reproduces; any other value is refused, since a ratio has no length without
  the cell size of the run

This is a migration tool, not a backward-compat shim: the runtime model itself
never accepts the old keys (``extra="forbid"``). ``migrate_config_doc`` is the
one pure document-to-document transform; one caller wraps it.
``migrate_config_doc_on_load`` runs the transform in memory on a payload
already parsed by a caller, without touching the file it came from, and logs
what it changed. ``HydroModPyConfig.from_toml`` calls it on the raw payload,
before validation, so a config written for an earlier schema still loads. The
calibration loader reaches it through the root-config provider, since the
calibration layer does not import this one.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit

from hydromodpy.core.config_kit.export_spec import RUN_FORMATS, format_from_path
from hydromodpy.core.logging import get_logger

_logger = get_logger(__name__)

_SOLVER_SECTIONS = ("modflow6", "modflownwt")

#: The result tables a run no longer reads. A stored config and a user file both
#: drop them, and the docs list them as migrated keys.
RETIRED_RESULTS_TABLES: tuple[str, ...] = (
    "simulation.results.derived",
    "simulation.results.budget",
)


def migrate_config_doc(doc: Any) -> list[str]:
    """Apply the legacy ``[simulation]`` key migrations to a parsed doc in place.

    Works on a plain ``dict`` (``tomllib``) or a ``tomlkit`` document.
    Returns the list of human-readable changes applied.
    """
    changes: list[str] = _drop_dead_result_options(doc)
    changes.extend(_report_retired_results_tables(doc))
    changes.extend(_move_the_bottom_path(doc))
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


def migrate_config_doc_on_load(doc: Any, *, source: str | Path | None = None) -> list[str]:
    """Apply every migration to *doc* in memory, for a config being read, not fixed.

    Meant for ``HydroModPyConfig.from_toml``: called on the freshly parsed
    payload, before Pydantic validation, so a config written for an earlier
    schema still loads. Never touches the file *doc* came from. Logs one line
    naming what changed and the file to rename it in; says nothing when the
    document was already current.
    """
    changes = migrate_config_doc(doc)
    loud = [change for change in changes if change not in _QUIET_CHANGES]
    if loud:
        where = f"{source}" if source is not None else "config"
        _logger.info(
            "%s: migrated %d legacy key(s) on load, not persisted to disk (rename them in %s): %s",
            where,
            len(loud),
            source if source is not None else "<path>",
            "; ".join(loud),
        )
    elif changes:
        _logger.debug("%s: %s", source or "config", "; ".join(changes))
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


__all__ = [
    "RETIRED_RESULTS_TABLES",
    "drop_retired_results_tables",
    "migrate_config_doc",
    "migrate_config_doc_on_load",
]
