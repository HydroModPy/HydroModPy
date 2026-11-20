"""MODPATH runtime resolvers: the zone raster, the CRS and the name file of a MODFLOW-NWT run.

The default zone is the domain raster. The seepage zone is the seepage raster of the first
period clipped to the watershed polygon. The CRS is the one of the raster, else the one of
the domain surface.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.model.domain.geometry import CatchmentGeometry, RasterGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_nwt.modpath import resolvers
from tests._helpers.model_factory import make_model


def flow_run(*, raster=None, catchment=None) -> SimpleNamespace:
    """A NWT solver object that keeps a Model with this raster and catchment."""
    geometry = Geometry(
        cells=None,
        domain=None,
        raster=None if raster is None else RasterGeometry.from_geographic(raster),
        catchment=(
            None if catchment is None else CatchmentGeometry.from_geographic(catchment, crs=None)
        ),
    )
    return SimpleNamespace(inputs=make_model(geometry=geometry))


def test_domain_zone_is_the_domain_raster(tmp_path: Path):
    run = flow_run(raster=SimpleNamespace(watershed_box_buff_dem="domain_raster.tif"))

    zone = resolvers.resolve_zone_partic("domain", full_path=str(tmp_path), model_modflow=run)

    assert zone == "domain_raster.tif"


def test_seepage_zone_is_the_seepage_raster_clipped_to_the_watershed(tmp_path: Path, monkeypatch):
    rasters_dir = tmp_path / "_postprocess" / "_rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)
    seepage_tif = rasters_dir / "seepage_areas_t(0).tif"
    seepage_tif.write_text("dummy")
    watershed_shp = tmp_path / "watershed.shp"
    watershed_shp.write_text("dummy")
    run = flow_run(catchment=SimpleNamespace(watershed_shp=str(watershed_shp)))
    calls: dict[str, object] = {}

    class FakeRaster:
        def clip_raster_to_polygon(
            self, in_raster: str, in_polygon: str, out_raster: str, maintain_dimensions: bool = True
        ) -> None:
            calls.update(
                in_raster=in_raster,
                in_polygon=in_polygon,
                out_raster=out_raster,
                maintain_dimensions=maintain_dimensions,
            )
            Path(out_raster).write_text("dummy")

    monkeypatch.setattr(
        "hydromodpy.catchment.delineation.get_whitebox_backend",
        lambda: SimpleNamespace(raster=FakeRaster()),
    )

    zone = resolvers.resolve_zone_partic("seepage_clip", full_path=str(tmp_path), model_modflow=run)

    expected_clip = rasters_dir / "seepage_areas_t(0)_clip.tif"
    assert zone == str(expected_clip)
    assert expected_clip.exists()
    assert calls == {
        "in_raster": str(seepage_tif),
        "in_polygon": str(watershed_shp),
        "out_raster": str(expected_clip),
        "maintain_dimensions": True,
    }


def test_seepage_zone_needs_the_seepage_raster(tmp_path: Path):
    run = flow_run(catchment=SimpleNamespace(watershed_shp=str(tmp_path / "watershed.shp")))

    with pytest.raises(FileNotFoundError, match="missing seepage raster"):
        resolvers.resolve_zone_partic("seepage_clip", full_path=str(tmp_path), model_modflow=run)


def test_crs_is_the_raster_one_else_the_domain_support():
    domain = SimpleNamespace(surface_topo=SimpleNamespace(support=SimpleNamespace(crs="EPSG:2154")))
    run = flow_run(raster=SimpleNamespace(crs_proj="EPSG:32631"))

    assert resolvers.resolve_crs_proj(run, domain) == "EPSG:32631"
    assert resolvers.resolve_crs_proj(SimpleNamespace(), domain) == "EPSG:2154"
    assert resolvers.resolve_crs_proj(SimpleNamespace(), None) is None


def test_solver_without_a_model_has_no_raster_and_no_catchment():
    bare = SimpleNamespace()

    assert resolvers.get_raster(bare) is None
    assert resolvers.get_catchment(bare) is None
    assert resolvers.resolve_watershed_shp(bare) is None
    with pytest.raises(ValueError, match="Cannot resolve default zone_partic='domain'"):
        resolvers.resolve_domain_raster(bare)


def test_missing_name_file_is_rebuilt(tmp_path: Path):
    namefile = tmp_path / "test_model.nam"
    write_calls: list[str] = []

    class FakeMf:
        model_ws = "stale-workspace"
        namefile = "test_model.nam"

        def write_name_file(self) -> None:
            write_calls.append(self.model_ws)
            (tmp_path / "test_model.nam").write_text("dummy name file", encoding="utf-8")

    resolved = resolvers.ensure_modflow_name_file(
        full_path=str(tmp_path),
        model_name="test_model",
        model_modflow=SimpleNamespace(mf=FakeMf()),
    )

    assert resolved == str(namefile)
    assert namefile.exists()
    assert write_calls == [str(tmp_path)]
