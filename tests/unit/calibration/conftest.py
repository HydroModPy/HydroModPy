"""Skip legacy calibration tests superseded by the P09 calibration package.

The whole ``hydromodpy/analysis/calibration/`` tree is being retired in favor
of ``hydromodpy/calibration/`` (Optuna-first, TOML-simplified, lightweight).
Tests targeting the legacy engine, methods, cases, and devkit are skipped at
collection time. New tests live in ``tests/unit/test_calibration_*.py``.
"""

from __future__ import annotations

import pytest

collect_ignore_glob = [
    "test_calibration2_*.py",
    "test_composite_objective.py",
    "test_schemas.py",
]


def pytest_collection_modifyitems(config, items):
    skip_legacy = pytest.mark.skip(
        reason="legacy analysis/calibration superseded by P09 hydromodpy/calibration"
    )
    for item in items:
        path = str(item.fspath)
        if "tests/unit/calibration/" in path:
            item.add_marker(skip_legacy)
