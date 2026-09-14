"""Every metric the engine can compute must be selectable from a TOML.

``MetricKind`` re-encodes the keys of ``METRICS`` as a closed ``Literal``. Two
lists of the same thing drift, and this one had: the engine computed ten metrics
while the schema offered seven, so ``nse_delta``, ``nse_seasonal`` and
``reservoir`` ran correctly in Python and were refused by validation. The last
of those is the objective built for an impounded level, which is exactly the
subject of the projects that could not select it.

The lists stay two, because a ``Literal`` is what gives an operator the value
list in the generated reference page and the completion in an editor. What must
not stay is the drift, so this test is the seam that holds them equal.
"""

from __future__ import annotations

from typing import get_args

from hydromodpy.calibration.config import MetricKind
from hydromodpy.calibration.optim.objective import HIGHER_IS_BETTER, METRICS


def test_every_computable_metric_is_selectable() -> None:
    """The TOML vocabulary is exactly the registry's keys."""
    assert set(get_args(MetricKind)) == set(METRICS)


def test_every_metric_declares_its_direction() -> None:
    """A metric the engine cannot orient would be minimised the wrong way."""
    assert HIGHER_IS_BETTER <= set(METRICS)


def test_every_selectable_metric_is_documented() -> None:
    """The generated reference page explains each value it offers."""
    from hydromodpy.calibration.config import CalibObjectiveBlockDecl

    extra = CalibObjectiveBlockDecl.model_fields["metric"].json_schema_extra
    assert isinstance(extra, dict)
    value_docs = extra["value_docs"]
    assert isinstance(value_docs, dict)
    assert set(value_docs) == set(get_args(MetricKind))
