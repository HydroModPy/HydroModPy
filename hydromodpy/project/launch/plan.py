"""The plan of a ``[sites]`` project: sites x recipes resolved into cases, then written once.

:func:`expand_plan` reads the tables and the recipes, binds columns to the keys they fill and
resolves each (site, recipe) pair into a :class:`DraftCase`. Nothing is written until
:func:`write_plan_draft` puts the draft under ``plan/<hash>/``, and a plan whose case still
runs is not rewritten. The precedence of a case, lowest first: the schema defaults, the base
chain of the recipe, the site row, ``site_overrides/<site>.toml``, the keys the recipe file
writes, its ``set`` table, the row of the recipe table, ``--set``, then ``HMP_SET_*``. A table
is CSV, Parquet or GeoPackage. A key that belongs to one catchment may not hold a literal value
that every site would share. The hash of a plan starts from its schema, then its cases and the
files it was made from. Which cases are sealed is read from ``runs/``, never written.

The plan is written once through ``results/plan_store.py`` as ``plan.json``,
``cases.csv`` and one TOML per case. A case is done when a sealed run, or a completed
session for a calibration, holds its solution key. A calibration compares the hash of
its sessions, never the one of the run it promoted, whose parameters the best trial
replaced. ``--dry-run`` and the launcher both ask ``case_is_done``, so they say the same
thing, and ``plan_budget`` gives the numbers of ``hmp run --dry-run``. An error names
its cell, such as ``sites.csv:37 column x_outlet``, and is grouped over the cases it
touches. A check of the section alone, without reading a file, goes to ``SitesConfig``
in ``config/sites.py``.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import math
import os
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from hydromodpy.config.config_migration import migrate_layers, migrate_merged_doc
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.config.sites import RECIPE_NAME_PATTERN, RecipeSpec, SitesConfig
from hydromodpy.core.config_kit.introspect import (
    LIST_ITEM_MARK,
    TABLE_KEY_MARK,
    iter_basemodels,
    site_scoped_paths,
)
from hydromodpy.core.config_kit.written import written_experimental_keys, written_payload
from hydromodpy.core.diagnostic import Diagnostic, Severity
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError
from hydromodpy.core.site.config import SITE_NAME_PATTERN
from hydromodpy.core.site.row import SITE_ROW_COLUMNS, SiteRow
from hydromodpy.core.state.layout import (
    PLAN_DIRNAME,
    PROJECT_MARKER_FILENAME,
    runs_dir_for,
    sessions_dir_for,
)
from hydromodpy.core.state.names import check_name, fold_name
from hydromodpy.core.toml_io.loader import (
    ChainFile,
    load_toml_with_base_config,
    merge_toml_chain,
    read_toml_chain,
)
from hydromodpy.core.toml_io.merge import merge_toml_payloads
from hydromodpy.core.toml_io.overrides import ENV_SOURCE, SET_SOURCE, env_overrides, env_set_names
from hydromodpy.core.toml_io.paths import UnknownPathError, assign, lookup, parse, resolve_field
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.core.version import __version__
from hydromodpy.core.workspace.workspace_toml import near_site_m as workspace_near_site_m
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.exporters.destination import DELIVER_TO_KEY
from hydromodpy.results.outcome import effective_status
from hydromodpy.results.plan_store import (
    CASE_COLUMNS,
    CASE_TOML_SUFFIX,
    PLAN_SCHEMA,
    Plan,
    PlanCase,
    current_plan_hash,
    plan_path,
    read_plan,
    write_plan,
)
from hydromodpy.results.record.manifest import is_sealed, read_seal
from hydromodpy.results.retention import level_at
from hydromodpy.results.session.descriptor import read_session, session_descriptor_path
from hydromodpy.results.storage.contract import PLAN_FILENAME
from hydromodpy.results.storage.json_io import readable
from hydromodpy.results.storage.kept import at_least

CaseKind = Literal["simulation", "calibration", "overview"]

CASE_SEPARATOR = "-"
PLAN_HASH_LENGTH = 16
RECIPE_COLUMN = "recipe"
RECIPE_FILE_COLUMN = "file"
GEOMETRY_X_COLUMN, GEOMETRY_Y_COLUMN = "geometry_x", "geometry_y"
CATALOG_BIND = {
    "site.name": "site",
    "site.label": "label",
    "site.gauge": "gauge",
    "site.uri": "uri",
    "geographic.catchment.x_outlet": "x_outlet",
    "geographic.catchment.y_outlet": "y_outlet",
}
"""How the fixed columns of the workspace site catalog reach a case."""
EXTRA_SITE_SCOPED = ("display.overrides.cross_section",)
SCRATCH_PER_KEPT_SOLVE_GIB = (0.6, 4.8)
"""Scratch one kept solve takes, low and high, as measured on the example 04."""
CALIBRATION_PARALLEL_CEILING = 8
"""Budget of a campaign that holds a calibration: 8 solves held 6.5 GiB, no loss, equal costs."""

_SITE_NAME = re.compile(SITE_NAME_PATTERN)
_RECIPE_NAME = re.compile(RECIPE_NAME_PATTERN)
_SITE_PATH, _SIM_PATH = parse("site.name"), parse("simulation.name")
_OUTLET = (parse("geographic.catchment.x_outlet"), parse("geographic.catchment.y_outlet"))


class SitesProjectError(ConfigError):
    """The file is not a ``[sites]`` project, or a table or a bind line is unusable."""


class BudgetError(ConfigError):
    """The plan asks for more than the machine, or the measurements, allow."""


class RunningCaseError(ConfigError):
    """A case of the current plan is running; a new plan would change its ground."""


class CellError(ConfigError):
    """A cell cannot be read by the type of the key it is bound to."""

    def __init__(self, origin: str, target: str, detail: str) -> None:
        super().__init__(f"{origin} -> {target}: {detail}")
        self.origin, self.target, self.detail = origin, target, detail


# -- issues: what a plan says about its cases, grouped ------------------------


@dataclass(frozen=True, slots=True)
class PlanIssue:
    """One thing wrong about a case or the plan, with the cell and the key it comes from."""

    message: str
    origin: str | None = None
    target: str | None = None
    case_id: str | None = None

    def text(self) -> str:
        """Return the issue without its case: origin, target and message."""
        head = " -> ".join(part for part in (self.origin, self.target) if part)
        return f"{head}: {self.message}" if head else self.message


def group_diagnostics(
    issues: Iterable[PlanIssue], severity: Severity = "error"
) -> list[Diagnostic]:
    """Return one ``sites_case`` diagnostic per distinct issue, counting the cases it touches."""
    groups: dict[tuple, list[str | None]] = {}
    for issue in issues:
        groups.setdefault((issue.origin, issue.target, issue.message), []).append(issue.case_id)
    found = []
    for (origin, target, message), cases in groups.items():
        named = [case for case in cases if case is not None]
        text = PlanIssue(message, origin, target).text()
        lead = f"{len(named)} cases: " if len(named) > 1 else f"{named[0]}: " if named else ""
        found.append(Diagnostic(target or "", "sites_case", severity, lead + text))
    return found


def group_issues(issues: Iterable[PlanIssue]) -> list[str]:
    """Return one line per distinct issue, counting the cases it touches."""
    return [diagnostic.detail for diagnostic in group_diagnostics(issues)]


class PlanError(ConfigError):
    """The plan cannot be written: its issues, one line each."""

    def __init__(self, issues: Sequence[PlanIssue]) -> None:
        self.lines = tuple(group_issues(issues))
        super().__init__("\n".join(self.lines))


# -- tables: CSV, Parquet or GeoPackage, every cell keeps its origin ----------


@dataclass(frozen=True, slots=True)
class TableRow:
    """One row of a table: its data index, its physical line (None if binary) and its cells."""

    index: int
    line: int | None
    cells: Mapping[str, Any]

    def origin(self, table: Table, column: str) -> str:
        """Return where one cell was written: ``sites.csv:3 column x``."""
        at = f":{self.line}" if self.line is not None else f" row {self.index}"
        return f"{table.label}{at} column {column}"


@dataclass(frozen=True, slots=True)
class Table:
    """A table read whole: its columns and its rows."""

    path: Path
    label: str
    columns: tuple[str, ...]
    rows: tuple[TableRow, ...]


def is_empty_cell(value: Any) -> bool:
    """Return whether a cell holds nothing: ``None``, ``NaN`` or blank text."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return True
    return isinstance(value, str) and not value.strip()


def read_table(path: Path, *, label: str) -> Table:
    """Read a CSV, Parquet or GeoPackage file; a GeoPackage of points gains geometry_x and _y."""
    if not path.is_file():
        raise SitesProjectError(f"{label}: no such file ({path})")
    suffix = path.suffix.lower()
    reader = {".csv": _read_csv, ".parquet": _read_parquet, ".gpkg": _read_geopackage}.get(suffix)
    if reader is None:
        found = suffix or "a file without suffix"
        raise SitesProjectError(f"{label}: a table is one of .csv, .parquet, .gpkg, not {found}")
    return reader(path, label)


def _columns(label: str, names: Sequence[Any]) -> tuple[str, ...]:
    columns = [str(name).strip() for name in names]
    if "" in columns:
        raise SitesProjectError(f"{label}: a column has no name")
    twice = sorted({name for name in columns if columns.count(name) > 1})
    if twice:
        raise SitesProjectError(f"{label}: column(s) named twice: {', '.join(twice)}")
    return tuple(columns)


def _binary_table(path: Path, label: str, names: Sequence[Any], records: Sequence[dict]) -> Table:
    rows = tuple(TableRow(i, None, record) for i, record in enumerate(records, start=1))
    return Table(path, label, _columns(label, names), rows)


def _read_csv(path: Path, label: str) -> Table:
    rows: list[TableRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise SitesProjectError(f"{label}: the file is empty")
        columns = _columns(label, header)
        for index, record in enumerate(reader, start=1):
            if not record or all(not cell.strip() for cell in record):
                continue
            if len(record) != len(columns):
                found = f"{len(record)} cells for {len(columns)} columns"
                raise SitesProjectError(f"{label}:{reader.line_num}: {found}")
            cells = {name: cell.strip() for name, cell in zip(columns, record, strict=True)}
            rows.append(TableRow(index, reader.line_num, cells))
    return Table(path, label, columns, tuple(rows))


def _read_parquet(path: Path, label: str) -> Table:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    return _binary_table(path, label, table.column_names, table.to_pylist())


def _read_geopackage(path: Path, label: str) -> Table:
    import geopandas as gpd

    frame = gpd.read_file(path)
    geometry = frame.geometry.name if frame.geometry is not None else None
    columns = [name for name in frame.columns if name != geometry]
    records = []
    for _, record in frame.iterrows():
        cells = {name: record[name] for name in columns}
        point = record[geometry] if geometry is not None else None
        if point is not None and getattr(point, "geom_type", None) == "Point":
            cells[GEOMETRY_X_COLUMN], cells[GEOMETRY_Y_COLUMN] = float(point.x), float(point.y)
        records.append(cells)
    if any(GEOMETRY_X_COLUMN in record for record in records):
        columns += [GEOMETRY_X_COLUMN, GEOMETRY_Y_COLUMN]
    return _binary_table(path, label, columns, records)


def table_from_site_rows(rows: Sequence[SiteRow], *, path: Path, label: str) -> Table:
    """Present the site catalog of the workspace as a table, the header on line 1."""
    body = tuple(TableRow(i, i + 1, row.to_mapping()) for i, row in enumerate(rows, start=1))
    return Table(path, label, SITE_ROW_COLUMNS, body)


# -- bind lines: a column fills one key, read by the type of the key ----------


@dataclass(frozen=True, slots=True)
class Bind:
    """One bind line: the key it fills, the columns it reads, the field that types the key."""

    path: Any
    columns: tuple[str, ...]
    field: FieldInfo


def resolve_binds(bind: Mapping[str, Any], where: str) -> list[Bind]:
    """Check every bind line against the schema; a key it has not, or a table, is refused."""
    out = []
    for key, cols in bind.items():
        try:
            path = parse(key)
            field = resolve_field(HydroModPyConfig, path)
        except UnknownPathError as exc:
            raise SitesProjectError(f"{where}: [sites.bind] {exc}") from exc
        except ValueError as exc:
            raise SitesProjectError(f"{where}: [sites.bind] {key!r}: {exc}") from exc
        if iter_basemodels(field.annotation):
            raise SitesProjectError(
                f"{where}: [sites.bind] {path} is a table, and a cell holds a value; bind "
                "the keys of the table one by one."
            )
        out.append(Bind(path, (cols,) if isinstance(cols, str) else tuple(map(str, cols)), field))
    return out


def _check_columns(binds: Sequence[Bind], tables: Sequence[Table], where: str) -> None:
    owner: dict[str, list[str]] = {}
    for table in tables:
        for column in table.columns:
            owner.setdefault(column, []).append(table.label)
    shared = sorted(column for column, labels in owner.items() if len(labels) > 1)
    if shared:
        both = " and ".join(sorted(table.label for table in tables))
        raise SitesProjectError(
            f"{where}: column(s) {', '.join(shared)} present in both {both}; a column "
            "belongs to one table."
        )
    for bind in binds:
        head = f"{where}: [sites.bind] {bind.path}"
        missing = [c for c in bind.columns if c not in owner]
        if missing:
            found = ", ".join(table.label for table in tables) or "no table"
            raise SitesProjectError(
                f"{head} names column(s) {', '.join(missing)}, found in {found}."
            )
        owners = {owner[c][0] for c in bind.columns}
        if len(owners) > 1:
            raise SitesProjectError(
                f"{head} binds columns of two tables ({', '.join(sorted(owners))}); "
                "bind columns of one table."
            )


def _on_table(binds: Sequence[Bind], table: Table) -> list[Bind]:
    return [bind for bind in binds if all(c in table.columns for c in bind.columns)]


def _toml_value(cell: Any) -> Any:
    if not isinstance(cell, str):
        return cell
    try:
        return tomllib.loads(f"value = {cell.strip()}\n")["value"]
    except tomllib.TOMLDecodeError:
        return cell


def _read_cell(bind: Bind, cells: Sequence[Any], origin: str) -> Any:
    field = bind.field
    kind = Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation
    adapter, many = TypeAdapter(kind), len(cells) > 1
    typed, plain = [_toml_value(c) for c in cells], list(cells)
    tries = [typed if many else typed[0]]
    if (plain if many else plain[0]) != tries[0]:
        tries.append(plain if many else plain[0])
    detail = ""
    for candidate in tries:
        try:
            adapter.validate_python(candidate)
            return candidate
        except ValidationError as exc:
            detail = "; ".join(e["msg"] for e in exc.errors())
    raise CellError(origin, str(bind.path), detail or "no value")


def _render_row(
    binds: Sequence[Bind], row: TableRow, table: Table
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    payload: dict[str, Any] = {}
    bound: list[tuple[str, str]] = []
    for bind in binds:
        cells = [row.cells.get(c) for c in bind.columns]
        blank = [c for c, value in zip(bind.columns, cells, strict=True) if is_empty_cell(value)]
        if len(blank) == len(cells):
            continue
        origin = row.origin(table, bind.columns[0])
        if blank:
            detail = f"column(s) {', '.join(blank)} empty; fill every cell or none"
            raise CellError(origin, str(bind.path), detail)
        assign(payload, bind.path, _read_cell(bind, cells, origin))
        bound.append((str(bind.path), origin))
    return payload, bound


# -- keys that belong to one catchment ----------------------------------------


def _leaves(payload: Mapping[str, Any], prefix: tuple = ()) -> set[tuple]:
    out: set[tuple] = set()
    for key, value in payload.items():
        inner = isinstance(value, Mapping) and value
        out |= _leaves(value, (*prefix, str(key))) if inner else {(*prefix, str(key))}
    return out


def _match(node: Any, parts: Sequence[str], prefix: tuple = ()) -> list[tuple]:
    if not parts:
        return [prefix]
    head, rest = parts[0], parts[1:]
    if head == TABLE_KEY_MARK:
        items = node.items() if isinstance(node, Mapping) else []
        return [p for key, value in items for p in _match(value, rest, (*prefix, str(key)))]
    if head.endswith(LIST_ITEM_MARK):
        name = head[: -len(LIST_ITEM_MARK)]
        seq = node.get(name) if isinstance(node, Mapping) else None
        items = enumerate(seq) if isinstance(seq, list) else []
        return [p for i, value in items for p in _match(value, rest, (*prefix, name, i))]
    if isinstance(node, Mapping) and head in node:
        return _match(node[head], rest, (*prefix, head))
    return []


def _literal_site_keys(document: Mapping[str, Any], varying: set[tuple]) -> list[str]:
    found = []
    for pattern in sorted({*site_scoped_paths(HydroModPyConfig), *EXTRA_SITE_SCOPED}):
        for path in _match(document, pattern.split(".")):
            if any(all(a == b for a, b in zip(path, v, strict=False)) for v in varying):
                continue
            text = ""
            for part in path:
                text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else part)
            found.append(text)
    return sorted(found)


# -- the draft ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedRecipe:
    """One recipe: its file, the chain below its own keys, what it writes, its bind lines."""

    name: str
    file: Path
    base: Mapping[str, Any]
    own: Mapping[str, Any]
    set: Mapping[str, Any]
    row: TableRow | None
    binds: tuple[Bind, ...]
    own_binds: tuple[Bind, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSite:
    """One site: its row, the row rendered through the bind lines and its overlay."""

    name: str
    row: TableRow
    payload: Mapping[str, Any]
    bound: tuple[tuple[str, str], ...]
    override: Mapping[str, Any]

    def outlet(self) -> tuple[float, float] | None:
        """Return the outlet the row binds, when both coordinates are bound."""
        try:
            x, y = lookup(self.payload, _OUTLET[0]), lookup(self.payload, _OUTLET[1])
        except KeyError:
            return None
        both = isinstance(x, (int, float)) and isinstance(y, (int, float))
        return (float(x), float(y)) if both else None


@dataclass(frozen=True, slots=True)
class DraftCase:
    """One case: a site crossed with a recipe, resolved and checked."""

    case_id: str
    site: str
    recipe: str
    document: Mapping[str, Any]
    config_hash: str | None
    kind: CaseKind
    solves: int
    kept_solves: int
    done: bool
    experimental_keys: tuple[str, ...] = ()

    def toml(self) -> str:
        """Return the document as TOML text."""
        return dumps(dict(self.document))


@dataclass(frozen=True, slots=True)
class PlanDraft:
    """A plan before it is written: its cases, and what is wrong with them."""

    project_root: Path
    project_file: Path | None
    config_path: Path | None
    sites_config: SitesConfig | None
    sites: tuple[ResolvedSite, ...]
    recipes: tuple[ResolvedRecipe, ...]
    cases: tuple[DraftCase, ...]
    errors: tuple[PlanIssue, ...] = ()
    warnings: tuple[PlanIssue, ...] = ()
    inputs: tuple[Path, ...] = ()
    steps: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether every case validated."""
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        """Return the plan as JSON: its ``lines``, then its grouped ``warnings`` and ``errors``.

        The ``lines`` are those ``hmp run --dry-run`` prints for a ``[sites]``
        project, so a draft without ``[sites]`` has none to give.
        """
        return {
            "lines": dry_run_lines(self, plan_budget(self)),
            "warnings": group_issues(self.warnings),
            "errors": group_issues(self.errors),
        }


def _label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def declares_sites(own: Mapping[str, Any]) -> bool:
    """Whether a document writes ``[sites]`` with more than its ``bind`` table."""
    section = own.get("sites")
    return isinstance(section, Mapping) and any(key != "bind" for key in section)


def find_sites_file(chain: Sequence[ChainFile]) -> ChainFile | None:
    """Return the file of a chain that declares ``[sites]`` beyond ``[sites.bind]``."""
    found = [item for item in chain if declares_sites(item.own)]
    if len(found) > 1:
        names = ", ".join(str(item.path) for item in found)
        raise SitesProjectError(
            f"[sites] is declared in two files of one chain: {names}; one file declares "
            "[sites], a file that inherits it (a recipe) writes [sites.bind] at most"
        )
    return found[0] if found else None


def expand_plan(
    project_root: str | Path,
    config_path: str | Path,
    *,
    set_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    near_site_m: float | None = None,
) -> PlanDraft:
    """Resolve every case of the ``[sites]`` project *config_path* belongs to.

    *config_path* declares ``[sites]`` (every recipe runs) or is one recipe file. *set_overrides*
    is the payload of ``--set``, *env* the environment whose ``HMP_SET_*`` go into every case,
    *near_site_m* the distance under which two outlets read as one catchment. A problem of the
    project raises :class:`SitesProjectError`; a problem of one case goes to the draft.
    """
    root, path = Path(project_root).resolve(), Path(config_path).resolve()
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        raise SitesProjectError(
            f"a [sites] project is anchored by {PROJECT_MARKER_FILENAME} at its root; none "
            f"in {root}"
        )
    chain = read_toml_chain(path, root=ROOT_CONFIG)
    head = find_sites_file(chain)
    if head is None:
        raise SitesProjectError(f"{path}: no [sites] section in the file or its base_config chain")
    doc = merge_toml_chain(chain[: chain.index(head) + 1], root=ROOT_CONFIG)
    if "site" in doc:
        raise SitesProjectError(
            f"{head.path}: [site] is declared beside [sites]; remove [site], each "
            "case takes its site from the table."
        )
    try:
        config = SitesConfig.model_validate(doc["sites"])
    except ValidationError as exc:
        raise SitesProjectError(f"{head.path}: [sites] {exc}") from exc

    binds = resolve_binds(config.bind, _label(head.path, root))
    inputs = [item.path for item in chain]
    workspace = _workspace_root(doc, root)
    near = workspace_near_site_m(workspace) if near_site_m is None else near_site_m
    site_table = _read_site_table(config, root, workspace, inputs)
    recipe_table = None
    if config.recipes_table is not None:
        file = (root / config.recipes_table).resolve()
        inputs.append(file)
        recipe_table = read_table(file, label=_label(file, root))
        if RECIPE_COLUMN not in recipe_table.columns:
            raise SitesProjectError(f"{recipe_table.label}: a recipe table has a 'recipe' column")
    tables = (site_table, recipe_table)
    recipes = _recipes(config, root, head, binds, recipe_table, tables, inputs)
    if path != head.path:
        recipes = [r for r in recipes if r.file == path]
        if not recipes:
            raise SitesProjectError(
                f"{path.name} is not a recipe of {head.path.name}; run the project file, "
                "or list this file under [sites.recipes]."
            )

    errors: list[PlanIssue] = []
    site_binds = _on_table(_with_catalog(config, binds), site_table)
    sites = _sites(config, site_table, site_binds, root, errors, inputs)
    cli = copy.deepcopy(dict(set_overrides or {}))
    envp = env_overrides(os.environ if env is None else env)
    migrate_layers([(SET_SOURCE, cli), (ENV_SOURCE, envp)])
    cases: list[DraftCase] = []
    taken: dict[str, str] = {}
    for site in sites:
        for recipe in recipes:
            case_id = _case_id(site, recipe, taken, errors)
            if case_id is None:
                continue
            case = _case(site, recipe, case_id, root, (cli, envp), tables, errors)
            if case is not None:
                cases.append(case)
    warnings, files = tuple(_near_outlets(sites, near)), tuple(dict.fromkeys(inputs))
    drafted = (tuple(sites), tuple(recipes), tuple(cases), tuple(errors))
    return PlanDraft(root, head.path, path, config, *drafted, warnings, files)


def single_case_draft(
    config: Any,
    *,
    name: str,
    config_path: Path | None,
    steps: Sequence[str],
    kind: CaseKind = "simulation",
    done: bool = False,
) -> PlanDraft:
    """Return the plan of one configuration, already validated: one case, no table."""
    from hydromodpy.workflow.solution_key import planned_solution_key

    site = getattr(getattr(config, "site", None), "name", None)
    key = planned_solution_key(config, search=kind == "calibration")
    payload, keys = written_payload(config), written_experimental_keys(config)
    case = DraftCase(name, str(site or ""), "", payload, key, kind, 1, 1, done, keys)
    root = Path(config.workspace.project_root)
    return PlanDraft(root, config_path, config_path, None, (), (), (case,), steps=tuple(steps))


def _workspace_root(doc: Mapping[str, Any], root: Path) -> Path:
    from hydromodpy.config.section_loader import load_standard_section
    from hydromodpy.core.workspace.config import WorkspaceConfig

    section = {**dict(doc.get("workspace") or {}), "project_root": str(root)}
    return Path(load_standard_section(section, WorkspaceConfig, root).root)


def _read_site_table(config: SitesConfig, root: Path, workspace: Path, inputs: list[Path]) -> Table:
    if config.table is not None:
        file = (root / config.table).resolve()
        inputs.append(file)
        table = read_table(file, label=_label(file, root))
    else:
        from hydromodpy.data.sites.catalog import catalog_path, read_catalog

        catalog = catalog_path(workspace)
        if not catalog.is_file():
            raise SitesProjectError(
                f"[sites] names no table and the workspace has no site catalog at {catalog}; "
                "declare sites with hmp site add or hmp site import, or write [sites] table."
            )
        inputs.append(catalog)
        table = table_from_site_rows(read_catalog(workspace), path=catalog, label=str(catalog))
    for column in table.columns:
        if column in CASE_COLUMNS and column != "site":
            raise SitesProjectError(
                f"{table.label}: column {column} is a column the plan writes for each case "
                f"({', '.join(CASE_COLUMNS)}). Rename it."
            )
    return table


def _with_catalog(config: SitesConfig, binds: list[Bind]) -> list[Bind]:
    if config.table is not None:
        return binds
    have = {str(b.path) for b in binds}
    return binds + [
        Bind(parse(key), (column,), resolve_field(HydroModPyConfig, key))
        for key, column in CATALOG_BIND.items()
        if key not in have
    ]


def _truthy(cell: Any) -> bool:
    if isinstance(cell, bool):
        return cell
    text = "" if is_empty_cell(cell) else str(cell).strip().lower()
    if text in {"", "false", "0", "no", "n"}:
        return False
    if text in {"true", "1", "yes", "y"}:
        return True
    raise SitesProjectError(f"enabled column: {cell!r} is not a boolean")


def _sites(
    config: SitesConfig,
    table: Table,
    binds: Sequence[Bind],
    root: Path,
    errors: list[PlanIssue],
    inputs: list[Path],
) -> list[ResolvedSite]:
    name_bind = next((b for b in binds if b.path == _SITE_PATH), None)
    if name_bind is None:
        raise SitesProjectError(
            f'{table.label}: no bind line names the site; write [sites.bind] "site.name" = '
            '"<column>".'
        )
    if config.enabled is not None and config.enabled not in table.columns:
        raise SitesProjectError(f"{table.label}: no column {config.enabled!r} for [sites] enabled")
    seen: dict[str, int] = {}
    out: list[ResolvedSite] = []
    for row in table.rows:
        if config.enabled is not None and not _truthy(row.cells.get(config.enabled)):
            continue
        origin, target = row.origin(table, name_bind.columns[0]), str(_SITE_PATH)
        try:
            payload, bound = _render_row(binds, row, table)
            name = str(lookup(payload, _SITE_PATH))
        except KeyError:
            errors.append(PlanIssue("the row names no site", origin, target))
            continue
        except CellError as exc:
            errors.append(PlanIssue(exc.detail, exc.origin, exc.target))
            continue
        if not _SITE_NAME.fullmatch(name):
            message = f"{name!r} is not a site name; write letters, digits and underscores"
            errors.append(PlanIssue(message, origin, target))
            continue
        if (config.include and name not in config.include) or name in config.exclude:
            continue
        if name in seen:
            message = f"site {name!r} is declared twice (rows {seen[name]} and {row.index})"
            errors.append(PlanIssue(message, origin, target))
            continue
        seen[name] = row.index
        override: Mapping[str, Any] = {}
        candidate = root / config.overrides / f"{name}.toml" if config.overrides else None
        if candidate is not None and candidate.resolve().is_file():
            inputs.append(candidate.resolve())
            try:
                override = load_toml_with_base_config(candidate.resolve(), root=ROOT_CONFIG)
            except (ValueError, TypeError) as exc:
                errors.append(PlanIssue(str(exc), _label(candidate.resolve(), root)))
                continue
        out.append(ResolvedSite(name, row, payload, tuple(bound), override))
    return out


def _near_outlets(sites: Sequence[ResolvedSite], near: float) -> list[PlanIssue]:
    placed = [(site, outlet) for site in sites if (outlet := site.outlet()) is not None]
    warnings = []
    for i, (first, (x1, y1)) in enumerate(placed):
        for second, (x2, y2) in placed[i + 1 :]:
            distance = math.hypot(x2 - x1, y2 - y1)
            if distance < near:
                text = f"sites {first.name} and {second.name} have outlets {distance:.0f} m apart"
                warnings.append(
                    PlanIssue(
                        f"{text}, under near_site_m = {near:g} m; one catchment declared twice?"
                    )
                )
    return warnings


def _recipes(
    config: SitesConfig,
    root: Path,
    head: ChainFile,
    project_binds: Sequence[Bind],
    recipe_table: Table | None,
    tables: Sequence[Table | None],
    inputs: list[Path],
) -> list[ResolvedRecipe]:
    declared: dict[str, tuple[Path, Mapping[str, Any], TableRow | None]] = {}
    for name, decl in config.recipes.items():
        spec = decl if isinstance(decl, RecipeSpec) else None
        file = (root / (spec.file if spec else decl)).resolve()
        declared[name] = (file, spec.set if spec else {}, None)
    for row in recipe_table.rows if recipe_table is not None else ():
        where = row.origin(recipe_table, RECIPE_COLUMN)
        cell = row.cells.get(RECIPE_COLUMN)
        if is_empty_cell(cell):
            raise SitesProjectError(f"{where}: no recipe name")
        name = str(cell).strip()
        if not _RECIPE_NAME.fullmatch(name) or CASE_SEPARATOR in name:
            raise SitesProjectError(
                f"{where}: {name!r} is not a recipe name; write letters, digits and underscores"
            )
        if name in declared:
            raise SitesProjectError(f"{where}: recipe {name!r} is also declared in [sites.recipes]")
        file = row.cells.get(RECIPE_FILE_COLUMN)
        declared[name] = (
            head.path if is_empty_cell(file) else (root / str(file)).resolve(),
            {},
            row,
        )
    if not declared:
        declared[head.path.stem] = (head.path, {}, None)

    out = []
    for name, (file, set_table, row) in declared.items():
        where = f"[sites.recipes] {name}"
        if not file.is_file():
            raise SitesProjectError(f"{where}: no such file {file}")
        try:
            chain = read_toml_chain(file, root=ROOT_CONFIG)
        except tomllib.TOMLDecodeError as exc:
            raise SitesProjectError(f"{where}: {file}: invalid TOML: {exc}") from exc
        except (OSError, TypeError, ValueError) as exc:
            raise SitesProjectError(f"{where}: {file}: {exc}") from exc
        inputs.extend(item.path for item in chain)
        own: Mapping[str, Any] = {}
        if chain[-1].path == head.path:
            base = merge_toml_chain(chain, root=ROOT_CONFIG)
        else:
            if find_sites_file(chain) is None:
                raise SitesProjectError(
                    f"{where}: {file} does not inherit the project file {head.path.name}; "
                    f'write base_config = "{head.path.name}"'
                )
            base, own = merge_toml_chain(chain[:-1], root=ROOT_CONFIG), dict(chain[-1].own)
        label = _label(file, root)
        bind = (own.get("sites") or {}).get("bind") or {}
        own_binds = resolve_binds(bind, label) if bind else []
        binds = [*project_binds, *own_binds]
        _check_columns(binds, [t for t in tables if t is not None], label)
        payload: dict[str, Any] = {}
        for key, value in set_table.items():
            try:
                resolve_field(HydroModPyConfig, parse(key))
            except UnknownPathError as exc:
                raise SitesProjectError(f"{where}: set {exc}") from exc
            assign(payload, parse(key), value)
        if any("site" in part for part in (base, own, payload)):
            raise SitesProjectError(
                f"{where}: {label} writes [site] in a [sites] project; remove "
                "it, each case takes its site from the table."
            )
        out.append(
            ResolvedRecipe(name, file, base, own, payload, row, tuple(binds), tuple(own_binds))
        )
    return out


# -- cases --------------------------------------------------------------------


def _case_id(
    site: ResolvedSite, recipe: ResolvedRecipe, taken: dict[str, str], errors: list[PlanIssue]
) -> str | None:
    """Return the run name of the case of *site* and *recipe*, or ``None`` when it has none."""
    label = f"{site.name}{CASE_SEPARATOR}{recipe.name}"
    case_id = fold_name(label)
    try:
        check_name(case_id, what="run")
    except ConfigError as exc:
        errors.append(PlanIssue(f"case {label!r}: {exc}", case_id=label))
        return None
    if taken.setdefault(case_id, label) != label:
        message = (
            f"cases {taken[case_id]!r} and {label!r} fold to the same run name "
            f"{case_id!r}. Rename a site or a recipe."
        )
        errors.append(PlanIssue(message, case_id=case_id))
        return None
    return case_id


def _case(
    site: ResolvedSite,
    recipe: ResolvedRecipe,
    case_id: str,
    root: Path,
    layers: tuple[Mapping[str, Any], Mapping[str, Any]],
    tables: tuple[Table, Table | None],
    errors: list[PlanIssue],
) -> DraftCase | None:
    from hydromodpy.workflow.solution_key import planned_solution_key

    def refuse(message: str, origin: str | None = None, target: str | None = None) -> None:
        errors.append(PlanIssue(message, origin, target, case_id))

    cli, envp = layers
    site_table, recipe_table = tables
    payload, bound = dict(site.payload), list(site.bound)
    row_payload: Mapping[str, Any] = {}
    try:
        if mine := _on_table(recipe.own_binds, site_table):
            extra, found = _render_row(mine, site.row, site_table)
            payload, bound = merge_toml_payloads(payload, extra), bound + found
        if recipe.row is not None and recipe_table is not None:
            binds = _on_table(recipe.binds, recipe_table)
            row_payload, found = _render_row(binds, recipe.row, recipe_table)
            bound += found
    except CellError as exc:
        return refuse(exc.detail, exc.origin, exc.target)
    try:
        doc = merge_toml_payloads(
            {},
            base_chain=[recipe.base],
            overlays=[payload, site.override, recipe.own, recipe.set, row_payload],
            cli_overrides=cli,
            env_overrides=envp,
        )
        migrate_merged_doc(doc)
    except ValueError as exc:
        return refuse(str(exc), recipe.file.name)
    doc.pop("sites", None)
    try:
        lookup(doc, _SIM_PATH)
    except KeyError:
        assign(doc, _SIM_PATH, case_id)
    else:
        return refuse(
            "[simulation] name is refused in a [sites] project: the case is named "
            "<site>-<recipe>. Remove the key.",
            recipe.file.name,
            str(_SIM_PATH),
        )
    blocks = doc.get("export")
    if isinstance(blocks, list) and any(
        DELIVER_TO_KEY in b for b in blocks if isinstance(b, Mapping)
    ):
        # Every case would send its files to the same destination, one over the other.
        return refuse(
            "deliver_to is refused in a [sites] project, because every case would "
            "send its files to the same destination. Remove it from [[export]], "
            "and take files out with hmp publish.",
            recipe.file.name,
            f"export.{DELIVER_TO_KEY}",
        )
    literal = _literal_site_keys(doc, _leaves(payload) | _leaves(site.override))
    if literal:
        return refuse(
            f"site scoped key(s) hold a literal value shared by every site: "
            f"{', '.join(literal)}. Bind them in [sites.bind] or write them in "
            "site_overrides/<site>.toml."
        )
    try:
        cfg = HydroModPyConfig.from_dict(doc, base_dir=root)
    except ConfigValidationError as exc:
        for detail in exc.details or [{"msg": str(exc)}]:
            loc, owner = str(detail.get("loc", "")), None
            owner = _owner(loc, bound, doc)
            refuse(
                str(detail.get("msg", "")),
                owner[1] if owner else recipe.file.name,
                owner[0] if owner else loc,
            )
        return None
    except ConfigError as exc:
        return refuse(str(exc), recipe.file.name)
    cal = cfg.calibration
    kind: CaseKind = "calibration" if cal is not None else "simulation"
    key = planned_solution_key(cfg, search=cal is not None)
    solves, kept = 1, 1
    if cal is not None:
        solves = max(map(cal.parallel_for, cal.phases)) if cal.phases else int(cal.parallel)
        solves, kept = max(1, solves), max(1, int(cal.save_best_n))
    done = case_is_done(root, case_id, key, kind)
    keys = written_experimental_keys(cfg)
    return DraftCase(case_id, site.name, recipe.name, doc, key, kind, solves, kept, done, keys)


def _owner(
    loc: str, bound: Sequence[tuple[str, str]], doc: Mapping[str, Any]
) -> tuple[str, str] | None:
    """Return the bound (key, origin) a validation location names, or sits under, if one does."""
    for key, origin in bound:
        if loc == key or loc.startswith(key + "."):
            return key, origin
    try:
        lookup(doc, loc)
    except (KeyError, ValueError):
        parts = loc.split(".")
        under = [b for b in bound if b[0].startswith(".".join(parts[:-1]) + ".")]
        if len(parts) - 1 >= 2 and len(under) == 1:
            return under[0]
    return None


def case_is_done(root: Path, case_id: str, config_hash: str | None, kind: CaseKind) -> bool:
    """Whether a sealed run (or a completed session) of this case holds this solution key."""
    if config_hash is None:
        return False
    calibration = kind == "calibration"
    tree = sessions_dir_for(root) if calibration else runs_dir_for(root)
    for entry in tree.iterdir() if tree.is_dir() else ():
        if split_stem_version(entry.name)[0] != case_id:
            continue
        if calibration:
            held = (
                readable(read_session, entry) if session_descriptor_path(entry).is_file() else None
            )
            if held is not None and held.status == "completed" and held.config_hash == config_hash:
                return True
        elif is_sealed(entry):
            seal = readable(read_seal, entry)
            if seal is None or seal.identity.solution_key != config_hash:
                continue
            try:
                level = level_at(entry)
            except (ValueError, OSError):
                continue
            if at_least(level, "result"):
                return True
    return False


# -- writing the plan: plan/<hash>/{plan.json, cases.csv, <case>.toml}, once ----


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_hash(cases: Sequence[DraftCase], inputs: Mapping[str, str]) -> str:
    """Return the fingerprint of a plan: its schema, its cases and the files it was made from."""
    lines = sorted(f"{c.case_id}\t{c.config_hash}\t{_sha256(c.toml())}" for c in cases)
    lines.extend(f"{name}\t{digest}" for name, digest in sorted(inputs.items()))
    return _sha256("\n".join([PLAN_SCHEMA, *lines]))[:PLAN_HASH_LENGTH]


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ";".join(str(item) for item in value)
    return "" if is_empty_cell(value) else str(value)


def build_plan(draft: PlanDraft) -> tuple[Plan, pd.DataFrame, list[PlanCase], dict[str, str]]:
    """Return what :func:`hydromodpy.results.plan_store.write_plan` takes, from a draft."""
    if draft.errors:
        raise PlanError(draft.errors)
    cases = [
        PlanCase(
            case_id=c.case_id,
            site=c.site,
            recipe=c.recipe,
            config_hash=c.config_hash or "",
            config_path=f"{c.case_id}{CASE_TOML_SUFFIX}",
        )
        for c in draft.cases
    ]
    run = draft.sites_config.run
    digests = {
        _label(p, draft.project_root): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in draft.inputs
    }
    hashed = plan_hash(draft.cases, digests)
    # The same plan written again is the same plan: it keeps its instant.
    exists = plan_path(draft.project_root, hashed).is_dir()
    previous = readable(read_plan, draft.project_root, hashed) if exists else None
    plan = Plan(
        plan_hash=hashed,
        hydromodpy_version=__version__,
        created_at=previous.plan.created_at if previous is not None else datetime.now(UTC),
        fingerprints=digests,
        n_cases=len(cases),
        budget={
            "parallel": run.parallel,
            "threads_per_case": run.threads_per_case,
            "solves": sum(c.solves for c in draft.cases),
            "kept_solves": sum(c.kept_solves for c in draft.cases),
        },
    )
    columns = list(dict.fromkeys(k for s in draft.sites for k in s.row.cells if k != "site"))
    rows = [
        {"site": s.name, **{k: _text(s.row.cells.get(k)) for k in columns}} for s in draft.sites
    ]
    sites = pd.DataFrame(rows, columns=["site", *columns], dtype=str)
    return plan, sites, cases, {c.case_id: c.toml() for c in draft.cases}


def running_cases(project_root: Path, case_ids: Iterable[str]) -> list[str]:
    """Return the cases whose run directory, or calibration session, says ``running``."""
    wanted, running = set(case_ids), []
    for tree in (runs_dir_for(project_root), sessions_dir_for(project_root)):
        for entry in sorted(tree.iterdir()) if tree.is_dir() else ():
            if split_stem_version(entry.name)[0] not in wanted or not entry.is_dir():
                continue
            if session_descriptor_path(entry).is_file():
                held = readable(read_session, entry)
                if held is None or held.status != "running":
                    continue
            if effective_status(entry) == "running":
                running.append(f"{tree.name}/{entry.name}")
    return running


def is_plan_case(config_path: str | Path) -> bool:
    """Whether *config_path* is a case of a plan: ``plan/<hash>/<case>.toml``."""
    path = Path(config_path).resolve()
    return (
        path.parent.parent.name == PLAN_DIRNAME
        and (path.parent / PLAN_FILENAME).is_file()
        and path.suffix == CASE_TOML_SUFFIX
    )


def refuse_env_overrides(env: Mapping[str, str], config_path: str | Path) -> None:
    """Refuse ``HMP_SET_*`` for a case of a plan: the plan rendered the overrides already."""
    names = env_set_names(env)
    if names and is_plan_case(config_path):
        raise ConfigError(
            f"{', '.join(names)} set while running a case of a plan; the plan renders "
            "HMP_SET_* into each case. Unset the variable(s), or plan again with them set."
        )


def write_plan_draft(project_root: str | Path, draft: PlanDraft, *, force: bool = False) -> Path:
    """Write ``plan/<hash>/`` from *draft* and return the directory."""
    root = Path(project_root).resolve()
    plan, sites, cases, tomls = build_plan(draft)
    if not force:
        ids = {case.case_id for case in cases}
        current = readable(read_plan, root) if current_plan_hash(root) is not None else None
        if current is not None:
            ids |= {case.case_id for case in current.cases}
        if running := running_cases(root, ids):
            raise RunningCaseError(
                f"case(s) running: {', '.join(running)}; a plan is not rewritten under a "
                "running case. Wait, or pass --force."
            )
    return write_plan(root, plan, sites, cases, tomls)


# -- what a plan costs, as --dry-run says it ----------------------------------


@dataclass(frozen=True, slots=True)
class PlanBudget:
    """The numbers of a plan, as ``--dry-run`` prints them."""

    n_cases: int
    n_sites: int
    n_recipes: int
    n_done: int
    parallel: int
    peak_solves: int
    threads_per_case: int
    cores: int
    kept_solves: int
    scratch_gib: tuple[float, float]


def _peak_solves(solves: list[int], budget: int) -> int:
    peak = running = 0
    for count in sorted(solves, reverse=True):
        if running and running + count > budget:
            peak, running = max(peak, running), 0
        running += count
    return max(peak, running)


def plan_budget(draft: PlanDraft, *, cores: int | None = None) -> PlanBudget:
    """Return the budget of a draft on a machine with *cores* cores."""
    run = draft.sites_config.run
    pending = [case for case in draft.cases if not case.done]
    kept = sum(case.kept_solves for case in pending)
    low, high = SCRATCH_PER_KEPT_SOLVE_GIB
    return PlanBudget(
        n_cases=len(draft.cases),
        n_sites=len(draft.sites),
        n_recipes=len(draft.recipes),
        n_done=len(draft.cases) - len(pending),
        parallel=run.parallel,
        peak_solves=_peak_solves([case.solves for case in pending], run.parallel),
        threads_per_case=run.threads_per_case,
        cores=cores if cores is not None else (os.cpu_count() or 1),
        kept_solves=kept,
        scratch_gib=(kept * low, kept * high),
    )


def dry_run_lines(draft: PlanDraft, budget: PlanBudget) -> list[str]:
    """Return the lines ``hmp run --dry-run`` prints for a ``[sites]`` project."""
    low, high = budget.scratch_gib
    run = draft.sites_config.run
    todo = budget.n_cases - budget.n_done
    lines = [
        f"[dry-run] project : {draft.project_file}",
        f"[dry-run] plan    : {budget.n_cases} cases ({budget.n_sites} sites x "
        f"{budget.n_recipes} recipes), {budget.n_done} already sealed, {todo} to run",
        f"[dry-run] solves  : {budget.parallel} side by side, peak {budget.peak_solves} solves x "
        f"{budget.threads_per_case} threads on {budget.cores} cores",
        f"[dry-run] scratch : {budget.kept_solves} kept solve(s), {low:.1f} to {high:.1f} GiB",
        f"[dry-run] dev     : threads_per_case = {run.threads_per_case}, keep_attempts = "
        f"{run.keep_attempts}, prepare_parallel = {run.prepare_parallel}",
    ]
    for case in draft.cases:
        state = "sealed" if case.done else case.kind
        lines.append(f"[dry-run]   {case.case_id}: {state}, {case.solves} solve(s)")
    return lines
