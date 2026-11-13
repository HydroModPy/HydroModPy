"""The reads of ``display.subject`` on the small stored run of ``_stored_run.py``."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import subject as reads
from hydromodpy.results.session.view import Session
from tests._helpers.run_builders import GAUGE
from tests.unit.display._stored_run import AREAS, HEAD_TOP, N_CELLS, STAMPS, STARTS

ZONE = "zone:catchment"
DAYS = np.array([31, 28, 31, 30]) * 86400.0

REFUSED = [
    (reads.read_field, ("topography",), {"layer": 1}, "no layer axis"),
    (reads.read_field, ("head",), {"layer": 5}, "outside the 2 layers"),
    (reads.read_field, ("head",), {"layer": "sum"}, "layers are not summed"),
    (reads.read_field, ("head",), {"time": 9}, "period 9 is outside the 4 periods"),
    (reads.read_field, ("porosity",), {}, "holds no field"),
    (reads.read_series, ("discharge",), {"station": GAUGE, "window": (9, "last")}, "outside the 4"),
    (reads.read_field, ("head",), {"layer": True}, "not an index"),
    (reads.read_field, ("head",), {"layer": "mid"}, "not an index"),
    (reads.read_field, ("head",), {"time": "1990-01-01"}, "outside the record"),
    (reads.read_series, ("discharge",), {"station": "nope"}, "Stations: "),
    (reads.read_series, ("head",), {"station": "zone:nowhere"}, "names no zone"),
    (reads.read_observed, ("discharge",), {"station": ZONE}, "no observed record"),
    (reads.read_observed, ("discharge",), {"station": "catchment"}, "no observation"),
    (reads.read_table, ("nothing",), {}, "holds no table"),
]


@pytest.mark.parametrize(("read", "args", "keywords", "words"), REFUSED)
def test_absent_things_refuse_with_a_sentence(stored_run, read, args, keywords, words):
    with pytest.raises(reads.FigureNotApplicable, match=words):
        read(stored_run, *args, **keywords)


@pytest.mark.parametrize(
    ("layer", "expected"), [(None, HEAD_TOP + 2.0), (0, HEAD_TOP + 2.0), (1, HEAD_TOP - 3.0)]
)
def test_field_layer_rules(stored_run, layer, expected):
    np.testing.assert_allclose(reads.read_field(stored_run, "head", layer=layer), expected)


def test_a_flow_sums_its_layers_and_a_date_picks_the_period_it_closes(stored_run):
    flow = reads.read_field(stored_run, "recharge", time="2001-02-01")
    np.testing.assert_allclose(flow, 2.0e-3, rtol=1e-4)


def test_the_zone_sums_a_flow_and_averages_a_state_by_area(stored_run):
    flow = reads.read_series(stored_run, "recharge", station=ZONE)
    np.testing.assert_allclose(flow, 8 * 2.0e-3 * (1 + 0.1 * np.arange(4)), rtol=1e-4)
    head = reads.read_series(stored_run, "head", station=ZONE)
    np.testing.assert_allclose(
        head, np.average(HEAD_TOP[:8], weights=AREAS[:8]) - 1.0 + np.arange(4)
    )


def test_a_flux_is_indexed_on_period_starts_and_a_state_on_period_ends(stored_run):
    assert list(reads.read_series(stored_run, "discharge", station=GAUGE).index) == list(STARTS)
    assert list(reads.read_series(stored_run, "head", station=ZONE).index) == list(STAMPS)
    window = ("2001-02-01", "2001-03-01")
    kept = reads.read_series(stored_run, "discharge", station=GAUGE, window=window)
    assert list(kept.index) == list(STARTS[1:3])
    ends = reads.read_series(stored_run, "discharge", station=GAUGE, window=(1, "last"))
    assert list(ends.index) == list(STARTS[1:])


def test_period_lengths_are_those_of_the_run(stored_run):
    index = reads.read_series(stored_run, "discharge", station=GAUGE).index
    np.testing.assert_allclose(reads.read_period_seconds(stored_run, index), DAYS)


def test_observed_sits_on_the_index_of_the_simulation(stored_run):
    observed = reads.read_observed(stored_run, "discharge", station=GAUGE)
    simulated = reads.read_series(stored_run, "discharge", station=GAUGE)
    assert observed.index.equals(simulated.index)
    np.testing.assert_allclose(observed.dropna(), [1.1, 2.2, 3.3])


def test_budget_terms_and_mesh_view(stored_run):
    assert reads.read_budget(stored_run) == ("recharge", "drain")
    mesh = reads.read_mesh(stored_run)
    assert mesh.faces.shape == (N_CELLS, 4) and mesh.n_layers == 2
    np.testing.assert_allclose(mesh.areas, AREAS)
    assert mesh.zones["catchment"].sum() == 8 and mesh.zones["domain"].all()
