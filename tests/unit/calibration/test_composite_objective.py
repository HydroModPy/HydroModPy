"""Placeholder for the composite (multi-block) objective test suite.

The old ``test_composite_objective.py`` exercised a
``CompositeObjective``/``CompositeObjectiveBlock`` pair that weighted
per-block RMSEs and plugged into the engine alongside a pure
``ObjectiveFunction``. The new architecture ships a single
:class:`~hydromodpy.calibration.objective.ScalarObjective`; a composite
multi-block objective has not been ported yet. The file is kept so the
intent is tracked in the regression inventory, but the test is skipped
until the composite objective lands.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Phase 4: composite multi-block objective not yet ported")
def test_composite_objective_weighted_blocks_placeholder() -> None:
    """Weighted multi-block composite objective (awaiting port from old API)."""
    raise AssertionError("placeholder — should never execute while skipped")
