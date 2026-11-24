"""Models of the ``[sites]`` section, checked when the file is read.

A ``[sites]`` project runs every recipe on every site of a table: the plan is
sites x recipes, one case ``<site>-<recipe>`` per pair. This module validates
what the TOML says without reading any file: the recipe names, the dotted
keys of ``[sites.bind]`` and of an inline recipe ``set``, the run budget, the
summary columns and the exports. Checking ``bind`` against the schema of the
resolved recipe needs that recipe read, so it belongs to the expansion.

TOML form::

    [sites]
    table = "sites.csv"
    overrides = "site_overrides/"

    [sites.recipes]
    base = "project.toml"                                   # a file
    k2e_5 = { file = "project.toml", set = { "flow.param.K.field.value" = 2e-5 } }

    [sites.bind]
    "geographic.catchment.x_outlet" = "x_outlet"            # quoted: one key

    [sites.design]                                          # points instead of a recipe table
    method = "sobol"
    n = 64
    seed = 1
    [sites.design.parameters.K]
    path = "flow.param.K.field.value"
    bounds = [1e-7, 1e-3]
    sampling = "log_uniform"

``is_sites_project`` tells a ``[sites]`` project from the others. The plan of a campaign
built from the section lives in ``project/launch/plan.py``.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from hydromodpy.calibration.config_objective import CalibParameterDecl
from hydromodpy.calibration.optim.design import SAMPLERS, grid_size, sampler_options
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import Names
from hydromodpy.core.scoring.metric_table import CONSECUTIVE_METRIC_NAMES, RUN_METRIC_NAMES
from hydromodpy.core.site.config import SITE_NAME_PATTERN
from hydromodpy.core.state.names import split_stem_version
from hydromodpy.core.time.period_aggregation import check_months
from hydromodpy.core.toml_io.paths import parse as parse_dotted_path

RECIPE_NAME_PATTERN = SITE_NAME_PATTERN
"""Grammar of a recipe name, the same as a site name."""

_RECIPE_NAME_RE = re.compile(RECIPE_NAME_PATTERN)

PARALLEL_CEILING = 16
"""Highest ``[sites.run] parallel`` accepted without ``--force`` (16 runs held 14 GiB)."""

PREPARE_PARALLEL_CEILING = 8
"""Highest ``[sites.run] prepare_parallel`` accepted without ``--force``."""


def _check_dotted_keys(table: dict[str, Any], *, where: str) -> None:
    """Refuse a key that is not one dotted path, or a value that became a table.

    TOML reads ``site.name = "site"`` unquoted as a nested table ``site`` with a
    key ``name``. Quoted, ``"site.name" = "site"`` is one key holding the path.
    A table value is therefore the mark of a missing pair of quotes.
    """
    for key, value in table.items():
        if isinstance(value, dict):
            raise ValueError(
                f"{where}: {key!r} holds a table, so its dotted key was written without "
                f'quotes. Write the whole path as one quoted key: "{key}.<...>" = ...'
            )
        try:
            parse_dotted_path(key)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc


class RecipeSpec(HydroModelBase):
    """A recipe written inline: a TOML file and the keys it sets on top of it."""

    file: Annotated[Path, Profile.USER] = Field(
        description=(
            "TOML file the recipe starts from, relative to the project root. The "
            "resolved file is the case before the keys of 'set' are applied."
        ),
        examples=["project.toml"],
    )
    set: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Keys this recipe writes on top of its file, as quoted dotted paths "
            '("flow.param.K.field.value" = 2e-5), the grammar of hmp run --set, '
            "without index. They are the recipe's own keys: they win over the site "
            "table and the site overlays."
        ),
        examples=[{"flow.param.K.field.value": 2e-5}],
    )

    @field_validator("set", mode="before")
    @classmethod
    def _keys_are_dotted_paths(cls, value: Any) -> Any:
        if isinstance(value, dict):
            _check_dotted_keys(value, where="recipe set")
        return value


RecipeDecl = Path | RecipeSpec
"""A recipe: a bare path is the short form of ``{ file = <path> }``."""


class SitesRunConfig(HydroModelBase):
    """How the cases of a ``[sites]`` project are run side by side."""

    parallel: Annotated[int, Profile.USER] = Field(
        default=8,
        ge=1,
        description=(
            "Total budget of solves that run side by side. A case whose "
            "[calibration] parallel is 5 takes 5 of it. The default is 8 because the "
            "throughput levelled off from 8 runs side by side on 22 cores, each run "
            "holding up to 1.2 GiB. Above 16 the launcher refuses without --force "
            "(16 runs held 14 GiB), and above 8 for a campaign that holds a calibration."
        ),
        examples=[8],
        json_schema_extra=field_metadata(unit="-"),
    )
    on_error: Annotated[Literal["warn", "raise"], Profile.USER] = Field(
        default="warn",
        description="What a failed case does to the launch.",
        json_schema_extra={
            "value_docs": {
                "warn": "The failure is recorded and the other cases go on.",
                "raise": "The launch stops at the first failed case.",
            }
        },
    )
    threads_per_case: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=1,
        description=(
            "Threads one case may use, applied by the case process itself to its "
            "numerical libraries and its child processes. Shown by --dry-run. The "
            "default is 1: one run already kept about 1.8 cores busy, and parallel "
            "times threads_per_case above the cores is refused without --force."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    keep_attempts: Annotated[int, Profile.DEV] = Field(
        default=1,
        ge=0,
        description=(
            "Earlier attempts of a case kept under runs/<case>/attempts/ when a "
            "fresh attempt starts. Shown by --dry-run."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    prepare_parallel: Annotated[int, Profile.DEV] = Field(
        default=2,
        ge=1,
        description=(
            "Cases prepared side by side before the solves: the geography and the "
            "data of each case. Two cases of one site are never prepared together, "
            "since they write the same data files. Above 8 the launcher refuses "
            "without --force: 16 runs writing the data cache at once lost a write."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )


def _refuse_variables(data: Any, where: str) -> Any:
    """Refuse the key ``variables`` with the one that replaced it."""
    if isinstance(data, Mapping) and "variables" in data:
        raise ValueError(
            f"{where} variables is now variable, the key [[display.figure]] and [[export]] "
            f"write too: write variable = {data['variables']!r}."
        )
    return data


class SummaryWindow(HydroModelBase):
    """One window the runs are scored on again after the fact, one ``[[sites.summary.window]]``."""

    name: Annotated[str, Profile.USER] = Field(
        description="Name of the window, the window_name column of summary/scores.parquet.",
        examples=["dry-summers"],
    )
    start: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="First day of the window, an ISO date. Unset, the start of each run.",
        examples=["2016-01-01"],
    )
    end: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Last day of the window, an ISO date. Unset, the end of each run.",
        examples=["2018-12-31"],
    )
    months: Annotated[list[int] | None, Profile.USER] = Field(
        default=None,
        description="Calendar months kept, 1 to 12. Unset, every month.",
        examples=[[6, 7, 8, 9]],
    )

    @field_validator("start", "end")
    @classmethod
    def _is_a_date(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                raise ValueError(f"{value!r} is not an ISO date (YYYY-MM-DD).") from None
        return value

    @field_validator("months")
    @classmethod
    def _are_months(cls, value: list[int] | None) -> list[int] | None:
        return None if value is None else list(check_months(value))


class SitesSummaryConfig(HydroModelBase):
    """What ``summary/`` of a ``[sites]`` project tabulates and draws."""

    metrics: Annotated[list[str], Profile.USER] = Field(
        default_factory=lambda: ["nse"],
        description="Metrics of each case put in the summary tables, scored by the metric rule.",
        examples=[["nse", "kge"]],
    )
    rank_by: Annotated[str, Profile.USER] = Field(
        default="nse",
        description=(
            "Metric that ranks the cases of a site to pick its best one, by the direction of "
            "the metric. The nse is always a column of the tables; any other one must be in "
            "metrics. The order of metrics does not choose it."
        ),
        examples=["kge"],
    )
    parameters: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Parameters of each case put in the summary tables, calibrated or set.",
        examples=[["K", "Sy"]],
    )
    figures: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Cohort figures drawn under summary/figures/<figure>_<variable>.png: map, distribution."
        ),
        examples=[["map", "distribution"]],
    )
    variable: Annotated[Names, Profile.USER] = Field(
        default_factory=list,
        description="Metric or parameter, or a list of them, the cohort figures map and distribute.",
        examples=[["K", "nse"]],
    )
    best: Annotated[Literal["calibrated", "any"], Profile.USER] = Field(
        default="calibrated",
        description="Which case of a site the by-site table keeps as its best.",
        json_schema_extra={
            "value_docs": {
                "calibrated": "The best calibrated case of the site, scored in its "
                "calibration window or out of it (evaluated).",
                "any": "The best case of the site, calibrated or not.",
            }
        },
    )
    window: Annotated[list[SummaryWindow], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Windows the runs are scored on again, with the metrics above, into "
            "summary/scores.parquet. One [[sites.summary.window]] block each."
        ),
    )
    columns: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Extra columns read from the manifest.json of each run, as dotted paths "
            "without index (checks.budget_pct, metrics.nse)."
        ),
        examples=[["checks.budget_pct", "checks.converged"]],
    )

    @model_validator(mode="before")
    @classmethod
    def _variables_is_now_variable(cls, data: Any) -> Any:
        return _refuse_variables(data, "[sites.summary]")

    @field_validator("columns")
    @classmethod
    def _columns_are_dotted_paths(cls, value: list[str]) -> list[str]:
        for column in value:
            parse_dotted_path(column)
        return value

    @field_validator("metrics")
    @classmethod
    def _metrics_are_metrics_of_the_rule(cls, value: list[str]) -> list[str]:
        unknown = [name for name in value if name not in RUN_METRIC_NAMES]
        if unknown:
            raise ValueError(
                f"metrics {', '.join(map(repr, unknown))} are not metrics the run rule writes: "
                f"{', '.join(RUN_METRIC_NAMES)}."
            )
        return value

    @field_validator("rank_by")
    @classmethod
    def _rank_by_is_a_metric_of_the_rule(cls, value: str) -> str:
        if value not in RUN_METRIC_NAMES:
            raise ValueError(
                f"rank_by {value!r} is not a metric the run rule writes: {', '.join(RUN_METRIC_NAMES)}."
            )
        return value

    @model_validator(mode="after")
    def _rank_by_is_a_column(self) -> SitesSummaryConfig:
        if self.rank_by != "nse" and self.rank_by not in self.metrics:
            raise ValueError(
                f"rank_by {self.rank_by!r} is not a column of the summary: add it to metrics."
            )
        return self

    @model_validator(mode="after")
    def _month_windows_need_no_consecutive_metric(self) -> SitesSummaryConfig:
        cut = [w for w in self.window if w.months is not None]
        for name in self.metrics:
            if name in CONSECUTIVE_METRIC_NAMES and cut:
                raise ValueError(
                    f"metric {name!r} needs consecutive days, so it is refused on window "
                    f"{cut[0].name!r}, which sets months. Drop the metric or the months."
                )
        return self


class SitesExportRequest(HydroModelBase):
    """One export of a ``[sites]`` project, the vocabulary of ``[[export]]``."""

    table: Annotated[Literal["by_site", "by_case", "catalog"] | None, Profile.USER] = Field(
        default=None,
        description="Summary table to export. Write table or runs, not both.",
        json_schema_extra={
            "value_docs": {
                "by_site": "One row per site, its best case.",
                "by_case": "One row per case.",
                "catalog": "The site table the plan resolved.",
            }
        },
    )
    runs: Annotated[Literal["best"] | None, Profile.USER] = Field(
        default=None,
        description="Runs whose variables are exported: the best case of each site.",
    )
    variable: Annotated[Names, Profile.USER] = Field(
        default_factory=list,
        description="Variable, or a list of them, exported from each run, with runs = 'best'.",
        examples=[["discharge"]],
    )
    format: Annotated[str, Profile.USER] = Field(
        default="csv",
        description="File format of the export, csv unless another is named.",
        examples=["csv"],
    )
    file: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "For a table, the file name under summary/exports/ (unset: <table>.<format>); "
            "for runs = 'best', the folder of the series (unset: best)."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _variables_is_now_variable(cls, data: Any) -> Any:
        return _refuse_variables(data, "[[sites.export]]")

    @model_validator(mode="after")
    def _one_subject(self) -> SitesExportRequest:
        if (self.table is None) == (self.runs is None):
            raise ValueError("[[sites.export]] exports a table or runs: write one of the two.")
        if self.table is not None and self.variable:
            raise ValueError("[[sites.export]] variable goes with runs, not with a table.")
        return self


def _refuse_design_parameter(name: str, decl: CalibParameterDecl) -> None:
    where = f"[sites.design.parameters.{name}]"
    written = decl.model_fields_set
    if decl.resolve_target() is None:
        raise ValueError(
            f"{where}: write path = '<dotted.key>'. A name is not looked up in the catalogue "
            "here; 'hmp config targets' lists the keys."
        )
    parse_dotted_path(decl.resolve_target())
    if "sampling" not in written:
        raise ValueError(
            f"{where}: write sampling = 'uniform' or 'log_uniform'. There is no default, "
            "because a uniform draw on a quantity that spans decades is silently wrong."
        )
    if decl.sampling == "normal":
        raise ValueError(
            f"{where}: sampling 'normal' has no stratified design for a normal law cut at "
            "its bounds. Use 'uniform' or 'log_uniform'."
        )
    if decl.mode != "replace":
        raise ValueError(
            f"{where}: mode = {decl.mode!r} is not read. A drawn value is written as it is; "
            "write mode = 'replace' or leave it out."
        )
    for key in ("search_space", "units"):
        if key in written:
            raise ValueError(
                f"{where}: {key} is not read by a design, the sampling and the bounds "
                "decide the points. Remove it."
            )
    if decl.bounds is None:
        raise ValueError(f"{where}: write bounds = [low, high].")
    low, high = decl.bounds
    if not low < high:
        raise ValueError(f"{where}: bounds {decl.bounds} are not ordered, low < high.")
    if decl.sampling == "log_uniform" and low <= 0.0:
        raise ValueError(
            f"{where}: the lower bound of a log draw is strictly positive, got {low!r}."
        )


class SitesDesignConfig(HydroModelBase):
    """Points of an experiment plan, drawn when the plan is expanded."""

    method: Annotated[str, Profile.USER] = Field(
        default="sobol",
        description=(
            "Design that places the points in the box of the parameters. "
            + "; ".join(f"{name}: {sampler.summary}" for name, sampler in SAMPLERS.items())
            + ". Each point becomes a recipe: p0001, p0002 for sobol and grid, "
            "b1p0001 for the first point of the first lot of lhs."
        ),
        examples=["sobol"],
    )
    n: Annotated[int | list[int] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Number of points. Required for sobol and lhs, refused for grid whose size is "
            "the product of options.points_per_dim. For lhs a list gives the size of each "
            "lot: [60, 60] adds a second lot of 60 points to a first one already run, and "
            "the first lot does not move. A sobol size that is not a power of two warns, "
            "its balance holds for powers of two."
        ),
        examples=[64, [60, 60]],
        json_schema_extra=field_metadata(unit="-"),
    )
    seed: Annotated[int | None, Profile.USER] = Field(
        default=None,
        ge=0,
        description=(
            "Seed of the draw, required for sobol and lhs. Without it every expansion would "
            "draw other points, give other solution keys to the same case names and run "
            "everything again."
        ),
        examples=[1],
        json_schema_extra=field_metadata(unit="-"),
    )
    recipe: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Recipe of [sites.recipes] that the points replace, and whose file and set they "
            "start from. Required if the project declares several recipes. The other "
            "recipes run once per site as before."
        ),
        examples=["base"],
    )
    options: Annotated[dict[str, Any], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Options of the method: optimization (random-cd or lloyd) for lhs, "
            "points_per_dim for grid. The number of points is n, never an option."
        ),
        examples=[{"optimization": "random-cd"}],
    )
    parameters: Annotated[dict[str, CalibParameterDecl], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Parameters that move, by name. The name is the column of cases.csv. Each is a "
            "calibration parameter: path, bounds and sampling are written, and the case "
            "gets the drawn value as if the recipe table had written it."
        ),
    )

    @model_validator(mode="after")
    def _the_design_is_complete(self) -> SitesDesignConfig:
        if self.method not in SAMPLERS:
            raise ValueError(
                f"[sites.design] method {self.method!r} is not a design, known: "
                f"{', '.join(SAMPLERS)}."
            )
        sampler = SAMPLERS[self.method]
        if "n_samples" in self.options:
            raise ValueError("[sites.design] options.n_samples is written n, in the section.")
        try:
            options = sampler_options(self.method, self.options)
        except ValidationError as exc:
            for item in exc.errors():
                key = str(item["loc"][0]) if item["loc"] else ""
                owners = [
                    name
                    for name, other in SAMPLERS.items()
                    if key in other.options.model_fields and name != self.method
                ]
                if owners:
                    raise ValueError(
                        f"[sites.design] options.{key} belongs to {owners[0]}, not to "
                        f"{self.method}."
                    ) from None
            raise ValueError(f"[sites.design] options: {exc}") from exc
        sizes = [self.n] if isinstance(self.n, int) else list(self.n or [])
        if sampler.needs_n:
            if not sizes or any(size <= 0 for size in sizes):
                raise ValueError(
                    f"[sites.design] n is required and positive for {self.method}, got {self.n!r}."
                )
            if isinstance(self.n, list) and self.method != "lhs":
                raise ValueError(
                    f"[sites.design] n is a list of lots for lhs only; {self.method} grows "
                    "by writing a larger n."
                )
        elif self.n is not None:
            raise ValueError(
                f"[sites.design] {self.method} takes no n, its {grid_size(len(self.parameters), options)}"
                " points follow options.points_per_dim."
            )
        if sampler.needs_seed and self.seed is None:
            raise ValueError(
                f"[sites.design] seed is required for {self.method}: without it every expansion "
                "draws other points and runs everything again. Write seed = <integer>."
            )
        if not self.parameters:
            raise ValueError(
                "[sites.design] declares no parameter: write [sites.design.parameters.<name>]."
            )
        paths: dict[str, str] = {}
        for name, decl in self.parameters.items():
            _refuse_design_parameter(name, decl)
            path = decl.resolve_target()
            if path in paths:
                raise ValueError(
                    f"[sites.design.parameters] {paths[path]!r} and {name!r} both draw {path}."
                )
            paths[path] = name
        return self


class SitesConfig(HydroModelBase):
    """The catchments of a project and the recipes run on each of them."""

    table: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Site table, one row per catchment: CSV, Parquet or GeoPackage, relative "
            "to the project root. Its columns are free and reach the config through "
            "[sites.bind]. Unset, the plan reads data/sites/catalog.csv of the "
            "workspace, whose columns are fixed and need no bind."
        ),
        examples=["sites.csv"],
    )
    recipes_table: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Recipe table, one row per recipe: a CSV with a mandatory 'recipe' column; "
            "its other columns are bound by [sites.bind] like the site table. A "
            "column present in both tables is refused."
        ),
        examples=["recipes.csv"],
    )
    enabled: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Boolean column of the site table; unset, every row is a site of the plan.",
        examples=["enabled"],
    )
    include: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Site names the plan keeps; empty, every site.",
    )
    exclude: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Site names the plan leaves out.",
    )
    overrides: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Folder of per-site overlays, relative to the project root: "
            "<folder>/<site>.toml is applied to every case of that site when it exists."
        ),
        examples=["site_overrides/"],
    )
    recipes: Annotated[dict[str, RecipeDecl], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Recipes run on every site, by name: a TOML file, or an inline table "
            '{ file = "...", set = { "<dotted.key>" = value } }. The case of a site '
            "and a recipe is named <site>-<recipe>. A name is letters, digits and "
            "underscores. Unset, the file that declares [sites] is the only recipe."
        ),
        examples=[{"base": "project.toml", "calibration": "calibration.toml"}],
    )
    bind: Annotated[dict[str, str | list[str]], Profile.USER] = Field(
        default_factory=dict,
        description=(
            "Config keys filled from table columns: a quoted dotted path, the "
            "grammar of hmp run --set without index, mapped to a column, or to a "
            "list of columns for a list key. The cell is read by the type of the "
            "target field; an empty cell leaves the key unbound."
        ),
        examples=[{"geographic.catchment.x_outlet": "x_outlet"}],
    )
    design: Annotated[SitesDesignConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Experiment plan: points drawn in a box of parameters, each one a recipe of "
            "the base recipe. Unset, the recipes are the ones written."
        ),
    )
    run: Annotated[SitesRunConfig, Profile.USER] = Field(
        default_factory=SitesRunConfig,
        description="How the cases run side by side.",
    )
    summary: Annotated[SitesSummaryConfig, Profile.USER] = Field(
        default_factory=SitesSummaryConfig,
        description="What summary/ tabulates and draws.",
    )
    export: Annotated[list[SitesExportRequest], Profile.USER] = Field(
        default_factory=list,
        description="Exports of the project, one [[sites.export]] block each, under summary/exports/.",
    )

    @field_validator("recipes")
    @classmethod
    def _recipe_names(cls, value: dict[str, RecipeDecl]) -> dict[str, RecipeDecl]:
        for name in value:
            if split_stem_version(name)[1] is not None:
                raise ValueError(
                    f"recipe {name!r}: a name never ends in _v<N>, the suffix that "
                    "versions a run directory."
                )
            if "-" in name:
                raise ValueError(
                    f"recipe {name!r}: the dash separates the site from the recipe in a "
                    f"case id; write {name.replace('-', '_')!r}."
                )
            if not _RECIPE_NAME_RE.fullmatch(name):
                raise ValueError(f"recipe {name!r}: write letters, digits and underscores only.")
        return value

    @field_validator("bind", mode="before")
    @classmethod
    def _bind_keys_are_dotted_paths(cls, value: Any) -> Any:
        if isinstance(value, dict):
            _check_dotted_keys(value, where="[sites.bind]")
            for key, columns in value.items():
                names = [columns] if isinstance(columns, str) else columns
                if isinstance(names, list) and (
                    not names or any(not str(name).strip() for name in names)
                ):
                    raise ValueError(f"[sites.bind] {key!r}: name a column.")
        return value

    @model_validator(mode="after")
    def _include_and_exclude_disjoint(self) -> SitesConfig:
        both = sorted(set(self.include) & set(self.exclude))
        if both:
            raise ValueError(f"[sites] include and exclude both name {', '.join(both)}; keep one.")
        return self


def is_sites_project(raw: Mapping[str, Any]) -> bool:
    """Whether a resolved document belongs to a ``[sites]`` project."""
    return isinstance(raw.get("sites"), Mapping)


__all__ = [
    "PARALLEL_CEILING",
    "PREPARE_PARALLEL_CEILING",
    "RECIPE_NAME_PATTERN",
    "RecipeDecl",
    "RecipeSpec",
    "SitesConfig",
    "SitesDesignConfig",
    "SitesExportRequest",
    "SitesRunConfig",
    "SitesSummaryConfig",
    "SummaryWindow",
    "is_sites_project",
]
