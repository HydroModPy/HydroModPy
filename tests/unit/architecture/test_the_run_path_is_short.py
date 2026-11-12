"""A flow run plays fewer than forty files of hydromodpy/, listed one by one in run_path.toml.

The list holds one table per group of files and one variant per solver chain.
Every path exists, no path is written twice, a MODFLOW 6 or MODFLOW-NWT flow run
stays under forty files, and the chained transport run is the MODFLOW 6 run plus
the transport group and nothing else.
"""

from __future__ import annotations

import copy
import pathlib
import tomllib
from collections.abc import Callable
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = ROOT / "hydromodpy"
RUN_PATH = tomllib.loads((pathlib.Path(__file__).with_name("run_path.toml")).read_text("utf-8"))

FLOW_BOUND = 40
FLOW_VARIANTS = ("mf6", "modflow_nwt")
VARIANTS = (*FLOW_VARIANTS, "gwt")
TRANSPORT_GROUP = "transport_modflow6"


def variant_files(table: dict[str, Any], variant: str) -> list[str]:
    """Return the paths of the groups a variant plays, in order, skipping unknown groups."""
    groups = table.get("variants", {}).get(variant, [])
    return [path for group in groups if group in table for path in table[group]["files"]]


def check_run_path(table: dict[str, Any], root: pathlib.Path = PKG_ROOT) -> list[str]:
    """Return one message per rule the table breaks, each naming the file or group."""
    faults: list[str] = []
    variants = table.get("variants", {})
    groups = [name for name in table if name != "variants"]
    for variant in VARIANTS:
        if variant not in variants:
            faults.append(f"variant {variant} is missing: the file must list {VARIANTS}")
    for variant, names in variants.items():
        faults.extend(
            f"group {name} of variant {variant} has no table: a variant names only defined groups"
            for name in names
            if name not in groups
        )
    used = {name for names in variants.values() for name in names}
    faults.extend(
        f"group {name} is in no variant: a group that no run plays is dead"
        for name in groups
        if name not in used
    )
    owner: dict[str, str] = {}
    for name in groups:
        for path in table[name]["files"]:
            if path in owner:
                faults.append(
                    f"{path} is written twice, in {owner[path]} and {name}: one line per file"
                )
            owner.setdefault(path, name)
            if not (root / path).is_file():
                faults.append(f"{path} of group {name} does not exist under hydromodpy/")
    for variant in FLOW_VARIANTS:
        count = len(variant_files(table, variant))
        if variant in variants and count >= FLOW_BOUND:
            faults.append(
                f"variant {variant} holds {count} files: a flow run stays under {FLOW_BOUND}"
            )
    if {"mf6", "gwt"} <= variants.keys() and TRANSPORT_GROUP in table:
        extra = set(variant_files(table, "gwt")) - set(variant_files(table, "mf6"))
        if extra != set(table[TRANSPORT_GROUP]["files"]):
            faults.append(
                f"variant gwt adds {sorted(extra)} to mf6: it adds the files of {TRANSPORT_GROUP} only"
            )
    return faults


def _to_the_bound(table: dict[str, Any]) -> None:
    """Push the flow group to the bound with files of ``core/`` that exist."""
    listed = {
        path for name, group in table.items() if name != "variants" for path in group["files"]
    }
    spare = [
        path
        for path in (
            p.relative_to(PKG_ROOT).as_posix() for p in sorted((PKG_ROOT / "core").glob("*.py"))
        )
        if path not in listed
    ]
    table["flow"]["files"].extend(spare[: FLOW_BOUND - len(variant_files(table, "mf6"))])


def _absent(table: dict[str, Any]) -> None:
    table["flow"]["files"].append("cli/commands/nowhere.py")


def _doubled(table: dict[str, Any]) -> None:
    table["modflow6"]["files"].append("cli/commands/run.py")


def _unknown(table: dict[str, Any]) -> None:
    table["variants"]["mf6"].append("modflow7")


def _extra_in_gwt(table: dict[str, Any]) -> None:
    table["variants"]["gwt"] = ["flow", "modflow6", "modflow_nwt", TRANSPORT_GROUP]


def _no_variant(table: dict[str, Any]) -> None:
    del table["variants"]["modflow_nwt"]


REFUSALS = [
    pytest.param(_absent, ["cli/commands/nowhere.py", "does not exist"], id="a path that is gone"),
    pytest.param(_doubled, ["cli/commands/run.py", "written twice"], id="a path written twice"),
    pytest.param(_to_the_bound, ["variant mf6", "40 files", "under 40"], id="a flow run at forty"),
    pytest.param(_unknown, ["modflow7", "has no table"], id="a group nobody defined"),
    pytest.param(
        _extra_in_gwt, ["variant gwt", TRANSPORT_GROUP], id="a gwt run with more than transport"
    ),
    pytest.param(_no_variant, ["variant modflow_nwt", "missing"], id="a variant that is missing"),
]


def test_the_run_path_of_the_tree_breaks_no_rule() -> None:
    assert check_run_path(RUN_PATH) == []


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_file_of_a_variant_exists(variant: str) -> None:
    paths = variant_files(RUN_PATH, variant)
    assert paths
    missing = [path for path in paths if not (PKG_ROOT / path).is_file()]
    assert not missing, f"{variant} lists files that do not exist: {missing}"


@pytest.mark.parametrize("variant", FLOW_VARIANTS)
def test_a_flow_run_plays_fewer_than_forty_files(variant: str) -> None:
    assert len(variant_files(RUN_PATH, variant)) < FLOW_BOUND


def test_the_chained_transport_run_is_the_mf6_run_plus_its_transport_group() -> None:
    mf6 = variant_files(RUN_PATH, "mf6")
    gwt = variant_files(RUN_PATH, "gwt")
    assert gwt[: len(mf6)] == mf6
    assert gwt[len(mf6) :] == RUN_PATH[TRANSPORT_GROUP]["files"]


@pytest.mark.parametrize(("change", "fragments"), REFUSALS)
def test_a_table_that_breaks_a_rule_is_refused_with_the_file_and_the_rule(
    change: Callable[[dict[str, Any]], None], fragments: list[str]
) -> None:
    table = copy.deepcopy(RUN_PATH)
    change(table)
    faults = check_run_path(table)
    assert faults, "the broken table was accepted"
    assert any(all(fragment in fault for fragment in fragments) for fault in faults), faults
