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
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.site import SITE_NAME_PATTERN
from hydromodpy.core.toml_io.paths import parse as parse_dotted_path
from hydromodpy.results.metric_rule import METRIC_NAMES

RECIPE_NAME_PATTERN = SITE_NAME_PATTERN
"""Grammar of a recipe name, the same as a site name."""

_RECIPE_NAME_RE = re.compile(RECIPE_NAME_PATTERN)
_VERSION_SUFFIX_RE = re.compile(r"\.v\d+$")

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
            "(16 runs held 14 GiB), and above 2 for a campaign that holds a calibration."
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
    variables: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Metrics or parameters the cohort figures map and distribute.",
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
    columns: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Extra columns read from the manifest.json of each run, as dotted paths "
            "without index (checks.budget_pct, metrics.nse)."
        ),
        examples=[["checks.budget_pct", "checks.converged"]],
    )

    @field_validator("columns")
    @classmethod
    def _columns_are_dotted_paths(cls, value: list[str]) -> list[str]:
        for column in value:
            parse_dotted_path(column)
        return value

    @field_validator("metrics")
    @classmethod
    def _metrics_are_metrics_of_the_rule(cls, value: list[str]) -> list[str]:
        unknown = [name for name in value if name not in METRIC_NAMES]
        if unknown:
            raise ValueError(
                f"metrics {', '.join(map(repr, unknown))} are not metrics the run rule writes: "
                f"{', '.join(METRIC_NAMES)}."
            )
        return value

    @field_validator("rank_by")
    @classmethod
    def _rank_by_is_a_metric_of_the_rule(cls, value: str) -> str:
        if value not in METRIC_NAMES:
            raise ValueError(
                f"rank_by {value!r} is not a metric the run rule writes: {', '.join(METRIC_NAMES)}."
            )
        return value

    @model_validator(mode="after")
    def _rank_by_is_a_column(self) -> SitesSummaryConfig:
        if self.rank_by != "nse" and self.rank_by not in self.metrics:
            raise ValueError(
                f"rank_by {self.rank_by!r} is not a column of the summary: add it to metrics."
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
    variables: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="Variables exported from each run, with runs = 'best'.",
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

    @model_validator(mode="after")
    def _one_subject(self) -> SitesExportRequest:
        if (self.table is None) == (self.runs is None):
            raise ValueError("[[sites.export]] exports a table or runs: write one of the two.")
        if self.table is not None and self.variables:
            raise ValueError("[[sites.export]] variables go with runs, not with a table.")
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
            if _VERSION_SUFFIX_RE.search(name):
                raise ValueError(
                    f"recipe {name!r}: a name never ends in .v<N>, the suffix that "
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


__all__ = [
    "PARALLEL_CEILING",
    "PREPARE_PARALLEL_CEILING",
    "RECIPE_NAME_PATTERN",
    "RecipeDecl",
    "RecipeSpec",
    "SitesConfig",
    "SitesExportRequest",
    "SitesRunConfig",
    "SitesSummaryConfig",
]
