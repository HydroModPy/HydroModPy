"""A rebuild reads the terrain from the store and delineates the catchment again.

The expensive half of the geographic step is the conditioning of the DEM and
its D8 accumulation. A rebuild reads that terrain back from the product store
and only redoes the delineation, which is deterministic. The test drives the
step twice on one workspace: the second pass gets a context that knows nothing,
and the conditioning engine is replaced by a bomb.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

PROJECT_TOML = """
[workflow]
mode = "simulation"

[site]
name = "naizin"

[simulation]
name = "naizin_rebuild"

[workspace]

[geographic]
crs_project = "EPSG:2154"
dem_correc_type = "breach"
write_intermediates = true

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 265611.933
y_outlet = 6784182.776
snap_dist = "50 m"
buff_area = "20%"

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = ["dem"]

[[data.dem.sources]]
source = "file"
path = "{dem}"

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"

[flow.bc.drainage]

[flow.sinks_sources.recharge]
"""


def _state_for(config_path: Path):
    """Return a pipeline state holding a context that has built nothing yet."""
    from hydromodpy.workflow.state import PipelineState
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
    """``artifacts()`` names the geographic tree, no manifest left behind."""
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    step = BuildGeographicStep()
    state = step.run(_state_for(built_workspace / "project.toml"))
    declared = step.artifacts(state)

    assert declared, "the geographic step declares nothing"
    assert all(Path(item).is_file() for item in declared)
    names = {Path(item).name for item in declared}
    assert "_geographic_cache_manifest.json" not in names
    assert "dem_breach.tif" in names, "the conditioned DEM is not declared"
    assert {"watershed.shp", "watershed.shx", "watershed.dbf"} <= names


def test_the_step_declares_every_file_a_rebuild_reads(built_workspace: Path) -> None:
    """The declaration is the geographic tree itself, unnamed files included.

    ``watershed_buff.shp`` is named by no public attribute of either runtime
    and was missing from the old manifest, so a rebuild read a file the
    declaration did not cover. The tree lists it from its folder attribute.
    """
    from hydromodpy.catchment.preprocess.geographic_tree import geographic_artifact_paths
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    step = BuildGeographicStep()
    state = step.run(_state_for(built_workspace / "project.toml"))
    geographic = state.get("ctx").setup.geographic

    declared = {Path(item) for item in step.artifacts(state)}
    tree = {Path(item) for item in geographic_artifact_paths(geographic)}
    assert declared == tree
    names = {path.name for path in declared}
    assert "watershed_buff.shp" in names
    assert {"watershed.shp", "watershed.shx", "watershed.dbf"} <= names


def test_a_rebuild_does_not_condition_again(
    built_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rebuild reads the terrain from the store; touching condition_dem fails."""
    from hydromodpy.catchment.terrain.whitebox_engine import WhiteboxTerrainEngine
    from hydromodpy.workflow.steps.setup import BuildGeographicStep

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("the rebuild conditioned the DEM again")

    monkeypatch.setattr(WhiteboxTerrainEngine, "condition_dem", _explode)

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


def test_a_missing_product_falls_back_to_a_full_build(
    tmp_path: Path,
) -> None:
    """A rebuild with nothing in the store still produces the runtime."""
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


def test_the_key_sees_the_notched_soil() -> None:
    """The notch edits the routed DEM, so its product key differs from the plain one.

    The store never writes over a product, so a run on a notched soil asks for
    ``terrain_notched``, keyed by the digest of the notched DEM.
    """
    from hydromodpy.catchment.algorithms.flow_products import TerrainRequest
    from hydromodpy.catchment.algorithms.terrain_stored import SCHEMA_VERSION
    from hydromodpy.results.products.key import product_key

    def _request(dem_sha256: str, notched: bool) -> TerrainRequest:
        return TerrainRequest(
            dem=Path("dem.tif"),
            dem_sha256=dem_sha256,
            state="raw",
            method="fill",
            capped_breach=None,
            crs_project="EPSG:2154",
            engine={"engine": "whitebox_workflows"},
            notched=notched,
            out_dir=Path("out"),
        )

    def _key(request: TerrainRequest) -> str:
        kind = "terrain_notched" if request.notched else "terrain"
        return product_key(
            kind,
            codec=SCHEMA_VERSION,
            package="catchment",
            inputs={"dem": request.dem_sha256},
            processing=request.processing(),
            engine=dict(request.engine),
        )

    plain = _key(_request("a" * 64, notched=False))
    notched = _key(_request("b" * 64, notched=True))
    assert notched != plain
