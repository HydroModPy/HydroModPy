"""A map rewritten at the same path moves the cache key of a network calibration.

The key held the path of ``stream_geometry_path`` and of
``minimal_stream_geometry_path``, never what the file holds. A map redrawn and
saved under the same name scored nothing new: every trial came back from the
cache with the cost of the old map. The key now holds the content of each map
file, with the sidecars of a shapefile, and only a document that names a map
carries it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.runners import state

pytestmark = pytest.mark.unit

PARAMETERS = {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}


def _network(**paths: Path) -> CalibrationConfig:
    output: dict[str, Any] = {
        "support": "network",
        **{key: str(value) for key, value in paths.items()},
    }
    return CalibrationConfig.model_validate(
        {
            "parameters": PARAMETERS,
            "outputs": {"net": output},
            "objective_blocks": [
                {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def _context(cfg: CalibrationConfig) -> dict[str, object]:
    return state.build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )


def _key(cfg: CalibrationConfig) -> str:
    return params_hash({"K": 1e-5}, context=_context(cfg))


def test_the_same_map_keeps_its_key(tmp_path: Path) -> None:
    streams = tmp_path / "streams.gpkg"
    streams.write_bytes(b"reaches v1")

    assert _key(_network(stream_geometry_path=streams)) == _key(
        _network(stream_geometry_path=streams)
    )


@pytest.mark.parametrize("field", ["stream_geometry_path", "minimal_stream_geometry_path"])
def test_a_map_rewritten_at_its_path_moves_the_key(tmp_path: Path, field: str) -> None:
    streams = tmp_path / "streams.gpkg"
    streams.write_bytes(b"reaches v1")
    paths = {"stream_geometry_path": streams}
    if field == "minimal_stream_geometry_path":
        paths[field] = tmp_path / "permanent.gpkg"
    target = paths[field]
    target.write_bytes(b"reaches v1")
    before = _key(_network(**paths))

    target.write_bytes(b"reaches v2")

    assert _key(_network(**paths)) != before


def test_the_attributes_of_a_shapefile_move_the_key(tmp_path: Path) -> None:
    streams = tmp_path / "streams.shp"
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        streams.with_suffix(suffix).write_bytes(b"part" + suffix.encode())
    before = _key(_network(stream_geometry_path=streams))

    streams.with_suffix(".dbf").write_bytes(b"other attributes")

    assert _key(_network(stream_geometry_path=streams)) != before


def test_a_document_that_names_no_map_carries_no_map_member() -> None:
    cfg = CalibrationConfig.model_validate(
        {
            "parameters": PARAMETERS,
            "outputs": {"q": {"support": "boundary", "variable": "discharge", "boundary_id": "o"}},
            "variable": "q",
        }
    )

    assert "observed_maps" not in _context(cfg)


def test_a_map_not_there_is_keyed_as_missing(tmp_path: Path) -> None:
    context = _context(_network(stream_geometry_path=tmp_path / "absent.gpkg"))

    assert context["observed_maps"] == {"net.stream_geometry_path": "missing"}
