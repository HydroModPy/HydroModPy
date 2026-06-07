from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

from tools.ci.coverage_helpers import coverage_include_patterns, coverage_sources


def test_coverage_helpers_follow_pyproject_source_list() -> None:
    sources = coverage_sources()
    patterns = coverage_include_patterns()
    pyproject_payload = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    expected_sources = tuple(pyproject_payload["tool"]["coverage"]["run"]["source"])

    assert tuple(sources) == expected_sources
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
