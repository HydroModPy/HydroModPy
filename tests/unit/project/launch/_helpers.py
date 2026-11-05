"""A planned ``[sites]`` project the SLURM tests write their job from."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from hydromodpy.results.plan_store import Plan, PlanCase, StoredPlan, read_plan, write_plan

STAMP = "20261020-143000"
PLAN_HASH = "0123abcd0123abcd"
PROJECT_TOML = """\
[sites]
table = "sites.csv"

[sites.recipes]
base = "base.toml"

[sites.run]
threads_per_case = {threads}
prepare_parallel = {prepare}
"""


def planned_project(
    root: Path,
    *,
    cases: tuple[str, ...] = ("J001-base", "J002-base", "J003-calage"),
    calibration_parallel: dict[str, int] | None = None,
    threads: int = 2,
    prepare: int = 3,
) -> StoredPlan:
    """Write a ``[sites]`` project and its current plan; return the plan."""
    root.mkdir(parents=True, exist_ok=True)
    project_toml = root / "project.toml"
    project_toml.write_text(PROJECT_TOML.format(threads=threads, prepare=prepare))
    parallel = calibration_parallel or {}
    tomls: dict[str, str] = {}
    for case_id in cases:
        site = case_id.split("-")[0]
        text = f'[site]\nname = "{site}"\n'
        if case_id in parallel:
            text += f"\n[calibration]\nparallel = {parallel[case_id]}\n"
        tomls[case_id] = text
    plan = Plan(
        plan_hash=PLAN_HASH,
        hydromodpy_version="test",
        created_at=datetime(2026, 10, 20, 14, 0, tzinfo=UTC),
        fingerprints={"project.toml": hashlib.sha256(project_toml.read_bytes()).hexdigest()},
        n_cases=len(cases),
    )
    plan_cases = [
        PlanCase(
            case_id=case_id,
            site=case_id.split("-")[0],
            recipe=case_id.split("-")[1],
            config_hash=f"hash-{case_id}",
            config_path=f"{case_id}.toml",
        )
        for case_id in cases
    ]
    sites = pa.table({"site": sorted({c.split("-")[0] for c in cases})})
    write_plan(root, plan, sites, plan_cases, tomls)
    return read_plan(root)
