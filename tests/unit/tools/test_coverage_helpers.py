from __future__ import annotations

import importlib.util
from pathlib import Path

from tools.ci.coverage_helpers import coverage_include_patterns, coverage_sources


def test_coverage_helpers_follow_pyproject_source_list() -> None:
    sources = coverage_sources()
    patterns = coverage_include_patterns()

    assert tuple(sources) == tuple(
        s.strip()
        for s in (
            "hydromodpy.core,hydromodpy.spatial,hydromodpy.physics,"
            "hydromodpy.data,hydromodpy.results,hydromodpy.simulation,"
            "hydromodpy.solver,hydromodpy.analysis"
        ).split(",")
    )
    assert patterns == [f"*/{s.replace('.', '/')}/*" for s in sources]


def test_run_pytest_with_coverage_module_imports_without_runtime_dependencies() -> None:
    module_path = Path("tools/ci/run_pytest_with_coverage.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "run_pytest_with_coverage_test_module",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.main)
