from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.domain import Domain, DomainConfig, Surface
from hydromodpy.solver.modflow_nwt.modflow import Modflow


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


def _build_domain_from_dem(dem: np.ndarray) -> Domain:
    return Domain(
        config=DomainConfig(),
        surface_topo=Surface(name="surface_topo", values=np.asarray(dem, dtype=float)),
    )


def test_modflow_requires_domain_object_for_spatial_geometry():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)

    model = Modflow(
        geographic=geo,
        model_folder=".",
    )
    with pytest.raises(ValueError, match="domain-only: a Domain object is required"):
        model._get_domain_surfaces()


def test_modflow_domain_surfaces_are_required():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)
    domain = _build_domain_from_dem(dem)

    domain.substratum = None
    model = Modflow(geographic=geo, model_folder=".")
    model.domain = domain
    with pytest.raises(
        ValueError,
        match="domain.surface_topo and domain.substratum are required",
    ):
        model._get_domain_surfaces()


def test_modflow_validates_domain_shape_match_on_surface_build():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)
    wrong_domain = _build_domain_from_dem(np.array([[1.0]], dtype=float))

    model = Modflow(
        geographic=geo,
        model_folder=".",
    )
    model.domain = wrong_domain

    with pytest.raises(ValueError, match="Domain surface shape must match active DEM"):
        model._get_domain_surfaces()
