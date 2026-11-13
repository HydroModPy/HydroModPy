"""The examples of the page "Add a figure", each played on the small stored run.

A row the page shows sits inside a dict literal here, and the dict is merged into the real
table for the length of the test, so the page shows the lines that ran.
"""

from __future__ import annotations

import tomllib

import numpy as np
import pytest

from hydromodpy.core.budget import terms
from hydromodpy.core.exceptions import CommandUsageError
from hydromodpy.core.units import kinds
from hydromodpy.core.units.kinds import QuantityKind
from hydromodpy.display import static
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.request import FigureRequest, expand
from hydromodpy.display.subject import read_series
from hydromodpy.results import field_registry as registry
from hydromodpy.results.derive.stream_network import cell_fields
from hydromodpy.results.derive.stream_network.cell_fields import RebuiltField, rebuilt_rows
from hydromodpy.results.field_registry import SHAPE_TIME_FACE, ColumnDescriptor, _rebuilt
from hydromodpy.results.run.view import Run
from tests.unit.results import test_field_registry_kinds as gate


def _merge(monkeypatch, table, rows):
    for key, row in rows.items():
        monkeypatch.setitem(table, key, row)


def test_case_1_a_variable_by_its_name(stored_run):
    # example: variable
    figure = stored_run.figure("head", time="last", layer=0, title="Head at the end")
    figure.savefig("head.png")
    # end of example
    assert figure.axes[0].collections and figure._suptitle.get_text() == "Head at the end"
    with pytest.raises(CommandUsageError, match=r"Unknown figure 'hed'\. Did you mean head\?"):
        stored_run.figure("hed")


def test_case_2_a_composition_of_panels(stored_run, monkeypatch, tmp_path):
    # example: toml
    toml = """
    [display.presets.head_and_flow]
    [[display.presets.head_and_flow.panels]]
    variable = "head"
    time = "last"
    holes = ["time"]
    [[display.presets.head_and_flow.panels]]
    variable = "discharge"
    holes = ["station"]
    """
    # end of example
    with pytest.raises(CommandUsageError, match=r"Unknown figure 'head_and_flow'\. Did you mean"):
        stored_run.figure("head_and_flow")
    # The run was sealed before the preset was written: a run made after it carries the table.
    sealed = tomllib.loads(toml)
    monkeypatch.setattr(Run, "config_snapshot", property(lambda self: sealed))
    # example: preset
    figure = stored_run.figure("head_and_flow", time="first")
    # end of example
    # example: panels
    panels = [{"variable": "head", "time": "last"}, {"variable": "discharge"}]
    same = stored_run.figure(request={"name": "head_and_flow", "panels": panels})
    # end of example
    assert len(figure.axes) == len(same.axes) == 3
    with pytest.raises(ValueError, match=r"Unknown preset 'head_and_flo'\. .*Known presets: "):
        stored_run.figure(request={"preset": "head_and_flo"})


def test_case_3_a_column_of_a_table(stored_run, monkeypatch):
    name = "simulation.budget_pct"
    request = {"type": "table", "variable": [name]}
    with pytest.raises(ValueError, match=r"has no row in COLUMN_REGISTRY \(results/field_registry"):
        stored_run.figure_data(request=request)
    written = {
        # example: column
        "simulation.budget_pct": ColumnDescriptor("percent", "Budget error"),
        # end of example
    }
    _merge(monkeypatch, registry.COLUMN_REGISTRY, written)
    gate.test_column_row_names_a_schema_column(name)
    label = stored_run.figure_data(request=request)["a"]["label"].iloc[0]
    assert label.startswith("Budget error")


def test_case_3_a_cell_field_rebuilt_from_a_run(stored_run, monkeypatch):
    name = "recharge_anomaly"
    descriptor = {
        # example: descriptor
        "recharge_anomaly": _rebuilt(
            "recharge_anomaly",
            "Recharge anomaly",
            "cell_flow",
            "m3 s-1",
            SHAPE_TIME_FACE,
            "Recharge of a cell minus the mean recharge of the cells",
        ),
        # end of example
    }
    _merge(monkeypatch, registry.REBUILT_FIELDS, descriptor)
    with pytest.raises(KeyError, match=r"has no row in REBUILT_FIELD_ROWS \(hydromodpy/results/"):
        rebuilt_rows(stored_run, name, [0])

    # example: rows function
    def _anomaly_rows(run, steps):
        cells = [np.asarray(run.field("recharge", time=step)).sum(axis=0) for step in steps]
        return np.array(cells) - np.mean(cells, axis=1, keepdims=True)

    # end of example
    rows = {
        # example: rows row
        "recharge_anomaly": RebuiltField(_anomaly_rows, lambda run: None),
        # end of example
    }
    _merge(monkeypatch, cell_fields.REBUILT_FIELD_ROWS, rows)
    terms_row = {
        # example: terms row
        "recharge_anomaly": ("recharge",),
        # end of example
    }
    _merge(monkeypatch, terms.FIELD_TERMS, terms_row)
    assert terms.budget_terms_for(name) == ("recharge",)
    _merge(monkeypatch, gate.DESCRIPTORS, descriptor)
    gate.test_descriptor_matches_its_kind(name)
    assert abs(rebuilt_rows(stored_run, name, [0, 3]).mean(axis=1)).max() < 1e-9
    assert stored_run.figure(name, time="last").axes[0].collections


def test_case_4_a_quantity(monkeypatch):
    descriptor = registry.TimeSeriesDescriptor("x", "X", "1", quantity="share", label="Share")
    monkeypatch.setitem(registry.TIME_SERIES_REGISTRY, "x", descriptor)
    with pytest.raises(
        KeyError, match=r"Quantity 'share' has no row in QUANTITY_KINDS \(hydromodpy/"
    ):
        registry.kind_of("x")
    written = {
        # example: quantity
        "share": QuantityKind("1", "%", layers=None),
        # end of example
    }
    _merge(monkeypatch, kinds.QUANTITY_KINDS, written)
    gate.test_display_unit_is_reached("share")
    assert registry.kind_of("x") is written["share"]


def test_case_5_a_plain_matplotlib_function(stored_run):
    # example: draw
    def discharge_against_recharge(subject, ax, theme):
        station = subject.stations("discharge")[0]
        discharge = read_series(subject, "discharge", station=station)
        recharge = read_series(subject, "recharge", station="zone:catchment")
        ax.scatter(recharge, discharge, color=theme.roles["observed"])
        ax.plot(recharge, discharge, **static.line_style(theme, "simulated"))
        static.style_axes(ax, theme)

    figure = stored_run.figure(draw=discharge_against_recharge)
    # end of example
    assert len(figure.axes[0].lines) == 1 and figure.axes[0].collections
    with pytest.raises(ValueError, match="draw takes a Python function and is never written"):
        FigureRequest.model_validate({"draw": "discharge_against_recharge"})
    with pytest.raises(ValueError, match=r"takes no keyword beyond subject.*time cannot be given"):
        expand(FigureRequest(draw=discharge_against_recharge, time="last"), PRESETS)
