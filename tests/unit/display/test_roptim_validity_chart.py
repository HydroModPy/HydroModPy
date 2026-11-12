"""Cross-site chart of the optimal agreement r_optim (-) against its validity bound.

One record per site (transmissivity in m2/s, d_optim in m) is carried into
``render``, because no single run holds another catchment. The tests read the
artists and the annotations, never pixels.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.display.figures.roptim_validity_chart import (
    RoptimValidityChart,
    SiteAgreement,
)

from ._render_helpers import labelled_patch


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


def _texts(ax) -> list[str]:
    return [item.get_text() for item in ax.texts]


RECORD_REFUSALS = [
    pytest.param(
        {"label": "cheze", "transmissivity": 1e-4, "d_optim": 120.0, "r_optim": -0.5},
        "r_optim",
        id="negative r_optim",
    ),
    pytest.param(
        {"label": "   ", "transmissivity": 1e-4, "d_optim": 120.0, "r_optim": 1.2},
        "label",
        id="missing label",
    ),
    pytest.param(
        {"label": "cheze", "transmissivity": 0.0, "d_optim": 120.0, "r_optim": 1.2},
        "transmissivity",
        id="zero transmissivity",
    ),
    pytest.param(
        {"label": "cheze", "transmissivity": 1e-4, "d_optim": -1.0, "r_optim": 1.2},
        "d_optim",
        id="negative d_optim",
    ),
]

RENDER_REFUSALS = [
    pytest.param({"sites": _sites(), "bound": 0.0}, "bound", id="zero bound"),
    pytest.param({"sites": []}, "at least one site", id="no site"),
]


@pytest.mark.parametrize(("fields", "message"), RECORD_REFUSALS)
def test_record_refusals(fields, message) -> None:
    with pytest.raises(ValueError, match=message):
        SiteAgreement(**fields)


@pytest.mark.parametrize(("kwargs", "message"), RENDER_REFUSALS)
def test_render_refusals(mpl, kwargs, message) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match=message):
        RoptimValidityChart().render(_run(), ax, **kwargs)


def test_zone_beyond_the_bound(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites())

    zone = labelled_patch(ax, "beyond the validity bound")
    assert zone.get_y() == pytest.approx(2.0)
    assert zone.get_y() + zone.get_height() == pytest.approx(ax.get_ylim()[1])
    bound_line = next(
        line for line in ax.lines if str(line.get_label()).startswith("validity bound")
    )
    assert bound_line.get_ydata()[0] == pytest.approx(2.0)
    assert "2" in bound_line.get_label()


def test_bound_moves_the_two_classes(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites(), bound=1.5)

    assert _collection(ax, "r_optim within").get_offsets().tolist() == [[1e-4, 1.2]]
    assert _collection(ax, "r_optim beyond").get_offsets().tolist() == [[5e-4, 1.8], [2e-3, 3.4]]
    assert labelled_patch(ax, "beyond the validity bound").get_y() == pytest.approx(1.5)


def test_every_site_within_the_bound(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run(), ax, sites=_sites()[:2])

    assert not _has_collection(ax, "r_optim beyond")
    note = next(text for text in _texts(ax) if "no site" in text)
    assert "2" in note
    assert labelled_patch(ax, "beyond the validity bound") is not None


def test_site_without_an_agreement_is_not_drawn_as_zero(mpl) -> None:
    fig, ax = mpl.subplots()
    failed = SiteAgreement(
        label="failed", transmissivity=8e-4, d_optim=float("nan"), r_optim=float("nan")
    )

    RoptimValidityChart().render(_run(), ax, sites=[*_sites()[:1], failed])

    drawn = _collection(ax, "r_optim within").get_offsets().tolist()
    assert drawn == [[1e-4, 1.2]]
    assert "failed" not in _texts(ax)
    assert any("1 site carries no r_optim" in text for text in _texts(ax))


def test_run_outside_the_set_draws_no_ring(mpl) -> None:
    fig, ax = mpl.subplots()

    RoptimValidityChart().render(_run("elsewhere"), ax, sites=_sites())

    assert not _has_collection(ax, "elsewhere")
    assert "3 sites" in ax.get_title()


def test_gallery_of_one_run_is_unavailable() -> None:
    reason = RoptimValidityChart().unavailable_reason(_run())

    assert reason is not None
    assert "site" in reason
    assert "render()" in reason


def test_no_site_measured_claims_no_agreement(mpl) -> None:
    # Zero measured sites must not read as "everybody agrees".
    fig, ax = mpl.subplots()
    sites = [
        SiteAgreement(label=name, transmissivity=t, d_optim=float("nan"), r_optim=float("nan"))
        for name, t in [("failed", 1e-4), ("also-failed", 5e-4)]
    ]

    RoptimValidityChart().render(_run(), ax, sites=sites)

    assert _collection(ax, "r_optim within").get_offsets().tolist() == []
    note = next(text for text in _texts(ax) if "r_optim" in text)
    assert "agree within the bound" not in note
    assert "no site carries an r_optim" in note
    assert "2 sites carry no r_optim" in note
