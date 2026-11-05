"""The basin of D is computed in one place, called from one place.

The catchment of a run is the basin of its descent D at the outlet: the budget
zone, the discharge a gauge sees, the drainage routing and the calibration all
read it. Each of them once resolved its own outlet and walked its own receivers
or its own polygon, and the supports drifted apart. The gate reads every module
under ``hydromodpy/``:

- ``descent_basin(`` is called once, by ``run_basin`` in ``catchment_basin``;
- ``Descent.basin(`` is called once, by ``descent_basin`` in ``spatial.drainage.descent``
  (a call whose first argument is a string literal is another ``basin``, the
  annual budget of the soil reservoir, and is ignored);
- ``resolve_outlet(`` is called by ``spatial.drainage.descent``, by the outlet pass of a
  watershed domain in ``flow_directions``, and by the stream criterion, which
  keeps its own flood on the top T (decision B4);
- the old per-consumer copies (``watershed_drainage_cell_mask``,
  ``_drainage_basin``) are gone.
"""

from __future__ import annotations

import ast
import pathlib
from collections import Counter

PKG_ROOT = pathlib.Path(__file__).resolve().parents[3] / "hydromodpy"

ALLOWED_CALLS: dict[str, dict[str, int]] = {
    "descent_basin": {"solver/modflow_common/catchment_basin.py": 1},
    "basin": {"spatial/drainage/descent.py": 1},
    "resolve_outlet": {
        "spatial/drainage/descent.py": 1,
        "solver/modflow_common/flow_directions.py": 1,
        # B4: the stream criterion keeps its own flood on T and its own outlet.
        "results/derive/stream/geometry.py": 1,
    },
}
"""Call sites of each name, by module relative to ``hydromodpy/``, and their count."""

REMOVED_NAMES = frozenset({"watershed_drainage_cell_mask", "_drainage_basin"})


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        if node.func.attr == "basin" and _first_argument_is_a_string(node):
            return None
        return node.func.attr
    return None


def _first_argument_is_a_string(node: ast.Call) -> bool:
    return (
        bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    )


def _scan() -> tuple[dict[str, Counter[str]], list[str]]:
    calls: dict[str, Counter[str]] = {name: Counter() for name in ALLOWED_CALLS}
    removed: list[str] = []
    for path in sorted(PKG_ROOT.rglob("*.py")):
        module = path.relative_to(PKG_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _called_name(node)
                if name in calls:
                    calls[name][module] += 1
            identifier = (
                node.name
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                else node.id
                if isinstance(node, ast.Name)
                else node.attr
                if isinstance(node, ast.Attribute)
                else node.name
                if isinstance(node, ast.alias)
                else None
            )
            if identifier in REMOVED_NAMES:
                removed.append(f"{module}:{getattr(node, 'lineno', '?')} {identifier}")
    return calls, removed


def test_the_basin_is_computed_and_called_from_one_place_each() -> None:
    calls, _ = _scan()

    for name, allowed in ALLOWED_CALLS.items():
        assert dict(calls[name]) == allowed, (
            f"{name}( is called from {dict(calls[name])}, the gate allows {allowed}: "
            "the basin of D has one computation, read by every consumer."
        )


def test_the_old_catchment_copies_are_gone() -> None:
    _, removed = _scan()

    assert not removed, f"old copies of the catchment rule are back: {removed}"
