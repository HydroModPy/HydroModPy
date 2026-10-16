"""The ``sfr_reaches`` table keeps the reaches each reach drains into.

The MODFLOW files are scratch, so a sealed run could say which cell carries a
reach but not how the reaches connect. A profile along a branched network needs
the connection: the numbering alone interleaves the tributaries.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run import Run
from hydromodpy.results.run.sfr import sfr_reach_links
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.solver.modflow6.extractors.sfr import SfrObsSpec, SfrReachGeometry
from tests._helpers.run_stores import open_run_store

REACH = {
    "ifno": 0,
    "layer": 0,
    "cell2d": 4,
    "rlen": 100.0,
    "rwid": 2.0,
    "rgrd": 0.01,
    "rtp": 150.0,
    "rbth": 1.0,
    "rhk": 1.0e-5,
    "manning": 0.035,
    "strahler": 1,
    "ustrf": 1.0,
}


def _links_of_sealed(project: Path, rows: list[dict] | None) -> pd.DataFrame:
    """Seal a run, with the ``sfr_reaches`` view when *rows* is given; read its links back."""
    store = open_run_store(project, "run", n_cells=1, n_layers=1)
    sid = store.sim_id
    if rows is not None:
        store.write_view(sid, "sfr_reaches", rows)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        return sfr_reach_links(Run(sid, catalog))


def test_the_sidecar_reads_the_downstream_reaches_back() -> None:
    reach = SfrReachGeometry.from_mapping({**REACH, "downstream": [2, 3]})

    assert reach.downstream == (2, 3)


def test_a_sidecar_without_the_links_is_refused_not_read_as_outlets() -> None:
    with pytest.raises(KeyError, match="downstream"):
        SfrObsSpec.from_mapping(
            {
                "obs_csv": "m.sfr.obs.csv",
                "network_id": "main",
                "reaches": [REACH],
            }
        )


def test_the_links_come_back_from_the_stored_table(tmp_path: Path) -> None:
    rows = [
        {"network_id": "main", **REACH, "ifno": 0, "downstream": [1]},
        {"network_id": "main", **REACH, "ifno": 1, "downstream": []},
    ]
    links = _links_of_sealed(tmp_path / "project", rows)

    assert list(links["ifno"]) == [0, 1]
    assert [list(down) for down in links["downstream"]] == [[1], []]
    assert list(links["rlen"]) == [100.0, 100.0]


def test_a_run_without_a_stream_network_has_no_links(tmp_path: Path) -> None:
    links = _links_of_sealed(tmp_path / "project", None)

    assert links.empty
    assert list(links.columns) == ["network_id", "ifno", "rlen", "ustrf", "downstream"]


def test_the_builder_writes_the_links_of_every_reach_into_the_sidecar() -> None:
    from hydromodpy.solver.modflow6.builders.sfr import (
        build_sfr_package_args,
        resolve_sfr_networks,
    )
    from tests.unit.solver.test_modflow6_sfr_builder import _fake_model, _mesh, _trace_payload
    from tests.unit.solver.test_modflow6_sfr_builder import _two_reach_trace as trace

    model = _fake_model({"net0": _trace_payload(trace())})
    networks = resolve_sfr_networks(model, solver_mesh=_mesh())

    meta = build_sfr_package_args(model, networks=networks)["sfr_obs_meta"]

    by_ifno = {reach.ifno: reach for reach in networks["net0"].reaches}
    assert [item["downstream"] for item in meta["reaches"]] == [
        list(by_ifno[item["ifno"]].downstream) for item in meta["reaches"]
    ]
    assert any(item["downstream"] for item in meta["reaches"])
