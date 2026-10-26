"""A map of a layered field with no layer named shows the top active cell of each column."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.display.figures._scalar_face_map import top_active_values

VALUES = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])


def _sim(idomain: np.ndarray | None) -> SimpleNamespace:
    return SimpleNamespace(
        has_field=lambda name: idomain is not None and name == "idomain",
        field=lambda name: idomain,
    )


def test_each_column_shows_its_top_active_cell() -> None:
    shown = top_active_values(_sim(np.array([[1, 0, 0], [1, 1, 0]])), VALUES)
    assert shown[:2].tolist() == [1.0, 5.0]
    assert np.isnan(shown[2])


def test_a_run_without_an_idomain_shows_layer_zero() -> None:
    assert top_active_values(_sim(None), VALUES).tolist() == [1.0, 2.0, 3.0]
