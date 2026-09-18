"""A resume rebuilds the geographic runtime instead of delineating it again.

Finding A1: ``BuildGeographicStep.rebuild_state`` used to call ``run()``, so a
process that died after the delineation paid for the whole Whitebox chain a
second time. The test drives the step twice on one workspace: the second pass
gets a context that knows nothing, and the regional flow products - the
expensive half - are replaced by a bomb.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "naizin_rebuild"

[workspace]
project_root = "{root}"

[geographic]
crs_project = "EPSG:2154"
dem_correc_type = "breach"
write_intermediates = true

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "{dem}"
x_outlet = 265611.933
y_outlet = 6784182.776
snap_dist = "50 m"
buff_area = "20%"

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = []

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"
"""


def _state_for(config_path: Path):
    """Return a pipeline state holding a context that has built nothing yet."""
    from hydromodpy.workflow.internals.state import PipelineState
    from hydromodpy.workflow.steps.resolve import ResolveStep
    from hydromodpy.workflow.steps.validate import ValidateStep

    state = PipelineState(run_id="naizin_rebuild", data={"config_path": config_path})
    return ResolveStep().run(ValidateStep().run(state))


@pytest.fixture(scope="module")
def built_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the geographic step once on a throwaway workspace."""
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    root = tmp_path_factory.mktemp("geographic_rebuild")
    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=root.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )
    BuildGeographicStep().run(_state_for(config_path))
    return root


def test_the_step_declares_the_tree_it_wrote(built_workspace: Path) -> None:
    """``artifacts()`` names existing files, description first."""
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    step = BuildGeographicStep()
    state = step.run(_state_for(built_workspace / "project.toml"))
    declared = step.artifacts(state)

    assert declared, "the geographic step declares nothing"
    assert all(Path(item).is_file() for item in declared)
    names = {Path(item).name for item in declared}
    assert "_geographic_cache_manifest.json" in names
    assert "dem_breach.tif" in names, "the conditioned DEM is not declared"
    assert {"watershed.shp", "watershed.shx", "watershed.dbf"} <= names


def test_the_step_declares_every_file_a_rebuild_reads(built_workspace: Path) -> None:
    """Nothing the reuse check requires is left out of the declaration.

    ``watershed_buff.shp`` is named by no public attribute of either runtime
    and was missing from the declaration, so the digest of the step did not
    cover a file a resume refuses to run without.
    """
    from hydromodpy.spatial.geographic.pipeline import (
        _raster_products_from_paths,
        _required_geographic_cache_artifacts,
    )
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    step = BuildGeographicStep()
    state = step.run(_state_for(built_workspace / "project.toml"))
    declared = {Path(item) for item in step.artifacts(state)}

    ctx = state.get("ctx")
    paths = ctx.setup.geographic._paths
    required = _required_geographic_cache_artifacts(
        config=ctx.cfg.geographic,
        paths=paths,
        raster_products=_raster_products_from_paths(paths),
    )
    missing = [str(item) for item in required if Path(item) not in declared]
    assert not missing, f"required by a reuse but not declared: {missing}"


def test_a_rebuild_does_not_delineate_again(
    built_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rebuild reads the tree; touching Whitebox at all fails the test."""
    from hydromodpy.spatial.geographic import pipeline as geographic_pipeline
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("the rebuild recomputed the regional flow products")

    monkeypatch.setattr(geographic_pipeline, "build_regional_flow_products", _explode)

    rebuilt = BuildGeographicStep().rebuild_state(
        prior_state=_state_for(built_workspace / "project.toml"),
        workspace=built_workspace,
        run_id="naizin_rebuild",
    )
    geographic = rebuilt.get("ctx").setup.geographic
    assert geographic is not None
    assert geographic.catch_area == pytest.approx(1.594375, rel=1e-9)


def test_a_rebuild_reports_the_outlet_the_delineation_ran_from(
    built_workspace: Path,
) -> None:
    """The snapped outlet survives the rebuild: v1 descriptions lost it."""
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    step = BuildGeographicStep()
    built = step.run(_state_for(built_workspace / "project.toml"))
    rebuilt = step.rebuild_state(
        prior_state=_state_for(built_workspace / "project.toml"),
        workspace=built_workspace,
        run_id="naizin_rebuild",
    )

    original = built.get("ctx").setup.geographic
    restored = rebuilt.get("ctx").setup.geographic
    assert restored.x_outlet_snapped == original.x_outlet_snapped
    assert restored.y_outlet_snapped == original.y_outlet_snapped
    assert restored.outlet_snap_distance_m == pytest.approx(original.outlet_snap_distance_m)
    assert restored.x_outlet_snapped != restored.x_outlet


def test_a_missing_tree_falls_back_to_a_full_build(
    tmp_path: Path,
) -> None:
    """A rebuild with nothing on disk still produces the runtime."""
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )
    rebuilt = BuildGeographicStep().rebuild_state(
        prior_state=_state_for(config_path),
        workspace=tmp_path,
        run_id="naizin_rebuild",
    )
    assert rebuilt.get("ctx").setup.geographic is not None


def test_the_fingerprint_sees_a_conditioning_vector_edited_in_place(tmp_path: Path) -> None:
    """A stream-enforcement vector rewritten in place invalidates the tree.

    The routing DEM is carved with these vectors, so every product below them
    changes when one does, without a single config value changing. A resume now
    forces the reuse, which is what makes the blind spot reachable.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
    from hydromodpy.spatial.geographic.pipeline import _geographic_cache_fingerprint

    network = tmp_path / "streams.gpkg"

    def _write(offset: float) -> None:
        gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[LineString([(0.0, offset), (100.0, offset + 100.0)])],
            crs="EPSG:2154",
        ).to_file(network, driver="GPKG")

    payload = {
        "source_mode": "standard",
        "catchment": {"catch_def": "dem", "dem_init_path": str(DEM)},
        "enforce_streams": {"enabled": True, "stream_geometry_path": str(network)},
    }

    _write(0.0)
    before = _geographic_cache_fingerprint(GeographicConfig.model_validate(payload))
    _write(500.0)
    after = _geographic_cache_fingerprint(GeographicConfig.model_validate(payload))

    assert before != after
