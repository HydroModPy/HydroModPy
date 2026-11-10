"""Sites x recipes: the cases of a ``[sites]`` project, resolved one by one.

:func:`expand_plan` reads the project, its site table and its recipes, and
returns a :class:`PlanDraft`: one :class:`DraftCase` per (site, recipe) with
its resolved document, its ``config_hash`` and whether a sealed run already
holds it, plus the errors and warnings of the plan, each pointing at the cell
or the file it comes from. The ``config_hash`` of a case is the solution key of
its request, computed offline
(:func:`~hydromodpy.workflow.solution_key.planned_solution_key`), the key its
run seals. Nothing is written: :mod:`hydromodpy.project.launch.sites.plan`
writes a draft under ``plan/<hash>/``.

The precedence of a case, lowest first: the defaults of the schema, the base
of the recipe (the ``base_config`` chain below it), the rendered row of the
site table, ``site_overrides/<site>.toml``, the recipe's own keys (the keys
its file writes, its inline ``set`` and its row of the recipe table), then
``--set`` and ``HMP_SET_*``. A recipe wins over the table on the keys it
writes itself; the table wins over the base.
"""

from __future__ import annotations

import copy
import math
import os
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from hydromodpy.config.config_migration import migrate_layers, migrate_merged_doc
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.config.sites import (
    RECIPE_NAME_PATTERN,
    RecipeSpec,
    SitesConfig,
)
from hydromodpy.core.config_kit.written import written_experimental_keys, written_payload
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.site import SITE_NAME_PATTERN
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, runs_dir_for, sessions_dir_for
from hydromodpy.core.state.names import check_name, fold_name
from hydromodpy.core.toml_io.loader import (
    ChainFile,
    load_toml_with_base_config,
    merge_toml_chain,
    read_toml_chain,
)
from hydromodpy.core.toml_io.merge import merge_toml_payloads
from hydromodpy.core.toml_io.overrides import ENV_SOURCE, SET_SOURCE, env_overrides
from hydromodpy.core.toml_io.paths import (
    UnknownPathError,
    assign,
    lookup,
    parse,
    resolve_field,
)
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.core.workspace.workspace_toml import near_site_m as workspace_near_site_m
from hydromodpy.project.launch.sites.binding import (
    Binding,
    BindingError,
    BoundValue,
    CellError,
    bindings_of_table,
    check_columns,
    render_row,
    resolve_bindings,
)
from hydromodpy.project.launch.sites.issues import PlanIssue
from hydromodpy.project.launch.sites.site_scoped import leaf_paths, literal_site_scoped_keys
from hydromodpy.project.launch.sites.tables import (
    Table,
    TableError,
    TableRow,
    is_empty_cell,
    read_table,
    table_from_site_rows,
)

CaseKind = Literal["simulation", "calibration", "overview"]

RECIPE_COLUMN = "recipe"
"""Mandatory column of a recipe table: the name of the recipe."""

RECIPE_FILE_COLUMN = "file"
"""Optional column of a recipe table: the TOML file of the recipe, else the project file."""

CASE_SEPARATOR = "-"
"""Separates the site from the recipe in a case id."""

CATALOG_BIND: dict[str, str] = {
    "site.name": "site",
    "site.label": "label",
    "site.gauge": "gauge",
    "site.uri": "uri",
    "geographic.catchment.x_outlet": "x_outlet",
    "geographic.catchment.y_outlet": "y_outlet",
}
"""How the fixed columns of the workspace site catalog reach a case."""

_SITE_NAME_RE = re.compile(SITE_NAME_PATTERN)
_RECIPE_NAME_RE = re.compile(RECIPE_NAME_PATTERN)
_SITE_NAME_PATH = parse("site.name")
_SIMULATION_NAME_PATH = parse("simulation.name")
_OUTLET_PATHS = (parse("geographic.catchment.x_outlet"), parse("geographic.catchment.y_outlet"))


class SitesProjectError(ConfigError):
    """The file is not a ``[sites]`` project a plan can be built from."""


@dataclass(frozen=True, slots=True)
class ResolvedRecipe:
    """One recipe: a file, what it writes itself, and the bind lines it adds."""

    name: str
    file: Path
    base: Mapping[str, Any]
    """The chain below the recipe's own keys, merged."""

    own: Mapping[str, Any]
    """The keys the recipe file writes itself; empty for the project file."""

    set: Mapping[str, Any]
    """The inline ``set`` table, rendered as a payload."""

    row: TableRow | None
    """The row of the recipe table, when the recipe comes from one."""

    bindings: tuple[Binding, ...]
    """The bind lines of the project and of the recipe, resolved."""

    own_bindings: tuple[Binding, ...]
    """The bind lines the recipe file adds, valid for its cases alone."""


@dataclass(frozen=True, slots=True)
class ResolvedSite:
    """One site of the plan: its row, its rendered keys and its overlay."""

    name: str
    row: TableRow
    payload: Mapping[str, Any]
    """The row rendered through the bind lines of the site table."""

    bound: tuple[BoundValue, ...]
    override: Mapping[str, Any]
    """``site_overrides/<site>.toml`` resolved, empty when absent."""

    override_path: Path | None

    def outlet(self) -> tuple[float, float] | None:
        """Return the outlet the row binds, when both coordinates are bound."""
        try:
            x = lookup(self.payload, _OUTLET_PATHS[0])
            y = lookup(self.payload, _OUTLET_PATHS[1])
        except KeyError:
            return None
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return float(x), float(y)
        return None


@dataclass(frozen=True, slots=True)
class DraftCase:
    """One case of the plan: a site crossed with a recipe, resolved and checked."""

    case_id: str
    site: str
    recipe: str
    document: Mapping[str, Any]
    """The resolved TOML document of the case, replayable alone."""

    config_hash: str | None
    """Solution key of the case; None when the case did not validate or needs the network."""

    kind: CaseKind
    solves: int
    """Solves the case runs side by side: 1, or ``[calibration] parallel``."""

    kept_solves: int
    """Solves the case keeps on disk: 1, or ``[calibration] save_best_n``."""

    done: bool
    """Whether a sealed run or a completed session already holds this hash."""

    experimental_keys: tuple[str, ...] = ()
    """The experimental keys the document of the case writes."""

    def toml(self) -> str:
        """Return the document as TOML text."""
        return dumps(dict(self.document))


@dataclass(frozen=True, slots=True)
class PlanDraft:
    """A plan before it is written: its cases, and what is wrong with them.

    A ``[sites]`` project holds one case per site and recipe, and :func:`expand_plan`
    fills every field. A single configuration holds one case and no table: ``sites_config``
    and ``site_table`` are ``None``, and ``steps`` says what its run would execute.
    """

    project_root: Path
    project_file: Path | None
    config_path: Path | None
    sites_config: SitesConfig | None
    site_table: Table | None
    sites: tuple[ResolvedSite, ...]
    recipes: tuple[ResolvedRecipe, ...]
    cases: tuple[DraftCase, ...]
    errors: tuple[PlanIssue, ...] = ()
    warnings: tuple[PlanIssue, ...] = ()
    inputs: tuple[Path, ...] = ()
    """Every file the plan was made from, for its fingerprints."""
    steps: tuple[str, ...] = ()
    """The pipeline steps the one case of a single configuration would execute, in order."""

    @property
    def ok(self) -> bool:
        """Whether every case validated."""
        return not self.errors


def _issue(exc: Exception, *, case_id: str | None = None) -> PlanIssue:
    if isinstance(exc, CellError):
        return PlanIssue(
            message=exc.detail,
            origin=str(exc.origin),
            target=str(exc.target),
            case_id=case_id,
        )
    return PlanIssue(message=str(exc), case_id=case_id)


def _relative_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


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


def declares_sites(own: Mapping[str, Any]) -> bool:
    """Whether a document writes ``[sites]`` with more than its ``bind`` table."""
    section = own.get("sites")
    if not isinstance(section, Mapping):
        return False
    return any(key != "bind" for key in section)


def expand_plan(
    project_root: str | Path,
    config_path: str | Path,
    *,
    set_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    near_site_m: float | None = None,
) -> PlanDraft:
    """Resolve every case of the ``[sites]`` project *config_path* belongs to.

    *config_path* is the file that declares ``[sites]`` (every recipe runs)
    or one recipe file (that recipe alone runs on every site). *project_root*
    is the folder of ``project.toml``, which anchors every relative path.
    *set_overrides* is the payload of ``--set`` and *env* the environment
    whose ``HMP_SET_*`` variables are rendered into every case; both sit on
    top of the precedence. *near_site_m* is the distance under which two
    outlets are reported as one catchment; unset, ``[sites] near_site_m`` of
    the workspace. A problem of the project itself (no ``[sites]``,
    no ``project.toml``, a bind line the schema has not) raises
    :class:`SitesProjectError`; a problem of one case goes to the draft.
    """
    root = Path(project_root).resolve()
    path = Path(config_path).resolve()
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        raise SitesProjectError(
            f"a [sites] project is anchored by {PROJECT_MARKER_FILENAME} at its root; none "
            f"in {root}"
        )
    chain = read_toml_chain(path, root=ROOT_CONFIG)
    sites_file = find_sites_file(chain)
    if sites_file is None:
        raise SitesProjectError(f"{path}: no [sites] section in the file or its base_config chain")
    project_doc = merge_toml_chain(chain[: chain.index(sites_file) + 1], root=ROOT_CONFIG)
    if "site" in project_doc:
        raise SitesProjectError(
            f"{sites_file.path}: [site] is declared beside [sites]; remove [site], each "
            "case takes its site from the table."
        )
    try:
        sites_config = SitesConfig.model_validate(project_doc["sites"])
    except ValidationError as exc:
        raise SitesProjectError(f"{sites_file.path}: [sites] {exc}") from exc

    project_label = _relative_label(sites_file.path, root)
    project_bindings = resolve_bindings(
        sites_config.bind, schema=HydroModPyConfig, where=project_label
    )
    inputs: list[Path] = [item.path for item in chain]
    workspace_root = _workspace_root(project_doc, root)
    if near_site_m is None:
        near_site_m = workspace_near_site_m(workspace_root)

    site_table = _read_site_table(sites_config, root, workspace_root, inputs)
    recipes_table = _read_recipes_table(sites_config, root, inputs)
    tables = [site_table] + ([recipes_table] if recipes_table is not None else [])

    recipes = _resolve_recipes(
        sites_config,
        root=root,
        sites_file=sites_file,
        project_bindings=project_bindings,
        recipes_table=recipes_table,
        tables=tables,
        schema=HydroModPyConfig,
        inputs=inputs,
    )
    selected = _select_recipes(recipes, path, sites_file)

    errors: list[PlanIssue] = []
    warnings: list[PlanIssue] = []
    site_bindings = bindings_of_table(project_bindings, site_table)
    sites = _resolve_sites(
        sites_config, site_table, site_bindings, root=root, errors=errors, inputs=inputs
    )
    _warn_near_outlets(sites, near_site_m, warnings)

    cli_payload = copy.deepcopy(dict(set_overrides or {}))
    env_payload = env_overrides(os.environ if env is None else env)
    migrate_layers([(SET_SOURCE, cli_payload), (ENV_SOURCE, env_payload)])
    cases: list[DraftCase] = []
    taken: dict[str, str] = {}
    for site in sites:
        for recipe in selected:
            case_id = _case_id(site, recipe, taken=taken, errors=errors)
            if case_id is None:
                continue
            case = _resolve_case(
                site,
                recipe,
                case_id=case_id,
                root=root,
                schema=HydroModPyConfig,
                cli=cli_payload,
                env=env_payload,
                site_table=site_table,
                recipes_table=recipes_table,
                errors=errors,
            )
            if case is not None:
                cases.append(case)
    return PlanDraft(
        project_root=root,
        project_file=sites_file.path,
        config_path=path,
        sites_config=sites_config,
        site_table=site_table,
        sites=tuple(sites),
        recipes=tuple(selected),
        cases=tuple(cases),
        errors=tuple(errors),
        warnings=tuple(warnings),
        inputs=tuple(dict.fromkeys(inputs)),
    )


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
    case = DraftCase(
        case_id=name,
        site=str(site or ""),
        recipe="",
        document=written_payload(config),
        config_hash=planned_solution_key(config, search=kind == "calibration"),
        kind=kind,
        solves=1,
        kept_solves=1,
        done=done,
        experimental_keys=written_experimental_keys(config),
    )
    return PlanDraft(
        project_root=Path(config.workspace.project_root),
        project_file=config_path,
        config_path=config_path,
        sites_config=None,
        site_table=None,
        sites=(),
        recipes=(),
        cases=(case,),
        steps=tuple(steps),
    )


# -- sites --------------------------------------------------------------------


def _workspace_root(project_doc: Mapping[str, Any], root: Path) -> Path:
    """Return the workspace root ``[workspace]`` of the project resolves to."""
    from hydromodpy.config.section_loader import load_standard_section
    from hydromodpy.core.workspace.config import WorkspaceConfig

    workspace_section = dict(project_doc.get("workspace") or {})
    workspace_section["project_root"] = str(root)
    return Path(load_standard_section(workspace_section, WorkspaceConfig, root).root)


def _read_site_table(
    sites: SitesConfig, root: Path, workspace_root: Path, inputs: list[Path]
) -> Table:
    if sites.table is not None:
        path = (root / sites.table).resolve()
        inputs.append(path)
        return read_table(path, label=_relative_label(path, root))
    from hydromodpy.data.sites.catalog import catalog_path, read_catalog

    catalog = catalog_path(workspace_root)
    if not catalog.is_file():
        raise SitesProjectError(
            f"[sites] names no table and the workspace has no site catalog at {catalog}; "
            "declare sites with hmp site add or hmp site import, or write [sites] table."
        )
    inputs.append(catalog)
    return table_from_site_rows(read_catalog(workspace_root), path=catalog, label=str(catalog))


def _read_recipes_table(sites: SitesConfig, root: Path, inputs: list[Path]) -> Table | None:
    if sites.recipes_table is None:
        return None
    path = (root / sites.recipes_table).resolve()
    inputs.append(path)
    table = read_table(path, label=_relative_label(path, root))
    if RECIPE_COLUMN not in table.columns:
        raise TableError(f"{table.label}: a recipe table has a {RECIPE_COLUMN!r} column")
    return table


def _resolve_sites(
    sites: SitesConfig,
    table: Table,
    bindings: Sequence[Binding],
    *,
    root: Path,
    errors: list[PlanIssue],
    inputs: list[Path],
) -> list[ResolvedSite]:
    if sites.table is None:
        effective = list(bindings)
        names = {str(b.path) for b in effective}

        for key, column in CATALOG_BIND.items():
            if key not in names:
                effective.append(
                    Binding(
                        path=parse(key),
                        columns=(column,),
                        field=resolve_field(HydroModPyConfig, key),
                    )
                )
        bindings = effective
    if not any(b.path == _SITE_NAME_PATH for b in bindings):
        raise BindingError(
            f'{table.label}: no bind line names the site; write [sites.bind] "site.name" = '
            '"<column>".'
        )
    if sites.enabled is not None and sites.enabled not in table.columns:
        raise TableError(f"{table.label}: no column {sites.enabled!r} for [sites] enabled")
    seen: dict[str, int] = {}
    out: list[ResolvedSite] = []
    for row in table.rows:
        if sites.enabled is not None and not _truthy(row.cells.get(sites.enabled)):
            continue
        try:
            payload, bound = render_row(bindings, row, table)
            name = lookup(payload, _SITE_NAME_PATH)
        except KeyError:
            errors.append(
                PlanIssue(
                    message="the row names no site",
                    origin=str(row.origin(table, _site_column(bindings))),
                    target=str(_SITE_NAME_PATH),
                )
            )
            continue
        except CellError as exc:
            errors.append(_issue(exc))
            continue
        name = str(name)
        if not _SITE_NAME_RE.fullmatch(name):
            errors.append(
                PlanIssue(
                    message=f"{name!r} is not a site name; write letters, digits and underscores",
                    origin=str(row.origin(table, _site_column(bindings))),
                    target=str(_SITE_NAME_PATH),
                )
            )
            continue
        if sites.include and name not in sites.include:
            continue
        if name in sites.exclude:
            continue
        if name in seen:
            errors.append(
                PlanIssue(
                    message=f"site {name!r} is declared twice (rows {seen[name]} and {row.index})",
                    origin=str(row.origin(table, _site_column(bindings))),
                    target=str(_SITE_NAME_PATH),
                )
            )
            continue
        seen[name] = row.index
        override_path = None
        override: Mapping[str, Any] = {}
        if sites.overrides is not None:
            candidate = (root / sites.overrides / f"{name}.toml").resolve()
            if candidate.is_file():
                override_path = candidate
                inputs.append(candidate)
                try:
                    override = load_toml_with_base_config(candidate, root=ROOT_CONFIG)
                except (ValueError, TypeError) as exc:
                    errors.append(
                        PlanIssue(message=str(exc), origin=_relative_label(candidate, root))
                    )
                    continue
        out.append(
            ResolvedSite(
                name=name,
                row=row,
                payload=payload,
                bound=tuple(bound),
                override=override,
                override_path=override_path,
            )
        )
    return out


def _site_column(bindings: Sequence[Binding]) -> str:
    for binding in bindings:
        if binding.path == _SITE_NAME_PATH:
            return binding.columns[0]
    return "site"


def _truthy(cell: Any) -> bool:
    if isinstance(cell, bool):
        return cell
    if is_empty_cell(cell):
        return False
    text = str(cell).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise TableError(f"enabled column: {cell!r} is not a boolean")


def _warn_near_outlets(
    sites: Sequence[ResolvedSite], near_site_m: float, warnings: list[PlanIssue]
) -> None:
    placed = [(site, site.outlet()) for site in sites]
    placed = [(site, outlet) for site, outlet in placed if outlet is not None]
    for i, (first, (x1, y1)) in enumerate(placed):
        for second, (x2, y2) in placed[i + 1 :]:
            distance = math.hypot(x2 - x1, y2 - y1)
            if distance < near_site_m:
                warnings.append(
                    PlanIssue(
                        message=(
                            f"sites {first.name} and {second.name} have outlets {distance:.0f} m "
                            f"apart, under near_site_m = {near_site_m:g} m; one catchment "
                            "declared twice?"
                        )
                    )
                )


# -- recipes ------------------------------------------------------------------


def _resolve_recipes(
    sites: SitesConfig,
    *,
    root: Path,
    sites_file: ChainFile,
    project_bindings: Sequence[Binding],
    recipes_table: Table | None,
    tables: Sequence[Table],
    schema: Any,
    inputs: list[Path],
) -> list[ResolvedRecipe]:
    declared: dict[str, tuple[Path, Mapping[str, Any], TableRow | None]] = {}
    for name, decl in sites.recipes.items():
        file = decl.file if isinstance(decl, RecipeSpec) else decl
        set_table = decl.set if isinstance(decl, RecipeSpec) else {}
        declared[name] = ((root / file).resolve(), set_table, None)
    if recipes_table is not None:
        for row in recipes_table.rows:
            name = row.cells.get(RECIPE_COLUMN)
            if is_empty_cell(name):
                raise TableError(f"{row.origin(recipes_table, RECIPE_COLUMN)}: no recipe name")
            name = str(name).strip()
            if not _RECIPE_NAME_RE.fullmatch(name) or CASE_SEPARATOR in name:
                raise TableError(
                    f"{row.origin(recipes_table, RECIPE_COLUMN)}: {name!r} is not a recipe "
                    "name; write letters, digits and underscores"
                )
            if name in declared:
                raise TableError(
                    f"{row.origin(recipes_table, RECIPE_COLUMN)}: recipe {name!r} is also "
                    "declared in [sites.recipes]"
                )
            file_cell = row.cells.get(RECIPE_FILE_COLUMN)
            file = (
                sites_file.path if is_empty_cell(file_cell) else (root / str(file_cell)).resolve()
            )
            declared[name] = (file, {}, row)
    if not declared:
        declared[sites_file.path.stem] = (sites_file.path, {}, None)

    recipes: list[ResolvedRecipe] = []
    for name, (file, set_table, row) in declared.items():
        if not file.is_file():
            raise SitesProjectError(f"[sites.recipes] {name}: no such file {file}")
        chain = _read_recipe_chain(name, file)
        inputs.extend(item.path for item in chain)
        leaf = chain[-1]
        if leaf.path == sites_file.path:
            base: Mapping[str, Any] = merge_toml_chain(chain, root=ROOT_CONFIG)
            own: Mapping[str, Any] = {}
            recipe_bind: Mapping[str, Any] = {}
        else:
            # Two files declaring [sites] were refused by find_sites_file.
            if find_sites_file(chain) is None:
                raise SitesProjectError(
                    f"[sites.recipes] {name}: {file} does not inherit the project file "
                    f'{sites_file.path.name}; write base_config = "{sites_file.path.name}"'
                )
            base = merge_toml_chain(chain[:-1], root=ROOT_CONFIG)
            own = dict(leaf.own)
            recipe_bind = dict((own.get("sites") or {}).get("bind") or {})
        label = _relative_label(file, root)
        own_bindings = (
            resolve_bindings(recipe_bind, schema=schema, where=label) if recipe_bind else []
        )
        bindings = [*project_bindings, *own_bindings]
        check_columns(bindings, tables, where=label)
        set_payload = _render_set(set_table, schema=schema, where=f"[sites.recipes] {name}")
        if any("site" in document for document in (base, own, set_payload)):
            raise SitesProjectError(
                f"[sites.recipes] {name}: {label} writes [site] in a [sites] project; remove "
                "it, each case takes its site from the table."
            )
        recipes.append(
            ResolvedRecipe(
                name=name,
                file=file,
                base=base,
                own=own,
                set=set_payload,
                row=row,
                bindings=tuple(bindings),
                own_bindings=tuple(own_bindings),
            )
        )
    return recipes


def _read_recipe_chain(name: str, file: Path) -> tuple[ChainFile, ...]:
    """Read the chain of a recipe file; a file that cannot be read names the recipe."""
    try:
        return read_toml_chain(file, root=ROOT_CONFIG)
    except tomllib.TOMLDecodeError as exc:
        raise SitesProjectError(f"[sites.recipes] {name}: {file}: invalid TOML: {exc}") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise SitesProjectError(f"[sites.recipes] {name}: {file}: {exc}") from exc


def _render_set(set_table: Mapping[str, Any], *, schema: Any, where: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in set_table.items():
        try:
            path = parse(key)
            resolve_field(schema, path)
        except UnknownPathError as exc:
            raise SitesProjectError(f"{where}: set {exc}") from exc
        assign(payload, path, value)
    return payload


def _select_recipes(
    recipes: Sequence[ResolvedRecipe], config_path: Path, sites_file: ChainFile
) -> list[ResolvedRecipe]:
    """Return the recipes *config_path* asks for: all of them, or those of that file."""
    if config_path == sites_file.path:
        return list(recipes)
    chosen = [recipe for recipe in recipes if recipe.file == config_path]
    if not chosen:
        listed = ", ".join(f"{r.name} ({r.file.name})" for r in recipes)
        raise SitesProjectError(
            f"{config_path.name} is not a recipe of {sites_file.path.name}; the recipes are "
            f"{listed}. Run the project file, or list this file under [sites.recipes]."
        )
    return chosen


# -- cases --------------------------------------------------------------------


def _case_id(
    site: ResolvedSite,
    recipe: ResolvedRecipe,
    *,
    taken: dict[str, str],
    errors: list[PlanIssue],
) -> str | None:
    """Return the run name of the case of *site* and *recipe*, or ``None`` when it has none.

    The code makes the name from two texts that are no run names, so the name is
    folded: lower case, and ``_`` for what a name does not hold. It is then held to
    the rule of a run name, and two cases that fold to one name are refused, since
    they would be versions of one run.
    """
    label = f"{site.name}{CASE_SEPARATOR}{recipe.name}"
    case_id = fold_name(label)
    try:
        check_name(case_id, what="run")
    except ConfigError as exc:
        errors.append(PlanIssue(message=f"case {label!r}: {exc}", case_id=label))
        return None
    if taken.setdefault(case_id, label) != label:
        errors.append(
            PlanIssue(
                message=(
                    f"cases {taken[case_id]!r} and {label!r} fold to the same run name "
                    f"{case_id!r}. Rename a site or a recipe."
                ),
                case_id=case_id,
            )
        )
        return None
    return case_id


def _resolve_case(
    site: ResolvedSite,
    recipe: ResolvedRecipe,
    *,
    case_id: str,
    root: Path,
    schema: Any,
    cli: Mapping[str, Any],
    env: Mapping[str, Any],
    site_table: Table,
    recipes_table: Table | None,
    errors: list[PlanIssue],
) -> DraftCase | None:
    bound: list[BoundValue] = list(site.bound)
    site_payload: dict[str, Any] = dict(site.payload)
    row_payload: Mapping[str, Any] = {}
    try:
        # The bind lines of the recipe read the site row for this recipe alone.
        own_on_site = bindings_of_table(recipe.own_bindings, site_table)
        if own_on_site:
            extra_payload, extra_bound = render_row(own_on_site, site.row, site_table)
            site_payload = merge_toml_payloads(site_payload, extra_payload)
            bound.extend(extra_bound)
        if recipe.row is not None and recipes_table is not None:
            row_payload, row_bound = render_row(
                bindings_of_table(recipe.bindings, recipes_table), recipe.row, recipes_table
            )
            bound.extend(row_bound)
    except CellError as exc:
        errors.append(_issue(exc, case_id=case_id))
        return None
    try:
        document = merge_toml_payloads(
            {},
            base_chain=[recipe.base],
            overlays=[site_payload, site.override, recipe.own, recipe.set, row_payload],
            cli_overrides=cli,
            env_overrides=env,
        )
        # What waited for the whole document. Each layer told its old forms already.
        migrate_merged_doc(document)
    except ValueError as exc:
        errors.append(PlanIssue(message=str(exc), origin=recipe.file.name, case_id=case_id))
        return None
    document.pop("sites", None)
    try:
        lookup(document, _SIMULATION_NAME_PATH)
    except KeyError:
        pass
    else:
        errors.append(
            PlanIssue(
                message=(
                    "[simulation] name is refused in a [sites] project: the case is named "
                    "<site>-<recipe>. Remove the key."
                ),
                origin=recipe.file.name,
                target=str(_SIMULATION_NAME_PATH),
                case_id=case_id,
            )
        )
        return None
    assign(document, _SIMULATION_NAME_PATH, case_id)

    varying = leaf_paths(site_payload) | leaf_paths(site.override)
    literal = literal_site_scoped_keys(document, varying)
    if literal:
        errors.append(
            PlanIssue(
                message=(
                    "site scoped key(s) hold a literal value shared by every site: "
                    f"{', '.join(literal)}. Bind them in [sites.bind] or write them in "
                    "site_overrides/<site>.toml."
                ),
                case_id=case_id,
            )
        )
        return None

    cfg = _validate_case(
        document, bound, root=root, schema=schema, recipe=recipe, case_id=case_id, errors=errors
    )
    if cfg is None:
        return None
    from hydromodpy.workflow.solution_key import planned_solution_key

    kind: CaseKind = "calibration" if cfg.calibration is not None else "simulation"
    config_hash = planned_solution_key(cfg, search=kind == "calibration")
    solves = _calibration_width(cfg.calibration) if cfg.calibration is not None else 1
    kept = int(cfg.calibration.save_best_n) if kind == "calibration" else 1
    return DraftCase(
        case_id=case_id,
        site=site.name,
        recipe=recipe.name,
        document=document,
        config_hash=config_hash,
        kind=kind,
        solves=max(1, solves),
        kept_solves=max(1, kept),
        done=case_is_done(root, case_id, config_hash, kind),
        experimental_keys=written_experimental_keys(cfg),
    )


def _calibration_width(calibration: Any) -> int:
    """Return the trials a calibration solves side by side at its widest phase."""
    phases = list(calibration.phases or [])
    if not phases:
        return int(calibration.parallel)
    return max(calibration.parallel_for(phase) for phase in phases)


def _validate_case(
    document: Mapping[str, Any],
    bound: Sequence[BoundValue],
    *,
    root: Path,
    schema: Any,
    recipe: ResolvedRecipe,
    case_id: str,
    errors: list[PlanIssue],
) -> Any:
    from hydromodpy.core.exceptions import ConfigValidationError

    try:
        return schema.from_dict(document, base_dir=root)
    except ConfigValidationError as exc:
        if not exc.details:
            errors.append(PlanIssue(message=str(exc), origin=recipe.file.name, case_id=case_id))
            return None
        for detail in exc.details:
            loc = str(detail.get("loc", ""))
            message = str(detail.get("msg", ""))
            owner = _owner_of(loc, bound, document)
            if owner is not None:
                errors.append(
                    PlanIssue(
                        message=message,
                        origin=str(owner.origin),
                        target=str(owner.path),
                        case_id=case_id,
                    )
                )
            else:
                errors.append(
                    PlanIssue(message=message, origin=recipe.file.name, target=loc, case_id=case_id)
                )
        return None
    except ConfigError as exc:
        errors.append(PlanIssue(message=str(exc), origin=recipe.file.name, case_id=case_id))
        return None


def _owner_of(
    loc: str, bound: Sequence[BoundValue], document: Mapping[str, Any]
) -> BoundValue | None:
    """Return the bound value a validation location points at, if one does.

    The location names the key itself, or a key under it. A model validator
    reports the table it checked, under the tag of the union variant it
    chose (``flow.param.K.field.homogeneous``): when the location is not a
    key of the document, its parent table is taken, and the bound key under
    that table is the owner. A table of fewer than two parts owns nothing:
    an error on a root section is not an error of a cell.
    """
    direct = next((value for value in bound if value.covers(loc)), None)
    if direct is not None:
        return direct
    try:
        lookup(document, loc)
    except (KeyError, ValueError):
        parts = loc.split(".")
        table = ".".join(parts[:-1])
        if len(parts) - 1 >= 2:
            under = [value for value in bound if str(value.path).startswith(table + ".")]
            if len(under) == 1:
                return under[0]
    return None


def case_is_done(root: Path, case_id: str, config_hash: str | None, kind: CaseKind) -> bool:
    """Whether a sealed run (or a completed session) of this case holds this solution key.

    A calibration compares the hash of its sessions, never the one of the run
    it promoted, whose parameters the best trial replaced. ``--dry-run`` and
    the launcher both ask this question, so they say the same thing.
    """
    if config_hash is None:
        return False
    from hydromodpy.results.catalog.registration import split_stem_version
    from hydromodpy.results.record.manifest import is_sealed, read_seal
    from hydromodpy.results.storage.json_io import readable

    if kind == "calibration":
        from hydromodpy.results.session.descriptor import read_session, session_descriptor_path

        sessions = sessions_dir_for(root)
        if sessions.is_dir():
            for entry in sessions.iterdir():
                if split_stem_version(entry.name)[0] != case_id:
                    continue
                if not session_descriptor_path(entry).is_file():
                    continue
                descriptor = readable(read_session, entry)
                if (
                    descriptor is not None
                    and descriptor.status == "completed"
                    and descriptor.config_hash == config_hash
                ):
                    return True
        return False
    runs = runs_dir_for(root)
    if not runs.is_dir():
        return False
    for entry in runs.iterdir():
        if split_stem_version(entry.name)[0] != case_id or not is_sealed(entry):
            continue
        seal = readable(read_seal, entry)
        if seal is not None and seal.identity.solution_key == config_hash:
            return True
    return False


__all__ = [
    "CASE_SEPARATOR",
    "CATALOG_BIND",
    "RECIPE_COLUMN",
    "RECIPE_FILE_COLUMN",
    "CaseKind",
    "DraftCase",
    "PlanDraft",
    "single_case_draft",
    "ResolvedRecipe",
    "ResolvedSite",
    "SitesProjectError",
    "case_is_done",
    "declares_sites",
    "expand_plan",
    "find_sites_file",
]
