"""The file names of a geographic run."""

from pathlib import Path

from hydromodpy.catchment.algorithms.geographic_paths import build_geographic_paths
from hydromodpy.core.state.scratch import preprocessing_dir


def test_stable_folder(tmp_path) -> None:
    declared = build_geographic_paths(tmp_path / "out", stable_folder=tmp_path / "stable")
    default = build_geographic_paths(tmp_path / "out")
    assert Path(declared.stable_folder) == tmp_path / "stable"
    assert Path(default.stable_folder) == preprocessing_dir(tmp_path / "out")
    assert Path(declared.geographic_path).parent == tmp_path / "stable"
