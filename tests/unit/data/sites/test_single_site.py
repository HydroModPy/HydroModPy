"""Match the outlet of a project to the sites of a workspace catalog.

An outlet is a point in a projected CRS (m). A name already in the catalog is
checked against its recorded outlet, an unknown name against the nearest site
within ``near_site_m`` (m).
"""

from __future__ import annotations

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.site.row import SiteRow
from hydromodpy.data.sites.catalog import write_catalog
from hydromodpy.data.sites.single_site import SiteMismatchError, match_site, resolve_single_site

ROWS = [
    SiteRow(
        site="nancon", gauge="J0014010", x_outlet=389285.91, y_outlet=6816518.749, crs="EPSG:2154"
    ),
    SiteRow(site="couesnon", x_outlet=377120.0, y_outlet=6831410.0, crs="EPSG:2154"),
]


def one_site_config(root, name: str, x: float, y: float) -> HydroModPyConfig:
    (root / "data").mkdir(exist_ok=True)
    (root / "dem.tif").write_bytes(b"never read")
    return HydroModPyConfig.from_dict(
        {
            "workspace": {"data_dir": "data"},
            "site": {"name": name},
            "data": {"dem": {"sources": [{"source": "file", "path": "dem.tif"}]}},
            "geographic": {
                "crs_project": "EPSG:2154",
                "catchment": {
                    "kind": "from_outlet_coord",
                    "x_outlet": x,
                    "y_outlet": y,
                    "snap_dist": "150 m",
                    "buff_area": "10%",
                },
            },
            "simulation": {
                "name": "probe",
                "time": {
                    "start_datetime": "2000-01-01",
                    "end_datetime": "2000-03-31",
                    "step_value": "1 month",
                },
                "process": [{"id": "flow_main", "kind": "flow", "solvers": ["modflow6"]}],
            },
            "flow": {
                "flow_regime": "steady",
                "param_list": ["K"],
                "bc": {"drainage": {}},
                "param": {"K": {"field": {"kind": "homogeneous", "unit": "m/s", "value": 5e-5}}},
            },
        },
        base_dir=root,
    )


def test_a_known_name_at_its_outlet_is_the_row() -> None:
    match = match_site("nancon", (389300.0, 6816500.0), "EPSG:2154", ROWS, near_site_m=500.0)

    assert match is not None and match.row.site == "nancon" and match.known_name
    assert match.distance_m == pytest.approx(23.5, abs=0.5)


def test_an_unknown_name_near_a_site_names_it() -> None:
    match = match_site("romazy", (377100.0, 6831400.0), "EPSG:2154", ROWS, near_site_m=500.0)

    assert match is not None and match.row.site == "couesnon" and not match.known_name


def test_an_unknown_name_far_from_every_site_is_new() -> None:
    assert match_site("vire", (300000.0, 6900000.0), "EPSG:2154", ROWS, near_site_m=500.0) is None
    assert match_site("vire", None, None, ROWS) is None


def test_resolve_single_site_reads_the_workspace_catalog(tmp_path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    write_catalog(workspace, ROWS)
    project = tmp_path / "project"
    project.mkdir()

    match = resolve_single_site(one_site_config(project, "nancon", 389300.0, 6816500.0), workspace)
    assert match is not None and match.known_name and match.row.gauge == "J0014010"
    assert match.distance_m == pytest.approx(23.5, abs=0.5)

    near = resolve_single_site(one_site_config(project, "romazy", 377100.0, 6831400.0), workspace)
    assert near is not None and not near.known_name and near.row.site == "couesnon"

    with pytest.raises(SiteMismatchError, match="'nancon'.*m away"):
        resolve_single_site(one_site_config(project, "nancon", 377120.0, 6831410.0), workspace)

    # No catalog in the workspace: nothing to resolve against.
    bare = tmp_path / "bare"
    bare.mkdir()
    assert (
        resolve_single_site(one_site_config(project, "nancon", 389300.0, 6816500.0), bare) is None
    )
