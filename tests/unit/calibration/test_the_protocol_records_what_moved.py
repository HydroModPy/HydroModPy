"""An option moved off the recipe has to show up where the number is read.

A protocol keeps its name when its engine is swapped, which is the point of
having options at all. What must not happen is a run reporting a published
method while running a different estimator, with nothing saying so. The check
output, the persisted record and the Methods prose are the three places a reader
looks, so all three are gated here.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.calibration.config import CalibrationProtocolDecl
from hydromodpy.calibration.protocols import (
    protocol_options_away_from_the_recipe,
    protocol_record,
)
from hydromodpy.calibration.protocols.boilerplate import methods_paragraph

NAME = "matching_hydrographic_network"


def _declared(**options: object) -> CalibrationProtocolDecl:
    return CalibrationProtocolDecl.model_validate({"name": NAME, **options})


def test_naming_the_protocol_alone_moves_nothing() -> None:
    assert protocol_options_away_from_the_recipe(NAME, _declared()) == ()


def test_restating_a_recipe_value_is_not_a_departure() -> None:
    # The reference file writes the published values out so it can be read beside
    # the script it replicates. Writing them must not read as changing them.
    declared = _declared(transient_metric="nse_log", transient_method="scipy_nelder_mead")
    assert protocol_options_away_from_the_recipe(NAME, declared) == ()


def test_a_swapped_estimator_and_engine_are_both_reported() -> None:
    declared = _declared(steady_metric="distance_mean", steady_method="scipy_nelder_mead")
    moved = {
        item["key"]: (item["here"], item["recipe"])
        for item in protocol_options_away_from_the_recipe(NAME, declared)
    }
    assert moved == {
        "steady_metric": ("distance_mean", "distance_gap"),
        "steady_method": ("scipy_nelder_mead", "bisection"),
    }


def test_the_pinned_version_is_not_an_option_that_moved() -> None:
    # A pin is a replayability guarantee, not a departure from the method.
    assert protocol_options_away_from_the_recipe(NAME, _declared(version="1.0")) == ()


def test_the_record_carries_the_departures_only_when_a_file_is_given() -> None:
    assert "options_away_from_the_recipe" not in protocol_record(NAME)
    record = protocol_record(NAME, _declared(steady_method="scipy_nelder_mead"))
    assert record["options_away_from_the_recipe"] == [
        {"key": "steady_method", "here": "scipy_nelder_mead", "recipe": "bisection"}
    ]


def test_the_methods_prose_says_the_engine_was_swapped() -> None:
    declared = _declared(steady_metric="distance_mean")
    prose = methods_paragraph(
        NAME,
        stages_that_ran=["steady_conductivity", "transient_storage"],
        options=protocol_options_away_from_the_recipe(NAME, declared),
    )
    assert "steady_metric = 'distance_mean' instead of 'distance_gap'" in prose


def test_the_prose_stays_silent_when_nothing_moved() -> None:
    prose = methods_paragraph(NAME, stages_that_ran=["steady_conductivity"])
    assert "moved off the recipe" not in prose


def test_the_descent_rule_is_declared_as_a_departure_from_the_paper() -> None:
    """The paper's own tool traces D8; HydroModPy descends D4 by default.

    That is a deviation from the publication the protocol cites, not a setting, so
    it belongs in the table that exists for exactly that and is printed before every
    run. The default has not been moved, because moving it changes every result
    obtained without it; what has been removed is the silence.
    """
    record = protocol_record(NAME)
    deviations = {item["key"]: item for item in record["deviations"]}
    assert "diagonal_neighbors" in deviations
    assert "D8" in deviations["diagonal_neighbors"]["paper"]
    assert "D4" in deviations["diagonal_neighbors"]["here"]
    # The why carries both measurements, so a reader does not have to find them.
    why = deviations["diagonal_neighbors"]["why"]
    assert "6.6 per cent" in why
    assert "64.631" in why


def test_the_value_a_file_actually_set_is_reported_even_when_it_is_false() -> None:
    # A boolean default is the case a "skip what is None" reader gets wrong, and it
    # is the one that matters here: false IS the departure.
    from hydromodpy.cli.commands.calibrate import _values_this_file_set

    cfg = SimpleNamespace(
        calibration=SimpleNamespace(
            outputs={"net": SimpleNamespace(diagonal_neighbors=False)}
        )
    )
    assert _values_this_file_set(cfg, ["diagonal_neighbors"]) == {"diagonal_neighbors": False}
