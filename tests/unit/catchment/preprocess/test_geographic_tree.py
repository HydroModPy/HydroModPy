"""The geographic tree declaration: what a runtime still holds, once and in order."""

from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import LineString

from hydromodpy.catchment.preprocess.geographic_tree import geographic_artifact_paths
from tests._helpers.geographic_cases import touch_artifact, write_features


def test_a_runtime_declares_every_file_it_still_holds_once_and_in_order(tmp_path: Path) -> None:
    geographic_path, correcflow = tmp_path / "geographic", tmp_path / "correcflow"
    watershed = write_features(geographic_path / "watershed.shp", [LineString([(0, 0), (1, 1)])])
    for path in (correcflow / "dem_acc_cells.tif", correcflow / "dem_fill.tif"):
        touch_artifact(path)
    runtime = SimpleNamespace(
        geographic_path=str(geographic_path),
        correcflow_path=str(correcflow),
        watershed_shp=str(watershed),
        box_buff=str(watershed),
        watershed_dem=str(tmp_path / "never_written.tif"),
        watershed_contour_shp="",
        _flow_products=SimpleNamespace(correc=str(correcflow / "dem_fill.tif")),
    )
    found = geographic_artifact_paths(runtime)
    sidecars = {p.suffix for p in found if p.stem == "watershed"}
    assert {".shp", ".shx", ".dbf", ".prj"} <= sidecars
    assert correcflow / "dem_acc_cells.tif" in found
    assert correcflow / "dem_fill.tif" in found
    assert tmp_path / "never_written.tif" not in found
    assert list(found) == sorted(set(found))
    assert geographic_artifact_paths(None) == ()


def test_a_provided_dem_is_an_input_not_a_written_file(tmp_path: Path) -> None:
    correcflow = tmp_path / "correcflow"
    correcflow.mkdir(parents=True, exist_ok=True)
    for name in ("user_dem.tif", "dem_direc.tif", "dem_acc.tif"):
        touch_artifact(correcflow / name)
    runtime = SimpleNamespace(
        geographic_path=str(tmp_path / "geographic"),
        correcflow_path=str(correcflow),
        _flow_products=SimpleNamespace(
            correc=str(correcflow / "user_dem.tif"),
            direc=str(correcflow / "dem_direc.tif"),
            acc=str(correcflow / "dem_acc.tif"),
            accumulation=SimpleNamespace(
                directions=SimpleNamespace(conditioned_dem=SimpleNamespace(method="provided"))
            ),
        ),
    )
    found = geographic_artifact_paths(runtime)
    assert correcflow / "dem_direc.tif" in found
    assert correcflow / "dem_acc.tif" in found
    assert correcflow / "user_dem.tif" not in found
