"""The immutable plan of a project: ``plan/<hash>/`` and ``plan/current``.

A plan is addressed by the fingerprint of what made it, written once, never rewritten in place,
so a launcher and an array job read the plan they were given. ``plan.json`` is :class:`Plan`.
``cases.csv`` holds one row per :class:`PlanCase`, the :data:`CASE_COLUMNS` first, then the
columns of the table of sites as text. ``<case_id>.toml`` is the resolved configuration of a
case. The directory is staged beside its final name and renamed into place.
"""

from __future__ import annotations

import filecmp
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.io.document_version import check_document
from hydromodpy.core.state.layout import PLAN_CURRENT_FILENAME, plan_dir_for
from hydromodpy.results.storage.contract import PLAN_CASES_FILENAME, PLAN_FILENAME
from hydromodpy.results.storage.json_io import read_json, write_json_atomic

PLAN_SCHEMA: Final[str] = "hydromodpy.plan.v2"

PLAN_REMEDY: Final[str] = (
    "A plan of HydroModPy 2.1 keeps its cases in cases.csv beside plan.json, where 2.0 "
    "wrote sites.parquet and cases.parquet. Write it again with hmp project plan <project>."
)

CASE_TOML_SUFFIX: Final[str] = ".toml"

CASE_COLUMNS: Final[tuple[str, ...]] = ("case_id", "site", "recipe", "config_hash", "config_path")


class PlanConflictError(HydroModPyError):
    """A plan with this hash exists and holds other content."""


class PlanCase(HydroModelBase):
    """One case of a plan: a site crossed with a recipe."""

    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+(-[A-Za-z0-9_]+)?$", description="site-recipe")
    site: str | None = Field(default=None, description="Site of the case")
    recipe: str | None = Field(default=None, description="Recipe of the case")
    config_hash: str = Field(description="Solution key of the resolved configuration")
    config_path: str = Field(description="Resolved TOML of the case, relative to the plan")


class Plan(HydroModelBase):
    """What a plan was made from, and what it holds."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PLAN_SCHEMA, alias="schema", description="Schema id")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{8,64}$", description="Fingerprint of the plan")
    hydromodpy_version: str = Field(description="Version that wrote the plan")
    created_at: datetime = Field(description="Instant the plan was written, UTC")
    fingerprints: dict[str, str] = Field(default_factory=dict, description="Digest of each input")
    n_cases: int = Field(ge=0, description="Number of cases")
    budget: dict[str, Any] = Field(default_factory=dict, description="Announced budget")

    @model_validator(mode="after")
    def _schema(self) -> Plan:
        if self.schema_ != PLAN_SCHEMA:
            raise ValueError(f"schema is {self.schema_!r}, this module reads {PLAN_SCHEMA!r}")
        return self


@dataclass(frozen=True, slots=True)
class StoredPlan:
    """A plan read back from ``plan/<hash>/``."""

    directory: Path
    plan: Plan
    cases: tuple[PlanCase, ...]
    sites: pd.DataFrame

    def case_toml(self, case_id: str) -> str:
        """Return the resolved configuration of one case."""
        case = next((c for c in self.cases if c.case_id == case_id), None)
        if case is None:
            raise KeyError(f"plan {self.plan.plan_hash} has no case {case_id!r}")
        return (self.directory / case.config_path).read_text(encoding="utf-8")


def plan_path(project_root: str | Path, plan_hash: str) -> Path:
    """Return ``<project>/plan/<hash>``."""
    return plan_dir_for(Path(project_root)) / plan_hash


def current_plan_hash(project_root: str | Path) -> str | None:
    """Return the hash ``plan/current`` names, or ``None`` without a plan."""
    pointer = plan_dir_for(Path(project_root)) / PLAN_CURRENT_FILENAME
    if not pointer.is_file():
        return None
    return pointer.read_text(encoding="utf-8").strip()


def write_plan(
    project_root: str | Path,
    plan: Plan,
    sites: pd.DataFrame,
    cases: list[PlanCase],
    case_tomls: Mapping[str, str],
) -> Path:
    """Write ``plan/<hash>/`` once, point ``plan/current`` at it, return the directory.

    *sites* is one row of text per site with a ``site`` column. Other content under an
    existing hash raises :class:`PlanConflictError` and leaves the plan as it was.
    """
    _check_cases(plan, cases, case_tomls, sites)
    final = plan_path(project_root, plan.plan_hash)
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = final.parent / f".staging-{plan.plan_hash}-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        write_json_atomic(staging / PLAN_FILENAME, plan.model_dump(mode="json", by_alias=True))
        _write_cases(staging / PLAN_CASES_FILENAME, cases, sites)
        for case in cases:
            (staging / case.config_path).write_text(case_tomls[case.case_id], encoding="utf-8")
        if final.exists():
            if not _same_content(staging, final):
                raise PlanConflictError(
                    f"plan {plan.plan_hash} exists under {final} with other content; a plan "
                    "is immutable, so this one was not written"
                )
        else:
            staging.rename(final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    with staged_path(final.parent / PLAN_CURRENT_FILENAME) as pointer:
        pointer.write_text(plan.plan_hash + "\n", encoding="utf-8")
    return final


def read_plan(project_root: str | Path, plan_hash: str | None = None) -> StoredPlan:
    """Read ``plan/<hash>/`` or the current plan; a plan of 2.0 is refused with its remedy."""
    chosen = plan_hash if plan_hash is not None else current_plan_hash(project_root)
    if chosen is None:
        raise FileNotFoundError(f"no plan under {plan_dir_for(Path(project_root))}")
    directory = plan_path(project_root, chosen)
    document = directory / PLAN_FILENAME
    payload = check_document(
        read_json(document), PLAN_SCHEMA, document=document, remedy=PLAN_REMEDY
    )
    table = pd.read_csv(directory / PLAN_CASES_FILENAME, dtype=str, keep_default_na=False)
    records = table[list(CASE_COLUMNS)].to_dict("records")
    rows = [{**r, "site": r["site"] or None, "recipe": r["recipe"] or None} for r in records]
    sites = table.drop(columns=[c for c in CASE_COLUMNS if c != "site"]).drop_duplicates("site")
    return StoredPlan(
        directory,
        read_stored(Plan, payload),
        tuple(read_stored(PlanCase, row) for row in rows),
        sites.reset_index(drop=True),
    )


def _check_cases(
    plan: Plan, cases: list[PlanCase], case_tomls: Mapping[str, str], sites: pd.DataFrame
) -> None:
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)) or len(cases) != plan.n_cases:
        raise ValueError(f"plan.n_cases is {plan.n_cases}, {len(cases)} cases given: {sorted(ids)}")
    missing, extra = sorted(set(ids) - set(case_tomls)), sorted(set(case_tomls) - set(ids))
    if missing or extra:
        raise ValueError(f"case TOMLs do not match the cases: missing {missing}, extra {extra}")
    for case in cases:
        if case.config_path != (expected := f"{case.case_id}{CASE_TOML_SUFFIX}"):
            raise ValueError(f"case {case.case_id} names {case.config_path!r}, not {expected!r}")
    taken = sorted(set(sites.columns) & set(CASE_COLUMNS) - {"site"})
    if taken or "site" not in sites.columns:
        raise ValueError(
            f"the sites table needs a site column and none of {CASE_COLUMNS[2:]}: {taken}"
        )


def _write_cases(target: Path, cases: list[PlanCase], sites: pd.DataFrame) -> None:
    """Write one row per case: the fixed columns, then the cells of its site."""
    rows = [{name: getattr(case, name) or "" for name in CASE_COLUMNS} for case in cases]
    frame = pd.DataFrame(rows, columns=list(CASE_COLUMNS), dtype=str)
    frame = frame.merge(sites.drop_duplicates("site"), on="site", how="left").fillna("")
    frame.to_csv(target, index=False, lineterminator="\n")


def _same_content(left: Path, right: Path) -> bool:
    """Return whether two plan directories hold the same bytes under the same names."""
    names = {p.name for p in left.iterdir()}
    return names == {p.name for p in right.iterdir()} and all(
        filecmp.cmp(left / name, right / name, shallow=False) for name in names
    )
