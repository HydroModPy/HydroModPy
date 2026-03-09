from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.geographic.core.flow_products import FlowProducts
from hydromodpy.solver.modflow_common.routing_context import (
    SolverRoutingContext,
    build_solver_routing_context,
)


def test_build_solver_routing_context_wraps_flow_products(monkeypatch, tmp_path: Path):
    dem_path = tmp_path / "solver_dem.tif"
    dem_path.write_text("stub", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_build_regional_flow_products(
        *,
        dem_init_path,
        dem_out_dir_path,
        dem_correc_type,
        crs_project,
        wbt_tool,
    ):
        captured.update(
            {
                "dem_init_path": str(dem_init_path),
                "dem_out_dir_path": str(dem_out_dir_path),
                "dem_correc_type": dem_correc_type,
                "crs_project": crs_project,
                "wbt_tool": wbt_tool,
            }
        )
        return FlowProducts(
            correc=str(Path(dem_out_dir_path) / "dem_breach.tif"),
            direc=str(Path(dem_out_dir_path) / "dem_direc.tif"),
            acc=str(Path(dem_out_dir_path) / "dem_acc.tif"),
        )

    monkeypatch.setattr(
        "hydromodpy.solver.modflow_common.routing_context.build_regional_flow_products",
        _fake_build_regional_flow_products,
    )

    ctx = build_solver_routing_context(
        dem_path=dem_path,
        output_dir=tmp_path / "routing",
        dem_correc_type="breach",
        crs_project="EPSG:2154",
        wbt_tool="fake-wbt",
    )

    assert isinstance(ctx, SolverRoutingContext)
    assert ctx.dem_path == str(dem_path)
    assert ctx.correc_path.endswith("dem_breach.tif")
    assert ctx.direc_path.endswith("dem_direc.tif")
    assert ctx.acc_path.endswith("dem_acc.tif")
    assert captured["dem_init_path"] == str(dem_path)
    assert captured["dem_correc_type"] == "breach"
    assert captured["crs_project"] == "EPSG:2154"
    assert captured["wbt_tool"] == "fake-wbt"


def test_build_solver_routing_context_requires_existing_dem(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Solver DEM raster not found"):
        build_solver_routing_context(
            dem_path=tmp_path / "missing_solver_dem.tif",
            output_dir=tmp_path / "routing",
            dem_correc_type="breach",
        )
