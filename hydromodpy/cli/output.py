"""The one way a command writes its result for a program.

``--format json`` prints one JSON object on stdout, with two keys::

    {"schema": "hmp.catalog.ls.v1", "data": [...]}

``schema`` names the command and the version of what ``data`` holds. ``data`` is
an array of rows for a listing, an empty one when there is nothing to list, and
an object otherwise. ``--format csv`` prints the same rows as a table with a
header, or ``key,value`` lines for an object. ``--format table`` is for people
and promises nothing.

:data:`OUTPUTS` declares what each command writes, and :func:`emit` is the only
function that writes it. The fields written are the fields declared, so a page
generated from this table cannot lie about them. While a command runs under
``json`` or ``csv``, :func:`stdout_for_a_program` points stdout at stderr, down
to the file descriptor, so a library or a solver that prints cannot break the
document. The result is written once the command is over.

A failure under ``--format json`` prints the envelope ``hmp.error.v1`` on stdout
as well as its line on stderr, unless a result was already written. A mistake on
the command line itself is found before the format is read, so it has only the
line on stderr. The promise is ``docs/source/reference/cli/machine-output.md``.
"""

from __future__ import annotations

import csv as csv_module
import dataclasses
import json
import math
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import PurePath
from typing import Any


@dataclass(frozen=True, slots=True)
class Output:
    """What one command writes under ``--format json`` and ``--format csv``."""

    verb: str
    """The command, without ``hmp``: ``catalog ls``."""

    fields: tuple[str, ...]
    """The columns of a row, or the keys of the object."""

    rows: bool = False
    """Whether ``data`` is an array of rows. An object otherwise."""

    open_fields: bool = False
    """A row may hold more fields than these: the columns of a query, a metric."""

    experimental: bool = False
    """Its shape may still change in a minor version, see ``about/versions.md``."""

    version: int = 1
    """Goes up when a field changes its meaning or leaves. A new field keeps it."""

    @property
    def schema(self) -> str:
        """The id the envelope carries: ``hmp.catalog.ls.v1``."""
        return f"hmp.{self.verb.replace(' ', '.')}.v{self.version}"


def _rows(verb: str, *fields: str, open_fields: bool = False) -> Output:
    return Output(verb, fields, rows=True, open_fields=open_fields)


def _object(verb: str, *fields: str, experimental: bool = False) -> Output:
    return Output(verb, fields, experimental=experimental)


_RUN_LISTING = (
    "sim_id",
    "name",
    "project",
    "site",
    "case_id",
    "rel_dir",
    "solver",
    "status",
    "label",
    "nse",
    "created_at",
    "started_at",
    "duration_s",
    "n_cells",
    "n_layers",
    "mesh_engine",
    "config_hash",
    "version_int",
    "overrides",
    "score_station",
    "score_variable",
    "score_window_start",
    "score_window_end",
    "metric_rule_version",
)

_SITE_ROW = ("site", "label", "gauge", "uri", "x_outlet", "y_outlet", "crs", "tags")

OUTPUTS: tuple[Output, ...] = (
    # Running
    _object("run", "workflow", "config", "dry_run", "result"),
    _object(
        "calibrate",
        "session_id",
        "method",
        "status",
        "n_trials",
        "best_cost",
        "duration_s",
        "save_runs",
        "promoted",
        "best_cases",
        "best_sim_id",
        "best_rel_dir",
        "cost_name",
        "cost_label",
        "best_trial",
        "best_parameters",
        "windows",
        "parameter_uncertainty",
        "cost_block_fractions",
        "workspace",
        "session_dir",
        "phases",
        "frozen",
        "reused_from_disk",
        "restart_spreads",
        "steady_window",
        "protocol",
        "methods_paragraph",
        "methods_path",
        "extra",
        experimental=True,
    ),
    _object("calibrate phases", "protocol", "phases", "calibration", experimental=True),
    _object(
        "calibrate plan",
        "case",
        "session_dir",
        "run_dir",
        "save_runs",
        "phases",
        "solves_in_parallel",
        experimental=True,
    ),
    _object(
        "spinup",
        "applied",
        "converged",
        "n_cycles",
        "cycles",
        "restart_from",
        "warning",
        "production_sim_id",
    ),
    # Files out of a run
    _object("export", "files", "regenerated"),
    _rows("export list", "name", "kind"),
    _object("publish", "applied", "copies", "package", "next"),
    _object("publish verify", "copy", "members", "problems"),
    # Workspace
    _object("workspace init", "path", "workspace_toml"),
    _rows("workspace list", "project", "name", "site", "solver", "nse", "created_at", "sim_id"),
    _object("workspace clean", "workspace", "applied", "results", "indexes", "caches"),
    # Project
    _object("project new", "path"),
    _object("project plan", "plan_hash", "path", "n_cases", "n_sites", "n_recipes", "n_sealed"),
    _object("project status", "plan_hash", "plan_stale", "counts", "cases"),
    _rows(
        "project log",
        "at",
        "event",
        "case_id",
        "status",
        "exit_code",
        "signal",
        "rel_dir",
        "error",
        "log",
        "log_tail",
        open_fields=True,
    ),
    _rows("project list", "name", "path", "has_project_toml", "run_tomls"),
    _object(
        "project show",
        "name",
        "path",
        "has_project_toml",
        "configs",
        "n_runs",
        "runs",
        "n_sessions",
        "sessions",
        "n_trials",
        "plan",
        "has_summary",
        "n_trashed",
        "has_index",
    ),
    _object("project delete", "project", "path", "applied", "bytes_freed", "published"),
    _object(
        "project import",
        "applied",
        "project",
        "path",
        "written",
        "unchanged",
        "runs",
        "sessions",
        "mesh_entries",
    ),
    # Campaign
    _object("campaign case", "path"),
    _object(
        "campaign array",
        "directory",
        "plan_hash",
        "n_cases",
        "cases_txt",
        "prepare_sh",
        "array_sh",
        "cpus_per_task",
        "threads_per_case",
        "max_solves",
        "prepare_parallel",
    ),
    _object(
        "campaign collect",
        "summary",
        "by_case",
        "by_site",
        "catalog",
        "report",
        "readme",
        "figures_not_drawn",
    ),
    _object("campaign prune", "case", "applied", "trials"),
    _object("campaign promote", "case", "trial", "rel_dir"),
    # Sites
    _object("site add", *_SITE_ROW, "catalog"),
    _object("site import", "applied", "catalog", "skipped", "sites"),
    _rows("site ls", *_SITE_ROW),
    _object("site show", *_SITE_ROW),
    # Catalog
    _rows("catalog ls", *_RUN_LISTING, open_fields=True),
    _rows("catalog query", open_fields=True),
    _object(
        "catalog show",
        "sim_id",
        "name",
        "project",
        "site",
        "case_id",
        "rel_dir",
        "solver",
        "status",
        "label",
        "label_date",
        "nse",
        "duration_s",
        "n_cells",
        "n_timesteps",
        "version_int",
        "config_hash",
        "exports",
        "figures",
        "zarr_path",
        "zarr_exists",
        "zarr_groups",
    ),
    _rows("catalog point", open_fields=True),
    _rows(
        "catalog rank",
        "sim_id",
        "name",
        "solver",
        "station",
        "variable",
        "metric_name",
        "value",
        "window_start",
        "window_end",
        "metric_rule_version",
    ),
    _object("catalog gc", "applied", "keep_versions", "max_age_days", "projects"),
    _object(
        "catalog reindex", "index", "full", "indexed", "sessions", "removed", "skipped", "rows"
    ),
    _object("catalog delete", "rel_dir", "applied", "removed_for_good", "trashed_to"),
    _object("catalog restore", "applied", "rel_dir"),
    _rows("catalog trash", "name", "rel_dir", "trashed_at"),
    _object("catalog trash empty", "applied", "removed", "kept_pinned"),
    _object("catalog tag", "rel_dir", "added", "removed", "tags"),
    _object("catalog note", "rel_dir", "text"),
    _object("catalog rename", "applied", "rel_dir", "renamed"),
    _object("catalog diff", "a", "b", "params", "metrics"),
    _rows(
        "catalog watch",
        "rel_dir",
        "case_id",
        "sim_id",
        "attempt",
        "attempt_id",
        "host",
        "pid",
        "step",
        "started_at",
        "heartbeat_at",
        "age_s",
        "stale",
        "dead",
    ),
    _object("catalog import", "applied", "rel_dir", "name", "written", "unchanged", "next"),
    _object("catalog rerun", "applied", "source", "rel_dir", "sim_id"),
    # Reports and figures
    _object("report render", "path"),
    _object("report compare", "folder"),
    _object(
        "report catchment",
        "overview_config",
        "simulation_config",
        "context_summary",
        "html_report",
        "postflight_report",
    ),
    _rows("viz list", "name", "kind", "required_fields", "required_tables"),
    _rows("viz list run", "name", "kind", "available", "reason"),
    _object("viz show", "path"),
    # Configuration
    _object(
        "config check",
        "ok",
        "diagnostics",
        "workspace",
    ),
    _rows(
        "config targets",
        "name",
        "path",
        "instance",
        "current",
        "units",
        "physical_bounds",
        "registry_id",
    ),
    # Data
    _rows("data ls", "variable", "source", "station_id", "file_path", open_fields=True),
    _object("data get", "files", "failures", "report"),
    _object("data add", "variable", "provider", "station_id", "dest"),
    _object("data remove", "applied", "removed"),
    _object("data prune", "applied", "older_than_days", "removed"),
    _object("data archive", "path"),
    _object("data restore", "source", "path"),
    # Lockfile
    _object("lock update", "path"),
    _object(
        "lock verify",
        "ok",
        "schema_diverged",
        "locked_schema",
        "current_schema",
        "mismatches",
    ),
    # Examples
    _rows(
        "example list",
        "id",
        "directory",
        "title",
        "summary",
        "runtime",
        "entry_config",
        "file_count",
        "total_size",
        "missing_size",
    ),
    _object(
        "example show",
        "id",
        "directory",
        "title",
        "summary",
        "runtime",
        "entry_config",
        "file_count",
        "total_size",
        "missing_size",
        "files",
        "data",
    ),
    _object(
        "example add",
        "workspace",
        "project_dir",
        "entry_config",
        "source",
        "downloaded",
        "downloaded_bytes",
        "written",
        "unchanged",
        "kept",
        "stations_written",
    ),
    # Privacy
    _object(
        "privacy purge",
        "applied",
        "sim_id",
        "rel_dir",
        "removed_paths",
        "certificate",
        "archive",
        "sha256_snapshot",
    ),
    _object(
        "privacy verify",
        "certificate",
        "permissions_ok",
        "permissions",
        "sim_id",
        "timestamp_utc",
        "operator",
        "reason",
        "sha256_snapshot",
    ),
    # Environment
    _object("doctor", "python", "platform", "hydromodpy", "checks"),
    _object("install-binaries", "already_cached", "release", "installed", "target"),
)
"""Every result ``hmp`` writes for a program, by command.

The commands that have no entry write a document that is the result itself, so an
envelope would break it: ``config template``, ``config resolve``, ``config schema``,
``config wizard`` and ``completion``.
"""

ERROR = _object("error", "code", "title", "detail", "exit_code")
"""What a failure writes under ``--format json``."""

_BY_VERB: dict[str, Output] = {output.verb: output for output in OUTPUTS}

_held: list[str] | None = None
"""What :func:`emit` wrote while a command runs under ``json`` or ``csv``."""

_json_mode = False


def output_of(verb: str) -> Output:
    """Return the declaration of a command."""
    return _BY_VERB[verb]


def plain(value: Any) -> Any:
    """Return *value* as what strict JSON can hold: no NaN, no infinity, no object."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        items = sorted(value, key=str) if isinstance(value, set | frozenset) else value
        return [plain(item) for item in items]
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, Enum):
        return plain(value.value)
    if isinstance(value, datetime | date):
        return None if value != value else value.isoformat()  # NaT is not equal to itself.
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return plain(dataclasses.asdict(value))
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(mode="json"))
    if hasattr(value, "tolist"):  # A scalar or an array of numpy.
        return plain(value.tolist())
    if type(value).__name__ == "NAType":
        return None
    return str(value)


def records(table: Any) -> list[dict[str, Any]]:
    """Return the rows of a data frame, or of anything that is already rows."""
    return table.to_dict("records") if hasattr(table, "to_dict") else list(table)


def _shaped(output: Output, data: Any) -> Any:
    """Return *data* holding what *output* declares, and nothing else unless it is open."""
    if output.rows:
        rows = records(data)
        if output.open_fields:
            return [{**dict.fromkeys(output.fields), **row} for row in rows]
        return [{name: row.get(name) for name in output.fields} for row in rows]
    return {name: data.get(name) for name in output.fields}


def _cell(value: Any) -> str:
    """Return one CSV cell: nothing for a missing value, one line for a list or a mapping."""
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return ";".join(f"{key}={_cell(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ";".join(_cell(item) for item in value)
    return str(value)


def _write_csv(columns: list[str], rows: list[Mapping[str, Any]]) -> None:
    class _Buffer:
        def write(self, text: str) -> None:
            _write(text)

    writer = csv_module.DictWriter(_Buffer(), fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _cell(row.get(column)) for column in columns})


def _columns(output: Output, rows: list[Mapping[str, Any]]) -> list[str]:
    columns = list(output.fields)
    if output.open_fields:
        for row in rows:
            columns.extend(name for name in row if name not in columns)
    return columns


def _write(text: str) -> None:
    if _held is None:
        sys.stdout.write(text)
    else:
        _held.append(text)


def emit(
    args: Any,
    verb: str,
    data: Any,
    *,
    table: Callable[[], None] | None = None,
    csv: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None = None,
) -> None:
    """Write the result of a command in the format it was asked for.

    Parameters
    ----------
    args
        The parsed command line. Its ``format`` is ``table`` when it has none.
    verb
        The command, as :data:`OUTPUTS` declares it.
    data
        The rows or the object, with Python values. A data frame reads as rows.
    table
        What to print for people.
    csv
        The columns and the rows ``--format csv`` writes when they are not ``data``:
        an object that holds a table, rows with a cell of their own.
    """
    output = output_of(verb)
    chosen = getattr(args, "format", "table")
    if chosen == "table":
        if table is not None:
            table()
        return
    shaped = plain(_shaped(output, data))
    if chosen == "json":
        document = {"schema": output.schema, "data": shaped}
        _write(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    elif csv is not None:
        _write_csv(list(csv[0]), plain(list(csv[1])))
    elif output.rows:
        _write_csv(_columns(output, shaped), shaped)
    else:
        _write_csv(["key", "value"], [{"key": k, "value": v} for k, v in shaped.items()])


def failed(code: str, title: str, detail: str, exit_code: int) -> None:
    """Hold the error envelope, when a command fails under ``--format json`` with no result yet."""
    if not _json_mode or _held:
        return
    data = {"code": code, "title": title, "detail": detail, "exit_code": exit_code}
    document = {"schema": ERROR.schema, "data": data}
    _write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")


@contextmanager
def stdout_for_a_program(args: Any) -> Iterator[None]:
    """Keep stdout for the result while a command runs under ``json`` or ``csv``.

    Python and every child process write to stderr instead, and :func:`emit`
    holds the result until the command is over, whether it ended well or not.
    """
    global _held, _json_mode
    chosen = getattr(args, "format", "table")
    if chosen == "table":
        yield
        return
    _held, _json_mode = [], chosen == "json"
    stream = sys.stdout
    stream.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stderr.flush()
        os.dup2(saved, 1)
        os.close(saved)
        sys.stdout = stream
        held, _held, _json_mode = _held, None, False
        for text in held:
            stream.write(text)
        stream.flush()


__all__ = (
    "ERROR",
    "OUTPUTS",
    "Output",
    "emit",
    "failed",
    "output_of",
    "plain",
    "records",
    "stdout_for_a_program",
)
