"""Fixtures and configuration specific to the integration test tier.

The integration tier covers cross-module workflows that exercise more than
one HydroModPy subpackage (e.g. pipeline + catalog, planner + adapters).
Tests here remain short (< 10 s) and rely on shared fixtures from the
repository-root ``tests/conftest.py``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _integration_tier_marker(request: pytest.FixtureRequest) -> None:
    """Tag every collected integration-tier test with the ``integration`` marker.

    Tests already annotated with ``@pytest.mark.integration`` keep the
    marker; this fixture just ensures the whole directory is queryable
    via ``pytest -m integration``.
    """
    if "integration" not in request.node.keywords:
        request.node.add_marker(pytest.mark.integration)
