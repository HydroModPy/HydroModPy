"""The effective porosity of a run is its stored field, else its sealed configuration value."""

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.results.derive.porosity import effective_porosity


def held(snapshot, stored=None):
    return SimpleNamespace(
        name="r", n_layers=2, n_cells=3, config_snapshot=snapshot,
        has_field=lambda name: stored is not None, field=lambda name: stored,
    )  # fmt: skip


def test_the_field_wins_then_the_sealed_value_spreads_over_layers_and_cells():
    sealed = {"transport": {"first": {"porosity": None}, "second": {"porosity": 0.1}}}
    assert effective_porosity(held(sealed)).tolist() == np.full((2, 3), 0.1).tolist()
    assert effective_porosity(held(sealed, np.full((2, 3), 0.3)))[0, 0] == pytest.approx(0.3)
    with pytest.raises(NothingThereError, match="porosity"):
        effective_porosity(held({}))


def test_several_sections_that_set_a_porosity_are_refused_by_name():
    sealed = {"transport": {"first": {"porosity": 0.1}, "second": {"porosity": 0.2}}}
    with pytest.raises(NothingThereError, match="several .*first, second"):
        effective_porosity(held(sealed))
