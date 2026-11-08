"""Unit tests for Modpath runtime resolvers."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.model.domain.geometry import CatchmentGeometry, RasterGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_nwt.modpath import resolvers
from tests._helpers.model_factory import make_model


def _flow_run(*, raster=None, catchment=None) -> SimpleNamespace:
    """A MODFLOW-NWT solver object that keeps a ``Model`` with this raster and catchment."""
    geometry = Geometry(
        cells=None,
        domain=None,
        raster=None if raster is None else RasterGeometry.from_geographic(raster),
        catchment=(
            None if catchment is None else CatchmentGeometry.from_geographic(catchment, crs=None)
        ),
    )
    return SimpleNamespace(inputs=make_model(geometry=geometry))


def test_resolve_zone_partic_returns_domain_raster(
    tmp_path: Path,
) -> None:
    model_modflow = _flow_run(raster=SimpleNamespace(watershed_box_buff_dem="domain_raster.tif"))

    assert (
        resolvers.resolve_zone_partic(
            "domain",
            full_path=str(tmp_path),
            model_modflow=model_modflow,
        )
        == "domain_raster.tif"
    )


def test_resolve_zone_partic_clips_seepage_raster(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rasters_dir = tmp_path / "_postprocess" / "_rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)
    seepage_tif = rasters_dir / "seepage_areas_t(0).tif"
    seepage_tif.write_text("dummy")

    watershed_shp = tmp_path / "watershed.shp"
    watershed_shp.write_text("dummy")
    model_modflow = _flow_run(catchment=SimpleNamespace(watershed_shp=str(watershed_shp)))

    calls: dict[str, object] = {}

    class _FakeRaster:
        def clip_raster_to_polygon(
            self,
            in_raster: str,
            in_polygon: str,
            out_raster: str,
            maintain_dimensions: bool = True,
        ) -> None:
            calls["in_raster"] = in_raster
            calls["in_polygon"] = in_polygon
            calls["out_raster"] = out_raster
            calls["maintain_dimensions"] = maintain_dimensions
            Path(out_raster).write_text("dummy")

    class _FakeWhiteboxBackend:
        def __init__(self) -> None:
            self.raster = _FakeRaster()

    monkeypatch.setattr(
        "hydromodpy.catchment.delineation.get_whitebox_backend",
        lambda: _FakeWhiteboxBackend(),
    )

    resolved = resolvers.resolve_zone_partic(
        "seepage_clip",
        full_path=str(tmp_path),
        model_modflow=model_modflow,
    )

    expected_clip = tmp_path / "_postprocess" / "_rasters" / "seepage_areas_t(0)_clip.tif"
    assert resolved == str(expected_clip)
    assert expected_clip.exists()
    assert calls["in_raster"] == str(seepage_tif)
    assert calls["in_polygon"] == str(watershed_shp)
    assert calls["out_raster"] == str(expected_clip)
    assert calls["maintain_dimensions"] is True


def test_resolve_zone_partic_fails_when_seepage_raster_missing(
    tmp_path: Path,
) -> None:
    model_modflow = _flow_run(
        catchment=SimpleNamespace(watershed_shp=str(tmp_path / "watershed.shp"))
    )

    with pytest.raises(FileNotFoundError, match="missing seepage raster"):
        resolvers.resolve_zone_partic(
            "seepage_clip",
            full_path=str(tmp_path),
            model_modflow=model_modflow,
        )


def test_the_crs_is_the_raster_one_else_the_domain_support() -> None:
    support = SimpleNamespace(crs="EPSG:2154")
    domain = SimpleNamespace(surface_topo=SimpleNamespace(support=support))
    run = _flow_run(raster=SimpleNamespace(crs_proj="EPSG:32631"))

    assert resolvers.resolve_crs_proj(run, domain) == "EPSG:32631"
    assert resolvers.resolve_crs_proj(SimpleNamespace(), domain) == "EPSG:2154"
    assert resolvers.resolve_crs_proj(SimpleNamespace(), None) is None


def test_a_solver_without_a_model_has_no_raster_and_no_catchment() -> None:
    bare = SimpleNamespace()

    assert resolvers.get_raster(bare) is None
    assert resolvers.get_catchment(bare) is None
    assert resolvers.resolve_watershed_shp(bare) is None
    with pytest.raises(ValueError, match="Cannot resolve default zone_partic='domain'"):
        resolvers.resolve_domain_raster(bare)


def test_ensure_modflow_name_file_rebuilds_missing_namefile(
    tmp_path: Path,
) -> None:
    namefile_path = tmp_path / "test_model.nam"
    write_calls: list[str] = []

    class _FakeMf:
        def __init__(self) -> None:
            self.model_ws = "stale-workspace"
            self.namefile = "test_model.nam"

        def write_name_file(self) -> None:
            write_calls.append(self.model_ws)
            namefile_path.write_text("dummy name file", encoding="utf-8")

    model_modflow = SimpleNamespace(mf=_FakeMf())

    resolved = resolvers.ensure_modflow_name_file(
        full_path=str(tmp_path),
        model_name="test_model",
        model_modflow=model_modflow,
    )

    assert resolved == str(namefile_path)
    assert namefile_path.exists()
    assert write_calls == [str(tmp_path)]
