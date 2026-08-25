"""SFR is lake-independent by construction: no import edge to the LAK builder."""

from __future__ import annotations

import ast
from pathlib import Path

import hydromodpy.solver.modflow6.builders.sfr as sfr_module


def test_sfr_builder_never_imports_the_lake_builder() -> None:
    tree = ast.parse(Path(sfr_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("builders.lake" in name for name in imported), (
        "builders/sfr.py must stay standalone: the SFR-LAK coupling is MVR data, "
        "never an import edge to builders/lake.py."
    )
