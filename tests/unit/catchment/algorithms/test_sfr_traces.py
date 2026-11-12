"""One SFR reach trace per declared network, read from the river-network products.

The bench is a straight stream down one column of a 10 m grid. Link 1 is two cells
long (one 10 m step) and link 2 is five cells long (four steps, 40 m).
"""

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.algorithms.sfr_traces import build_sfr_reach_traces
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.units.registry import UREG
from tests._helpers.geotiffs import write_geotiff

N = 9
SOUTH = 8  # D8 code of the southern neighbour


def _geographic(tmp_path, **overrides) -> SimpleNamespace:
    link = np.zeros((N, N))
    link[1:3, 3], link[3:8, 3] = 1.0, 2.0
    acc = np.ones((N, N))
    acc[:, 3] = 5.0 * np.arange(1, N + 1)
    dem = np.repeat(100.0 - np.arange(N)[:, None], N, axis=1)

    def write(name: str, data: np.ndarray) -> str:
        return str(write_geotiff(tmp_path / f"{name}.tif", data, cell=10.0))

    products = SimpleNamespace(
        enabled=True,
        stream_link_id_full_tif=write("link", link),
        flow_acc_cells_tif=write("acc", acc),
    )
    facts = {
        "_river_network_products": products,
        "_flow_products": SimpleNamespace(direc=write("d8", np.full((N, N), float(SOUTH)))),
        "_top_dem_path": write("dem", dem),
        "dem_res": 10.0,
    }
    return SimpleNamespace(**{**facts, **overrides})


def _network(min_reach_length=None) -> SimpleNamespace:
    return SimpleNamespace(min_slope=None, min_reach_length=min_reach_length)


def test_one_trace_per_network(tmp_path) -> None:
    networks = {
        "kept whole": _network(),
        "metres": _network(UREG.Quantity(20.0, "m")),
        "kilometres": _network(UREG.Quantity(0.02, "km")),
        "bare number": _network(20.0),
        "magnitude only": _network(SimpleNamespace(magnitude=20.0)),
    }

    traces = build_sfr_reach_traces(_geographic(tmp_path), networks, {})

    assert list(traces) == list(networks)
    assert traces["kept whole"].reach_count == 2
    # Link 1 (10 m) is shorter than 20 m and goes, link 2 (40 m) stays.
    for name in list(networks)[1:]:
        (reach,) = traces[name].reaches
        assert reach.rlen == pytest.approx(40.0)


def _without(name: str):
    return lambda tmp_path: _geographic(tmp_path, **{name: None})


def _without_link(tmp_path) -> SimpleNamespace:
    geographic = _geographic(tmp_path)
    geographic._river_network_products.stream_link_id_full_tif = None
    return geographic


def _disabled(tmp_path) -> SimpleNamespace:
    geographic = _geographic(tmp_path)
    geographic._river_network_products.enabled = False
    return geographic


REFUSALS = [
    pytest.param(
        _without("_river_network_products"), "needs the river-network products", id="no products"
    ),
    pytest.param(_disabled, "needs the river-network products", id="river network disabled"),
    pytest.param(_without_link, "compute_stream_links = true", id="no stream links"),
    pytest.param(
        _without("_flow_products"), "needs the regional flow products", id="no flow products"
    ),
    pytest.param(_without("_top_dem_path"), "model-top", id="no top dem"),
]


@pytest.mark.parametrize(("make", "message"), REFUSALS)
def test_refusals(tmp_path, make, message) -> None:
    with pytest.raises(ConfigError, match=message):
        build_sfr_reach_traces(make(tmp_path), {"main": _network()}, {})
