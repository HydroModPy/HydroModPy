"""A gauge declared at a coordinate has to be scored on the gauge's quantity.

The point support used to coerce every declared variable to ``head``, which made
the commonest calibration target in the project, the discharge at a gauge,
unreachable through the weighted-block route: a block naming `observes` on a
point output was scored on a water level instead, and nothing said so. The
translation is one function, so the fix is gated here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibOutputCell, CalibOutputPoint
from hydromodpy.calibration.metrics.solver_extract import observable_request_for_output

CELL = (0, 12)


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(
        "hydromodpy.calibration.metrics.solver_extract.find_cell_at_point",
        lambda _ctx, _x, _y: CELL,
    )
    return SimpleNamespace()


def _point(variable: str) -> CalibOutputPoint:
    return CalibOutputPoint.model_validate(
        {"variable": variable, "support": "point", "x": 1.0, "y": 2.0}
    )


def test_a_head_target_is_unchanged(ctx) -> None:
    request = observable_request_for_output("piezo", _point("head"), ctx)
    assert (request.name, request.support, request.cell) == ("head", "cell", CELL)


def test_a_discharge_target_asks_for_the_discharge(ctx) -> None:
    request = observable_request_for_output("gauge", _point("discharge"), ctx)
    assert (request.name, request.support, request.cell) == ("discharge", "cell", CELL)


def test_the_request_is_the_one_the_single_metric_route_already_builds(ctx) -> None:
    # `composite.py` resolves a station to its cell and asks for
    # ObservableRequest(name="discharge", support="cell", cell=...). A block
    # scoring the same gauge has to ask the solver the same question, or the two
    # routes are not comparable.
    request = observable_request_for_output("gauge", _point("discharge"), ctx)
    assert request.name == "discharge"
    assert request.support == "cell"


def test_a_point_with_no_coordinates_is_refused_at_declaration() -> None:
    with pytest.raises(ValueError, match="requires both 'x' and 'y'"):
        CalibOutputPoint.model_validate({"variable": "head", "support": "point"})


def test_a_point_output_s_diagonal_neighbors_reaches_the_request(ctx) -> None:
    # The D4/D8 knob only helps if it survives the translation to a solver
    # request; declared and dropped here is indistinguishable from absent.
    declaration = CalibOutputPoint.model_validate(
        {
            "variable": "discharge",
            "support": "point",
            "x": 1.0,
            "y": 2.0,
            "diagonal_neighbors": True,
        }
    )
    request = observable_request_for_output("gauge", declaration, ctx)
    assert request.diagonal_neighbors is True


def test_a_cell_output_s_diagonal_neighbors_reaches_the_request() -> None:
    declaration = CalibOutputCell.model_validate(
        {
            "variable": "discharge",
            "support": "cell",
            "row": 3,
            "col": 7,
            "diagonal_neighbors": True,
        }
    )
    request = observable_request_for_output("gauge", declaration, SimpleNamespace())
    assert request.diagonal_neighbors is True


def test_diagonal_neighbors_defaults_to_false(ctx) -> None:
    request = observable_request_for_output("gauge", _point("discharge"), ctx)
    assert request.diagonal_neighbors is False
