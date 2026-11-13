"""Label, unit, scale and ramp of a variable, from the registry and its quantity kind."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.units.kinds import QUANTITY_KINDS
from hydromodpy.display import variables
from hydromodpy.display.theme import get_theme
from hydromodpy.results.field_registry import FIELD_REGISTRY

THEME = get_theme("default")
FLOW = "recharge"
SIGNED = next(n for n, d in FIELD_REGISTRY.items() if d.quantity == "cell_flow" and d.sign is None)


def test_a_label_carries_the_display_unit_and_a_class_has_none():
    assert variables.label("head").startswith("Hydraulic head (")
    assert "mm" in variables.label(FLOW) and "(" not in variables.label("seepage_mask")


@pytest.mark.parametrize(
    ("name", "value", "area", "expected"),
    [
        ("hydraulic_conductivity", 1e-5, None, 1e-5),
        (FLOW, 1e-3, 100.0, 1e-3 / 100.0 * 86400 * 1000),
        (FLOW, 1e-3, 50.0, 1e-3 / 50.0 * 86400 * 1000),
    ],
)
def test_to_display_numbers_and_nan(name, value, area, expected):
    out = variables.to_display(name, np.array([value, np.nan]), area=area)
    assert out[0] == pytest.approx(expected) and np.isnan(out[1])
    with pytest.raises(ValueError, match="area"):
        variables.to_display(FLOW, np.array([1.0]))


@pytest.mark.parametrize(
    ("name", "family", "ramp"),
    [
        ("seepage_mask", "categorical", ""),
        (FLOW, "sequential", THEME.ramps["sequential"]),
        (SIGNED, "diverging", THEME.quantity_ramps["cell_flow"]),
        ("head", "sequential", THEME.quantity_ramps["head"]),
        ("hydraulic_conductivity", "sequential", THEME.quantity_ramps["conductivity"]),
    ],
)
def test_scale_and_ramp(name, family, ramp):
    assert variables.scale(name) == family and variables.ramp(name, THEME) == ramp


def test_a_diverging_quantity_on_a_sequential_scale_takes_the_scale_ramp(monkeypatch):
    monkeypatch.setattr(variables, "scale", lambda name: "sequential")
    assert variables.ramp(FLOW, THEME) == THEME.ramps["sequential"]


def test_class_colors_and_log():
    classes = len(FIELD_REGISTRY["seepage_mask"].classes)
    assert variables.class_colors("seepage_mask", THEME) == [
        THEME.roles["no_data"],
        *THEME.categorical[: classes - 1],
    ]
    assert variables.is_log("hydraulic_conductivity") and not variables.is_log("head")
    assert variables.is_log("head", "log") and not variables.is_log(
        "hydraulic_conductivity", "linear"
    )


def test_only_flows_and_mass_fluxes_add_up_over_a_zone():
    assert {k for k, kind in QUANTITY_KINDS.items() if kind.extensive} == {"cell_flow", "mass_flux"}


@pytest.mark.parametrize(
    ("scale", "log", "values", "norm", "vmin", "vmax"),
    [
        ("diverging", False, [-2.0, 1.0], "TwoSlopeNorm", -2.0, 2.0),
        ("sequential", True, [-1.0, 0.0, 5.0, 50.0], "LogNorm", 5.0, 50.0),
        ("sequential", False, [3.0, 3.0], "Normalize", 3.0, 4.0),
        ("sequential", False, [np.nan], "Normalize", 0.0, 1.0),
    ],
)
def test_the_colour_norm_covers_the_values_and_never_collapses(
    scale, log, values, norm, vmin, vmax
):
    found = variables.color_norm(scale, log, np.array(values))
    assert (type(found).__name__, found.vmin, found.vmax) == (norm, vmin, vmax)


@pytest.mark.parametrize(
    "name",
    ["seepage_mask", "simulated_active_network", "network_agreement", "package_cells", "idomain"],
)
def test_the_class_of_absence_is_neutral_and_the_others_take_the_palette(name):
    classes = variables.descriptor(name).classes
    colors = variables.class_colors(name, THEME)
    zero = [value for value, _ in classes].index(0)
    assert colors[zero] == THEME.roles["no_data"]
    assert [c for i, c in enumerate(colors) if i != zero] == list(
        THEME.categorical[: len(colors) - 1]
    )
