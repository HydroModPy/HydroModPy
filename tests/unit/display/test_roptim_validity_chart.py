"""The cross-site chart of the optimal agreement against its validity bound.

The chart is driven the way a paper figure is: one record per site, carried
into ``render`` because no single run holds another catchment. The tests read
the artists, the annotations and the refusals, never pixels.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures.roptim_validity_chart import (
    RoptimValidityChart,
    SiteAgreement,
)


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _sites() -> list[SiteAgreement]:
    """Three sites, the last one past the bound the method declares valid."""
    return [
        SiteAgreement(label="cheze", transmissivity=1e-4, d_optim=120.0, r_optim=1.2),
        SiteAgreement(label="abherve", transmissivity=5e-4, d_optim=210.0, r_optim=1.8),
        SiteAgreement(label="naizin", transmissivity=2e-3, d_optim=460.0, r_optim=3.4),
    ]


def _run(name: str = "cheze") -> SimpleNamespace:
    return SimpleNamespace(sim_id="sim-cheze", name=name)


def _collection(ax, prefix: str):
    return next(item for item in ax.collections if str(item.get_label()).startswith(prefix))


def _has_collection(ax, prefix: str) -> bool:
    return any(str(item.get_label()).startswith(prefix) for item in ax.collections)


def _patch(ax, prefix: str):
    return next(item for item in ax.patches if str(item.get_label()).startswith(prefix))


def _texts(ax) -> list[str]:
    return [item.get_text() for item in ax.texts]


def _rgba(color: str):
    from matplotlib.colors import to_rgba

    return to_rgba(color)


def _relative_luminance(color) -> float:
    """Perceived brightness, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


# --------------------------------------------------------------------------- #
# the record
# --------------------------------------------------------------------------- #


def test_a_record_refuses_a_negative_roptim() -> None:
    with pytest.raises(ValueError, match="r_optim"):
        SiteAgreement(label="cheze", transmissivity=1e-4, d_optim=120.0, r_optim=-0.5)


def test_a_record_refuses_a_missing_label() -> None:
    with pytest.raises(ValueError, match="label"):
        SiteAgreement(label="   ", transmissivity=1e-4, d_optim=120.0, r_optim=1.2)


def test_a_record_refuses_a_non_positive_transmissivity() -> None:
    with pytest.raises(ValueError, match="transmissivity"):
        SiteAgreement(label="cheze", transmissivity=0.0, d_optim=120.0, r_optim=1.2)


def test_a_record_refuses_a_negative_doptim() -> None:
    with pytest.raises(ValueError, match="d_optim"):
        SiteAgreement(label="cheze", transmissivity=1e-4, d_optim=-1.0, r_optim=1.2)


def test_a_record_accepts_a_site_whose_agreement_was_never_measured() -> None:
    record = SiteAgreement(
        label="failed", transmissivity=1e-4, d_optim=float("nan"), r_optim=float("nan")
    )
    assert np.isnan(record.r_optim)


# --------------------------------------------------------------------------- #
# the chart
# --------------------------------------------------------------------------- #


def test_chart_puts_one_marker_per_site_on_each_of_the_two_axes(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites())

    try:
        twin = fig.axes[-1]
        within = _collection(ax, "r_optim within").get_offsets().tolist()
        beyond = _collection(ax, "r_optim beyond").get_offsets().tolist()
        assert within == [[1e-4, 1.2], [5e-4, 1.8]]
        assert beyond == [[2e-3, 3.4]]
        assert _collection(twin, "D_optim").get_offsets().tolist() == [
            [1e-4, 120.0],
            [5e-4, 210.0],
            [2e-3, 460.0],
        ]
    finally:
        mpl.close(fig)


def test_chart_reads_the_transmissivity_on_a_log_axis_and_names_both_ordinates(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites())

    try:
        twin = fig.axes[-1]
        assert ax.get_xscale() == "log"
        assert ax.get_xlabel() == "Transmissivity (m²/s)"
        assert ax.get_ylabel() == "r_optim (-)"
        assert twin.get_ylabel() == "D_optim (m)"
    finally:
        mpl.close(fig)


def test_the_zone_beyond_the_bound_is_shaded_and_labelled(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites())

    try:
        zone = _patch(ax, "beyond the validity bound")
        assert zone.get_y() == pytest.approx(2.0)
        assert zone.get_y() + zone.get_height() == pytest.approx(ax.get_ylim()[1])
        bound_line = next(
            line for line in ax.lines if str(line.get_label()).startswith("validity bound")
        )
        assert bound_line.get_ydata()[0] == pytest.approx(2.0)
        assert "2" in bound_line.get_label()
    finally:
        mpl.close(fig)


def test_a_site_beyond_the_bound_stays_visible_and_carries_its_name(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites())

    try:
        assert ax.get_ylim()[1] > 3.4
        beyond = _collection(ax, "r_optim beyond")
        assert beyond.get_offsets().tolist() == [[2e-3, 3.4]]
        assert "naizin" in _texts(ax)
        note = next(text for text in _texts(ax) if "beyond" in text and "naizin" in text)
        assert "1 of 3" in note
    finally:
        mpl.close(fig)


def test_the_two_classes_of_site_differ_by_marker_and_by_lightness(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites())

    try:
        within = _collection(ax, "r_optim within")
        beyond = _collection(ax, "r_optim beyond")
        assert tuple(within.get_facecolor()[0]) == _rgba(HIGH_CONTRAST_TRIPLET[0])
        assert tuple(beyond.get_facecolor()[0]) == _rgba(HIGH_CONTRAST_TRIPLET[2])
        gap = abs(
            _relative_luminance(HIGH_CONTRAST_TRIPLET[0])
            - _relative_luminance(HIGH_CONTRAST_TRIPLET[2])
        )
        assert gap > 0.05
        assert not np.array_equal(within.get_paths()[0].vertices, beyond.get_paths()[0].vertices)
    finally:
        mpl.close(fig)


def test_the_bound_is_an_argument_and_moves_the_two_classes(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites(), bound=1.5)

    try:
        assert _collection(ax, "r_optim within").get_offsets().tolist() == [[1e-4, 1.2]]
        assert _collection(ax, "r_optim beyond").get_offsets().tolist() == [
            [5e-4, 1.8],
            [2e-3, 3.4],
        ]
        zone = _patch(ax, "beyond the validity bound")
        assert zone.get_y() == pytest.approx(1.5)
    finally:
        mpl.close(fig)


def test_a_non_positive_bound_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="bound"):
            RoptimValidityChart().render(_run(), ax, sites=_sites(), bound=0.0)
    finally:
        mpl.close(fig)


def test_every_site_within_the_bound_is_said_so_instead_of_left_to_guess(mpl) -> None:
    fig, ax = mpl.subplots()
    sites = _sites()[:2]

    RoptimValidityChart().render(_run(), ax, sites=sites)

    try:
        assert not _has_collection(ax, "r_optim beyond")
        note = next(text for text in _texts(ax) if "no site" in text)
        assert "2" in note
        assert _patch(ax, "beyond the validity bound") is not None
    finally:
        mpl.close(fig)


def test_a_site_without_an_agreement_is_reported_and_never_drawn_as_zero(mpl) -> None:
    fig, ax = mpl.subplots()
    sites = [
        *_sites()[:1],
        SiteAgreement(
            label="failed", transmissivity=8e-4, d_optim=float("nan"), r_optim=float("nan")
        ),
    ]

    RoptimValidityChart().render(_run(), ax, sites=sites)

    try:
        drawn = _collection(ax, "r_optim within").get_offsets().tolist()
        assert drawn == [[1e-4, 1.2]]
        assert not any(point[1] == 0.0 for point in drawn)
        assert "failed" not in _texts(ax)
        assert any("1 site carries no r_optim" in text for text in _texts(ax))
    finally:
        mpl.close(fig)


def test_an_empty_set_of_sites_is_refused(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="at least one site"):
            RoptimValidityChart().render(_run(), ax, sites=[])
    finally:
        mpl.close(fig)


def test_the_catchment_of_the_run_is_ringed_among_the_others(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run("abherve"), ax, sites=_sites())

    try:
        ring = _collection(ax, "abherve")
        assert ring.get_offsets().tolist() == [[5e-4, 1.8]]
        assert "abherve" in ax.get_title()
    finally:
        mpl.close(fig)


def test_a_run_naming_no_site_of_the_set_draws_no_ring(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run("elsewhere"), ax, sites=_sites())

    try:
        assert not _has_collection(ax, "elsewhere")
        assert "3 sites" in ax.get_title()
    finally:
        mpl.close(fig)


def test_the_legend_names_the_two_classes_and_the_shaded_zone(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites())

    try:
        twin = fig.axes[-1]
        labels = [text.get_text() for text in twin.get_legend().get_texts()]
        assert any(label.startswith("r_optim within") for label in labels)
        assert any(label.startswith("r_optim beyond") for label in labels)
        assert any(label.startswith("D_optim") for label in labels)
        assert any("beyond the validity bound" in label for label in labels)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# availability and registration
# --------------------------------------------------------------------------- #


def test_a_gallery_driven_by_one_run_skips_with_a_readable_reason() -> None:
    reason = RoptimValidityChart().unavailable_reason(_run())

    assert reason is not None
    assert "site" in reason
    assert "render()" in reason


def test_registered_under_its_own_name() -> None:
    figure = get_figure("roptim_validity_chart")

    assert isinstance(figure, RoptimValidityChart)
    assert figure.spec.name == "roptim_validity_chart"
    assert figure.spec.kind == "comparison"


def test_a_set_where_no_site_was_ever_measured_claims_no_agreement(mpl) -> None:
    """Zero measured sites must not read as "everybody agrees"."""
    fig, ax = mpl.subplots()
    sites = [
        SiteAgreement(
            label="failed", transmissivity=1e-4, d_optim=float("nan"), r_optim=float("nan")
        ),
        SiteAgreement(
            label="also-failed", transmissivity=5e-4, d_optim=float("nan"), r_optim=float("nan")
        ),
    ]

    RoptimValidityChart().render(_run(), ax, sites=sites)

    try:
        assert _collection(ax, "r_optim within").get_offsets().tolist() == []
        note = next(text for text in _texts(ax) if "r_optim" in text)
        assert "agree within the bound" not in note
        assert "no site carries an r_optim" in note
        assert "2 sites carry no r_optim" in note
    finally:
        mpl.close(fig)
