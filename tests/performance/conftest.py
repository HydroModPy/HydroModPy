"""Pytest configuration for the performance baseline tier.

Each module under ``tests/performance/`` sets ``pytestmark =
pytest.mark.performance`` so the suite is selectable via
``pytest -m performance``. Benchmarks are self-contained: they avoid
any dependency on hydromodpy runtime so the baseline survives across
the v2 refactor phases (P1 to P15).
"""

from __future__ import annotations
