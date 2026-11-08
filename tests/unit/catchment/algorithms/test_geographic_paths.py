"""The file names of a geographic run."""

from pathlib import Path

from hydromodpy.catchment.algorithms.geographic_paths import build_geographic_paths
from hydromodpy.core.state.scratch import preprocessing_dir


def test_the_paths_name_every_river_network_output() -> None:
    paths = build_geographic_paths(Path("dummy_out"))
    assert paths.river_streams_tif.endswith("river_streams.tif")
    assert paths.river_streams_pruned_tif.endswith("river_streams_pruned.tif")
    assert paths.river_stream_order_strahler_tif.endswith("river_stream_order_strahler.tif")
    assert paths.river_stream_link_id_tif.endswith("river_stream_link_id.tif")
    assert paths.hydrographic_network_generated_shp.endswith("river_network.shp")
    assert paths.hydrographic_network_generated_summary_json.endswith("river_network_summary.json")


def test_the_tree_sits_in_the_declared_stable_folder_or_in_the_preprocessing_one(tmp_path) -> None:
    declared = build_geographic_paths(tmp_path / "out", stable_folder=tmp_path / "stable")
    default = build_geographic_paths(tmp_path / "out")
    assert Path(declared.stable_folder) == tmp_path / "stable"
    assert Path(default.stable_folder) == preprocessing_dir(tmp_path / "out")
    assert Path(declared.geographic_path).parent == tmp_path / "stable"
