"""Map of the agreement between the simulated and the mapped stream network.

A cell is valid (both networks), excess (simulated only), missing (mapped only)
or neither. The run is the V-shaped valley of
:mod:`tests.unit.display._network_comparison_run`, whose partition is known
before the criterion is called.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.colors import to_rgb, to_rgba

from hydromodpy.display.figures._stream_comparison import (
    AGREEMENT_COLORS,
    CASING_COLOR,
    CELL_WEIGHT_PT,
)
from hydromodpy.display.figures.seepage_network_confusion_map import SeepageNetworkConfusionMap
from hydromodpy.results.derive.stream_network.comparison import (
    AGREEMENT_EXCESS,
    AGREEMENT_MISSING,
    AGREEMENT_NEITHER,
    AGREEMENT_VALID,
    agreement_label,
)

from ._network_comparison_run import (
    AXIS_COLUMN,
    cell,
    column_cells,
    comparison_run,
    drawn_cells,
    legend_note,
)


def partition_run():
    """Seepage halfway down the mapped column and on the south-east corner.

    The first closes down the column and agrees with the map, the second
    crosses two cells of the flank before joining it, and the northern cell of
    the map has no simulated stream: two valid, two excess, one missing.
    """
    return comparison_run(seepage_cells=[cell(AXIS_COLUMN, 1), cell(4, 0)])


def layer(ax, value: int):
    """The one collection drawn under an agreement class."""
    label = agreement_label(value)
    return next(item for item in ax.collections if str(item.get_label()) == label)


def class_cells(ax, value: int) -> list[int]:
    """The grid cells drawn under one agreement class, empty when it has none."""
    label = agreement_label(value)
    for collection in ax.collections:
        if str(collection.get_label()) == label:
            return drawn_cells(collection)
    return []


def test_every_class_has_its_own_color(mpl) -> None:
    _, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(partition_run(), ax)

    for value, color in AGREEMENT_COLORS.items():
        face = tuple(np.asarray(layer(ax, value).get_facecolor()).reshape(-1)[:3])
        assert face == pytest.approx(to_rgb(color))


def test_threshold_far_above_any_release_leaves_the_column_missing(mpl) -> None:
    # No cell releases that much, so there is no simulated stream.
    _, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(partition_run(), ax, tau_specific_ratio=1.0e6)

    assert class_cells(ax, AGREEMENT_MISSING) == column_cells(AXIS_COLUMN)
    assert class_cells(ax, AGREEMENT_VALID) == []
    assert class_cells(ax, AGREEMENT_EXCESS) == []
    assert "above 1e+06 times its recharge" in legend_note(ax)


def test_network_is_widened_once_not_class_by_class(mpl) -> None:
    # A class is a one-cell-wide line that needs weight to survive the page.
    # Given a stroke each, the classes interleave cell by cell and each widens
    # over its neighbours (on the Nancon valid held the most cells and printed
    # the least ink). The weight is carried once, by a casing over their union.
    _, ax = mpl.subplots()

    SeepageNetworkConfusionMap().render(partition_run(), ax)

    casing = next(item for item in ax.collections if str(item.get_label()) == "_network casing")
    assert float(casing.get_linewidth()[0]) == pytest.approx(CELL_WEIGHT_PT)
    union = (
        class_cells(ax, AGREEMENT_VALID)
        + class_cells(ax, AGREEMENT_EXCESS)
        + class_cells(ax, AGREEMENT_MISSING)
    )
    assert drawn_cells(casing) == sorted(union), "the casing covers the three classes only"
    assert tuple(np.asarray(casing.get_facecolor()).reshape(-1)) == pytest.approx(
        to_rgba(CASING_COLOR)
    )
    for value in (AGREEMENT_VALID, AGREEMENT_EXCESS, AGREEMENT_MISSING, AGREEMENT_NEITHER):
        assert float(layer(ax, value).get_linewidth()[0]) == 0.0, agreement_label(value)


def test_unknown_frame_is_refused(mpl) -> None:
    _, ax = mpl.subplots()

    with pytest.raises(ValueError, match="extent must be"):
        SeepageNetworkConfusionMap().render(partition_run(), ax, extent="everything")


def test_run_without_release_flux_names_what_it_needs() -> None:
    reason = SeepageNetworkConfusionMap().unavailable_reason(comparison_run(with_release=False))

    assert reason is not None
    assert "release_flux" in reason
