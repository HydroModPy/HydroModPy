"""The map overlays and the UGRID export."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.maps.overlays import OverlayUnavailable, apply_overlays, draw_wells
from hydromodpy.display.maps.ugrid import render_face_field

# A run that declares wells but kept no well field says which key to set.
#
# The overlay reads the well budget field, which a run keeps unless
# ``[simulation.results] keep_per_cell_budget`` is false and no consumer asked
# for it. Without it the overlay used to vanish with one INFO line, and a reader
# took the wells for absent.

WELLS = {"W1": {"location": {"kind": "absolute_xy", "x": 1.0, "y": 2.0}, "flux": -0.01}}


def _run(snapshot: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        sim_id="sim-wells",
        has_field=lambda variable, **_: False,
        config_snapshot=snapshot,
    )


def test_a_run_that_declares_wells_is_told_the_key_to_set() -> None:
    run = _run({"flow": {"sinks_sources": {"wells": WELLS}}})

    with pytest.raises(OverlayUnavailable) as raised:
        draw_wells(None, run)

    assert raised.value.actionable
    assert "[simulation.results] keep_per_cell_budget = true" in str(raised.value)
    assert "declares wells" in str(raised.value)


def test_the_skip_is_a_warning_when_the_user_can_fix_it(caplog) -> None:
    run = _run({"flow": {"sinks_sources": {"wells": WELLS}}})

    with caplog.at_level(logging.INFO):
        drawn = apply_overlays(None, run, ["wells"])

    assert drawn == []
    (record,) = [r for r in caplog.records if "Overlay 'wells'" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert "keep_per_cell_budget = true" in record.getMessage()


def _store_run(policy: str, kept: list[str]) -> SimpleNamespace:
    """A run whose ``budget/`` group declares what it kept, as a store does."""
    root = {
        "head": object(),
        "budget": SimpleNamespace(attrs={"policy": policy, "kept_terms": kept}),
    }
    store = SimpleNamespace(root=root, close=lambda: None)
    return SimpleNamespace(
        sim_id="sim-wells",
        has_field=lambda variable, **_: False,
        config_snapshot={"flow": {"sinks_sources": {"wells": WELLS}}},
        _catalog=SimpleNamespace(open_zarr=lambda _sim_id: store),
    )


def test_the_skip_says_what_the_run_kept() -> None:
    with pytest.raises(OverlayUnavailable) as raised:
        draw_wells(None, _store_run("consumers", ["recharge"]))

    assert raised.value.actionable
    message = str(raised.value)
    assert "kept only the per-cell budget terms its consumers read (recharge)" in message
    assert "also needs well" in message
    assert "spatial_fields" not in message


def test_a_run_that_kept_the_whole_budget_has_no_key_to_set() -> None:
    """The model has no well package: no setting would have stored one."""
    with pytest.raises(OverlayUnavailable) as raised:
        draw_wells(None, _store_run("all", ["recharge"]))

    assert not raised.value.actionable


@pytest.mark.parametrize(
    "snapshot",
    [None, {}, {"flow": {"sinks_sources": {}}}, {"flow": {"sinks_sources": {"wells": {}}}}],
)
def test_a_run_without_wells_stays_a_quiet_skip(caplog, snapshot) -> None:
    with caplog.at_level(logging.INFO):
        drawn = apply_overlays(None, _run(snapshot), ["wells"])

    assert drawn == []
    (record,) = [r for r in caplog.records if "Overlay 'wells'" in r.getMessage()]
    assert record.levelno == logging.INFO
    assert "keep_per_cell_budget" not in record.getMessage()


# Unit tests for UGRID face-field rendering.


def _mesh_run(connectivity: np.ndarray) -> SimpleNamespace:
    mesh = SimpleNamespace(
        vertices=np.asarray(
            [
                [0.0, 0.0, 10.0],
                [1.0, 0.0, 11.0],
                [1.0, 1.0, 12.0],
                [0.0, 1.0, 13.0],
                [2.0, 0.0, 14.0],
                [2.0, 1.0, 15.0],
            ]
        ),
        face_node_connectivity=connectivity,
    )
    return SimpleNamespace(mesh=mesh)


def test_render_face_field_ignores_integer_padding_and_labels_colorbar() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sim = _mesh_run(np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int))
    fig, ax = plt.subplots()

    collection = render_face_field(
        ax,
        sim,
        np.asarray([10.0, 20.0]),
        vmin=0.0,
        vmax=30.0,
        cbar_label="Head [m]",
    )

    try:
        assert len(collection.get_paths()) == 2
        assert collection.get_array().tolist() == [10.0, 20.0]
        assert collection.get_clim() == (0.0, 30.0)
        assert fig.axes[-1].get_ylabel() == "Head [m]"
    finally:
        plt.close(fig)


def test_render_face_field_ignores_float_nan_padding() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sim = _mesh_run(np.asarray([[0.0, 1.0, 2.0, np.nan], [0.0, 2.0, 3.0, np.nan]]))
    fig, ax = plt.subplots()

    collection = render_face_field(ax, sim, np.asarray([1.0, 2.0]))

    try:
        polygons = [path.vertices[:-1] for path in collection.get_paths()]
        assert [polygon.shape[0] for polygon in polygons] == [3, 3]
        assert np.allclose(polygons[0], [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    finally:
        plt.close(fig)


def test_render_face_field_rejects_value_count_mismatch() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sim = _mesh_run(np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int))
    fig, ax = plt.subplots()

    try:
        with pytest.raises(ValueError, match="face field has 1 values but mesh has 2 faces"):
            render_face_field(ax, sim, np.asarray([10.0]))
    finally:
        plt.close(fig)
