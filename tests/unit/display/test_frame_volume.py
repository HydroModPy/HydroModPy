"""The volume frame on the small stored run: the block around a map, and what it refuses."""

from __future__ import annotations

from dataclasses import replace

import pytest

from hydromodpy.display.frames import volume
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable


def data(run, **panel):
    return volume.data(run, PanelRequest(type="volume", **panel))


def test_a_block_takes_its_top_and_base_from_the_first_and_last_interface_or_one_layer(stored_run):
    whole = data(stored_run, variable="head")
    assert set(whole.table["top"]) == {120.0} and set(whole.table["bottom"]) == {0.0}
    one = data(stored_run, variable="head", layer=1)
    assert set(one.table["top"]) == {60.0} and set(one.table["bottom"]) == {0.0}
    assert sorted(set(whole.cells) - {-1}) == list(range(12))  # the walls own no cell


def test_a_table_column_has_no_block_and_a_mesh_without_interfaces_has_none(
    stored_run, monkeypatch
):
    with pytest.raises(FigureNotApplicable, match="has no block to draw"):
        data(stored_run, variable="sfr_reaches.strahler")
    real = volume.map_frame.data

    def flat(subject, panel):
        found = real(subject, panel)
        return replace(found, mesh=replace(found.mesh, interfaces=None))

    monkeypatch.setattr(volume.map_frame, "data", flat)
    with pytest.raises(FigureNotApplicable, match="no layer interfaces"):
        data(stored_run, variable="head")
