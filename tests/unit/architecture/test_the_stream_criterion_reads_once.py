"""The stream criterion reads each of its inputs once, for the trial and the figure alike.

The calibration trial and the figure drawn from a sealed run once kept their own
copy of seven operations: the mapped cells, the free ends of the map, the share
of the minimal map outside the maximal one, the outlet and the outline, the routed
discharge, the depression flood and the mean recharge. The copies drifted apart,
so a figure could draw a partition other than the one behind the number it shows.
The gate reads every module under ``hydromodpy/`` and holds that:

- the old copies are gone (:data:`REMOVED`);
- each operation has one definition, in the module named by :data:`ONE_DEFINITION`;
- the mesh kernels that turn a map into cells are called, in ``calibration/`` and
  ``results/derive/stream_network/``, only by ``criterion_inputs.py`` (:data:`ONE_CALLER`);
- ``priority_flood`` is the one flood of the criterion and of the descent D.
"""

from __future__ import annotations

import ast
import pathlib
from collections import Counter
from functools import cache

import pytest

PKG_ROOT = pathlib.Path(__file__).resolve().parents[3] / "hydromodpy"

REMOVED: dict[str, str] = {
    "_share_outside": "",
    "routed_discharge": "",
    "_flood": "catchment/drainage",
    "_delineated_outlet_xy": "",
    "_delineated_catchment": "",
    "_watershed_catchment": "",
    "_mean_recharge_m_s": "",
    "_recharge_forcing_on_periods": "",
    "_budget_mean_recharge_m_s": "",
    "_stored_basin": "",
    "water_body_mask": "",
}
"""Each old copy, and the folder under ``hydromodpy/`` where it must not be defined.

An empty folder means the whole package. ``_flood`` is held in
``catchment/drainage`` only, because ``results/derive/stream_network/depressions.py``
keeps a flood of its own name that walks the depressions of a stored surface.
"""

ONE_DEFINITION: dict[str, str] = {
    "mapped_cells": "results/derive/stream_network/criterion_inputs.py",
    "map_heads": "results/derive/stream_network/criterion_inputs.py",
    "catchment_cells": "results/derive/stream_network/criterion_inputs.py",
    "basin_reference": "results/derive/stream_network/criterion_inputs.py",
    "criterion_recharge_of_run": "results/derive/stream_network/criterion_inputs.py",
    "share_outside": "catchment/stream_network/geometry.py",
    "scored_cells": "catchment/stream_network/geometry.py",
    "open_water_mask": "catchment/stream_network/geometry.py",
    "route_release_to_discharge": "catchment/drainage/routing.py",
    "priority_flood": "catchment/drainage/filling.py",
    "basin_of_group": "results/run/descent.py",
}
"""The one module that defines each operation at its top level, relative to ``hydromodpy/``.

A method of the same name, such as ``RunDescent.catchment_cells``, reads what the
run kept and computes nothing, so only module-level definitions count.
"""

CRITERION_PACKAGES = ("calibration", "catchment", "results")
"""Where a second definition of an operation would be a second criterion."""

ONE_CALLER = ("line_crossing_cell_mask", "vector_cell_mask", "network_head_candidates")
"""Mesh kernels that ``criterion_inputs.py`` alone calls for the criterion."""

CALLER_FOLDERS = ("calibration", "results/derive/stream_network")
CALLER = "results/derive/stream_network/criterion_inputs.py"

FLOOD_CALLERS = {"catchment/drainage/filling.py": 1, "catchment/drainage/descent.py": 1}
"""The calls of ``priority_flood``: the depression fill and the descent D."""


@cache
def _modules() -> dict[str, ast.Module]:
    return {
        path.relative_to(PKG_ROOT).as_posix(): ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(PKG_ROOT.rglob("*.py"))
    }


def _defined_names(tree: ast.Module, *, top_level: bool = False) -> list[str]:
    names: list[str] = []
    for node in tree.body if top_level else ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _called_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def _under(module: str, folder: str) -> bool:
    return not folder or module.startswith(folder.rstrip("/") + "/")


@pytest.mark.parametrize("name", sorted(REMOVED))
def test_an_old_copy_is_gone(name: str) -> None:
    folder = REMOVED[name]
    found = [
        module
        for module, tree in _modules().items()
        if _under(module, folder) and name in _defined_names(tree)
    ]
    assert found == [], f"{name} is defined again in {found}"


@pytest.mark.parametrize("name", sorted(ONE_DEFINITION))
def test_an_operation_has_one_definition(name: str) -> None:
    found = [
        module
        for module, tree in _modules().items()
        if module.split("/")[0] in CRITERION_PACKAGES
        and name in _defined_names(tree, top_level=True)
    ]
    assert found == [ONE_DEFINITION[name]], f"{name} is defined in {found}"


@pytest.mark.parametrize("name", ONE_CALLER)
def test_a_mesh_kernel_is_called_only_by_the_criterion_inputs(name: str) -> None:
    callers = sorted(
        module
        for module, tree in _modules().items()
        if any(_under(module, folder) for folder in CALLER_FOLDERS) and name in _called_names(tree)
    )
    assert callers == [CALLER], f"{name} is called in {callers}"


def test_priority_flood_is_the_one_flood() -> None:
    calls = Counter(
        {
            module: count
            for module, tree in _modules().items()
            if (count := _called_names(tree).count("priority_flood"))
        }
    )
    assert dict(calls) == FLOOD_CALLERS


def test_the_tables_name_modules_that_exist() -> None:
    modules = _modules()
    for module in {*ONE_DEFINITION.values(), CALLER, *FLOOD_CALLERS}:
        assert module in modules, f"{module} does not exist"
    for folder in {*REMOVED.values(), *CALLER_FOLDERS} - {""}:
        assert (PKG_ROOT / folder).is_dir(), f"{folder} does not exist"
