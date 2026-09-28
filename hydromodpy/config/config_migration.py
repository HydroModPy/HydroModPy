"""One-shot TOML config migration for the simulation-management refactor.

Rewrites legacy ``[simulation]`` keys in place, preserving comments and layout:

- ``on_collision`` -> ``if_exists``
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
  read them, at the root and under a comparison or testbed overlay
- ``solver_scratch`` and ``persistence.save_lock`` dropped: both drove
  nothing. The solver scratch directory is ``<project>/.hmp/scratch`` and
  the lockfile is written on every run.
- ``geographic.bottom_path`` -> one ``[[data.substratum.sources]]`` entry,
  ``[domain.depth_model]`` left as it is (the old key was never read)
- ``roptim_max`` of a network output under ``[calibration.outputs.<name>]``
  dropped when it is 2, the paper's bound, which ``validity_length = "auto"``
  reproduces; any other value is refused, since a ratio has no length without
  the cell size of the run

This is a migration tool, not a backward-compat shim: the runtime model itself
never accepts the old keys (``extra="forbid"``). ``migrate_config_doc`` is the
one pure document-to-document transform; two callers wrap it. ``fix_config_file``
(reached through ``hmp doctor --fix-config``) rewrites a file on disk once, so a
project TOML catches up for good. ``migrate_config_doc_on_load`` runs the same
transform in memory on a payload already parsed by a caller, without touching
the file it came from, and logs what it changed. ``HydroModPyConfig.from_toml``
calls it on the raw payload, before validation, so a config written for an
earlier schema still loads without the doctor having run on it first. The
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
    schema still loads. Never touches the file *doc* came from - only
    ``fix_config_file`` writes to disk. Logs one line naming what changed and
    that ``hmp doctor`` persists it; says nothing when the document was
    already current.
    """
    changes = migrate_config_doc(doc)
    loud = [change for change in changes if change not in _QUIET_CHANGES]
    if loud:
        where = f"{source}" if source is not None else "config"
        _logger.info(
            "%s: migrated %d legacy key(s) on load, not persisted to disk "
            "(run `hmp doctor --fix-config %s` to persist): %s",
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
    if exploded == [_EMPTY_EXPORT_DROPPED]:
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


def _artifact_block(artifact: Mapping[str, Any], folder: Any) -> dict[str, Any]:
    """Return one ``[[export.artifacts]]`` entry as an ``[[export]]`` request."""
    block: dict[str, Any] = {}
    for old, new in _ARTIFACT_KEYS.items():
        if old in artifact:
            block[new] = _plain(artifact[old])
    if block.get("variables") == "*":
        block["variables"] = "all"
    if block.get("format") == "hmp":
        block["format"] = "package"
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


def _export_blocks(table: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the requests the old ``[export]`` table made, in the order they ran.

    A format toggle wrote every name of ``variables`` at ``time``, into
    ``output_dir``; ``csv_timeseries`` wrote every series; ``package`` wrote
    the archive last. The defaults are the ones the table had.
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
    blocks.extend(_artifact_block(artifact, folder) for artifact in export.get("artifacts") or ())
    if export.get("package"):
        blocks.append(
            _export_block({"variables": "all", "format": "package"}, time=None, folder=folder)
        )
    return blocks


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
    blocks = _export_blocks(table)
    if not blocks:
        del doc["export"]
        return [_EMPTY_EXPORT_DROPPED]
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
    return [f"[export] toggles and artifacts -> {len(blocks)} [[export]] block(s) ({formats})"]


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

    A comparison or testbed file patches its solver sections under ``overlay``,
    and those reach the same loader, so the root alone is not enough.
    """
    changes: list[str] = []
    for path, table in _solver_tables(doc):
        if "tgrid" not in table:
            continue
        del table["tgrid"]
        changes.append(f"{path}.tgrid dropped (removed from the schema, never read)")
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


def _solver_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return every ``(path, table)`` pair holding a MODFLOW solver section."""
    tables: list[tuple[str, Any]] = [(name, doc.get(name)) for name in _SOLVER_SECTIONS]
    for owner, member in (("comparison", "simulation"), ("testbed", "case")):
        entries = (doc.get(owner) or {}).get(member)
        if entries is None:
            continue
        if isinstance(entries, Mapping):
            entries = [entries]
        for index, entry in enumerate(entries):
            overlay = (entry or {}).get("overlay")
            if overlay is None:
                continue
            for name in _SOLVER_SECTIONS:
                tables.append((f"{owner}.{member}[{index}].overlay.{name}", overlay.get(name)))
    return [(path, table) for path, table in tables if table is not None]


def _flow_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return every ``(path, table)`` pair holding a flow section.

    A comparison or testbed file carries no top-level ``[flow]``: it patches
    one per case, under ``overlay``. Those overlays reach the same loader and
    are refused by the same rule, so a migration that only looked at the root
    left the file broken and reported nothing to fix.
    """
    tables = [("flow", doc.get("flow"))]
    for owner, member in (("comparison", "simulation"), ("testbed", "case")):
        entries = (doc.get(owner) or {}).get(member)
        if entries is None:
            continue
        if isinstance(entries, Mapping):
            entries = [entries]
        for index, entry in enumerate(entries):
            overlay = (entry or {}).get("overlay")
            if overlay is None:
                continue
            tables.append((f"{owner}.{member}[{index}].overlay.flow", overlay.get("flow")))
    return [(path, table) for path, table in tables if table is not None]


def _flatten_boundary_conditions(doc: Any) -> list[str]:
    """Rewrite ``[flow.bc.<kind>.<id>]`` as ``[flow.bc.<id>]`` with a kind field.

    A boundary is keyed by what it is; its kind is an attribute the registry
    declares and the table only has to carry when it departs from that default.
    The nested form said the same thing twice and let the two disagree.
    """
    changes: list[str] = []
    for prefix, flow in _flow_tables(doc):
        bc = flow.get("bc")
        if bc is None:
            continue
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


__all__ = ["fix_config_file", "migrate_config_doc", "migrate_config_doc_on_load"]
