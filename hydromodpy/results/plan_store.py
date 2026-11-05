"""The immutable plan of a project: ``plan/<hash>/`` and ``plan/current``.

Why
---
A plan is what a launcher and an array job read to know which cases exist
and what configuration each one runs. If ``hmp run`` rewrote it on every
start, a ``--only failed`` launched while an array waits in a queue would
change what task N is about to read. So a plan is addressed by the
fingerprint of what made it, written once, never rewritten in place, and
``plan/current`` names the one the project is on. Two plans with the same
hash are the same plan: writing it again is a no-op; writing different
content under an existing hash is refused.

Format
------
``plan/<hash>/plan.json`` is :class:`Plan`; ``sites.parquet`` the resolved
site table as the caller built it; ``cases.parquet`` one row per
:class:`PlanCase` (no ``status`` column: the state of a case is read from
its outcome); ``<case_id>.toml`` the resolved configuration of each case,
replayable alone from any directory. The directory is staged beside its
final name and renamed into place, so a reader sees a whole plan or none.
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

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.state.layout import PLAN_CURRENT_FILENAME, plan_dir_for
from hydromodpy.results.storage.contract import (
    PLAN_CASES_FILENAME,
    PLAN_FILENAME,
    PLAN_SITES_FILENAME,
)
from hydromodpy.results.storage.json_io import read_sealed_json, write_json_atomic
from hydromodpy.results.storage.parquet_io import write_table_atomic

PLAN_SCHEMA: Final[str] = "hydromodpy.plan.v1"
"""Schema id of ``plan.json``."""

PLAN_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.plan.v1", current=PLAN_SCHEMA
)
"""Versions of ``plan.json`` this code reads."""

CASE_TOML_SUFFIX: Final[str] = ".toml"
"""Suffix of the resolved configuration of one case inside a plan."""

PLAN_CASES_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("case_id", pa.string(), nullable=False),
        pa.field("site", pa.string(), nullable=True),
        pa.field("recipe", pa.string(), nullable=True),
        pa.field("config_hash", pa.string(), nullable=False),
        pa.field("config_path", pa.string(), nullable=False),
    ]
)
"""Columns of ``cases.parquet``. No status: the state of a case is its outcome."""


class PlanConflictError(HydroModPyError):
    """A plan with this hash exists and holds other content."""


class PlanCase(HydroModelBase):
    """One case of a plan: a site crossed with a recipe."""

    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+(-[A-Za-z0-9_]+)?$", description="site-recipe")
    site: str | None = Field(default=None, description="Site of the case")
    recipe: str | None = Field(default=None, description="Recipe of the case")
    config_hash: str = Field(description="Identity hash of the resolved configuration")
    config_path: str = Field(
        description="Resolved TOML of the case, relative to the plan directory"
    )


class Plan(HydroModelBase):
    """What a plan was made from, and what it holds."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PLAN_SCHEMA, alias="schema", description="Schema id")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{8,64}$", description="Fingerprint of the plan")
    hydromodpy_version: str = Field(description="Version that wrote the plan")
    created_at: datetime = Field(description="Instant the plan was written, UTC")
    fingerprints: dict[str, str] = Field(
        default_factory=dict,
        description="Digest of each input of the plan: project.toml, recipes...",
    )
    n_cases: int = Field(ge=0, description="Number of cases")
    budget: dict[str, Any] = Field(
        default_factory=dict, description="Announced budget: solves, peak memory, scratch"
    )

    @model_validator(mode="after")
    def _schema(self) -> Plan:
        if not PLAN_VERSIONS.holds(self.schema_):
            raise ValueError(f"schema is {self.schema_!r}, this module reads {PLAN_SCHEMA!r}")
        return self


@dataclass(frozen=True, slots=True)
class StoredPlan:
    """A plan read back from ``plan/<hash>/``."""

    directory: Path
    plan: Plan
    sites: pa.Table
    cases: tuple[PlanCase, ...]

    def case_toml(self, case_id: str) -> str:
        """Return the resolved configuration of one case."""
        case = next((c for c in self.cases if c.case_id == case_id), None)
        if case is None:
            raise KeyError(f"plan {self.plan.plan_hash} has no case {case_id!r}")
        return (self.directory / case.config_path).read_text(encoding="utf-8")


def plan_path(project_root: str | Path, plan_hash: str) -> Path:
    """Return ``<project>/plan/<hash>``."""
    return plan_dir_for(Path(project_root)) / plan_hash


def current_plan_path(project_root: str | Path) -> Path:
    """Return ``<project>/plan/current``."""
    return plan_dir_for(Path(project_root)) / PLAN_CURRENT_FILENAME


def current_plan_hash(project_root: str | Path) -> str | None:
    """Return the hash ``plan/current`` names, or ``None`` without a plan."""
    pointer = current_plan_path(project_root)
    if not pointer.is_file():
        return None
    return pointer.read_text(encoding="utf-8").strip()


def write_plan(
    project_root: str | Path,
    plan: Plan,
    sites: pa.Table,
    cases: list[PlanCase],
    case_tomls: Mapping[str, str],
) -> Path:
    """Write ``plan/<hash>/`` once, point ``plan/current`` at it, return the directory.

    The same plan written twice is a no-op. Different content under an
    existing hash raises :class:`PlanConflictError`, and the existing plan is
    left as it was.
    """
    _check_cases(plan, cases, case_tomls)
    final = plan_path(project_root, plan.plan_hash)
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = final.parent / f".staging-{plan.plan_hash}-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        write_json_atomic(staging / PLAN_FILENAME, plan.model_dump(mode="json", by_alias=True))
        write_table_atomic(sites, staging / PLAN_SITES_FILENAME)
        write_table_atomic(_cases_table(cases), staging / PLAN_CASES_FILENAME)
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
    with staged_path(current_plan_path(project_root)) as pointer:
        pointer.write_text(plan.plan_hash + "\n", encoding="utf-8")
    return final


def read_plan(project_root: str | Path, plan_hash: str | None = None) -> StoredPlan:
    """Read ``plan/<hash>/``, or the current plan when *plan_hash* is ``None``."""
    chosen = plan_hash if plan_hash is not None else current_plan_hash(project_root)
    if chosen is None:
        raise FileNotFoundError(f"no plan under {plan_dir_for(Path(project_root))}")
    directory = plan_path(project_root, chosen)
    plan = read_stored(Plan, read_sealed_json(directory / PLAN_FILENAME, PLAN_VERSIONS))
    sites = pq.read_table(directory / PLAN_SITES_FILENAME)
    cases = tuple(
        read_stored(PlanCase, row)
        for row in pq.read_table(directory / PLAN_CASES_FILENAME).to_pylist()
    )
    return StoredPlan(directory=directory, plan=plan, sites=sites, cases=cases)


def _check_cases(plan: Plan, cases: list[PlanCase], case_tomls: Mapping[str, str]) -> None:
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"a plan names each case once: {sorted(ids)}")
    if len(cases) != plan.n_cases:
        raise ValueError(f"plan.n_cases is {plan.n_cases}, {len(cases)} cases given")
    missing = sorted(set(ids) - set(case_tomls))
    extra = sorted(set(case_tomls) - set(ids))
    if missing or extra:
        raise ValueError(f"case TOMLs do not match the cases: missing {missing}, extra {extra}")
    for case in cases:
        expected = f"{case.case_id}{CASE_TOML_SUFFIX}"
        if case.config_path != expected:
            raise ValueError(f"case {case.case_id} names {case.config_path!r}, not {expected!r}")


def _cases_table(cases: list[PlanCase]) -> pa.Table:
    return pa.Table.from_pylist([case.model_dump() for case in cases], schema=PLAN_CASES_SCHEMA)


def _same_content(left: Path, right: Path) -> bool:
    """Return whether two plan directories hold the same documents.

    The Parquet files are compared by content, not by bytes: the writer
    stamps nothing in them, but the comparison should not depend on it.
    """
    names = {p.name for p in left.iterdir()}
    if names != {p.name for p in right.iterdir()}:
        return False
    for name in names:
        if name.endswith(".parquet"):
            if not pq.read_table(left / name).equals(pq.read_table(right / name)):
                return False
        elif not filecmp.cmp(left / name, right / name, shallow=False):
            return False
    return True


__all__ = [
    "CASE_TOML_SUFFIX",
    "PLAN_CASES_SCHEMA",
    "PLAN_SCHEMA",
    "PLAN_VERSIONS",
    "Plan",
    "PlanCase",
    "PlanConflictError",
    "StoredPlan",
    "current_plan_hash",
    "current_plan_path",
    "plan_path",
    "read_plan",
    "write_plan",
]
