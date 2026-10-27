"""The river network is switched on exactly when the mesh follows the rivers (rule D3).

A generated mesh that follows the rivers, a refinement zone on the height above
the stream, or a stream boundary on a mesh read from a file needs the network
traced from the DEM. A network switched on without its threshold is refused.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig, RiverNetworkConfig
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.planning.geographic import prepare_geographic_config_for_mesh


def _geographic(
    *, synthetic: bool = False, threshold: float | None = 0.5, enabled: bool = False
) -> GeographicConfig:
    network = RiverNetworkConfig(threshold_area_km2=threshold, enabled=enabled)
    base = GeographicConfig(source_mode="synthetic", river_network=network)
    # A standard config needs a catchment; only the source mode matters here.
    return base if synthetic else base.model_copy(update={"source_mode": "standard"})


def _voronoi_reading(path: str) -> MeshConfig:
    return MeshConfig(engine="voronoi", triangle={"path": path}, voronoi={"seeds": "triangulation"})


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_a_generated_mesh_that_follows_the_rivers_switches_the_network_on(engine: str) -> None:
    geographic = _geographic()
    updated = prepare_geographic_config_for_mesh(
        geographic, MeshConfig(engine=engine), active_bc=()
    )
    assert updated.river_network.enabled is True
    assert geographic.river_network.enabled is False


@pytest.mark.parametrize(
    ("mesh_cfg", "active_bc", "synthetic"),
    [
        (MeshConfig(engine="regular"), ("stream",), False),
        (MeshConfig(engine="triangle", families={"rivers": "none"}), (), False),
        (MeshConfig(engine="voronoi"), ("stream",), True),
        (_voronoi_reading("mesh.msh"), ("drain",), False),
    ],
    ids=["regular", "rivers-none", "synthetic", "file-without-stream"],
)
def test_the_network_stays_as_it_is(
    mesh_cfg: MeshConfig, active_bc: tuple[str, ...], synthetic: bool
) -> None:
    geographic = _geographic(synthetic=synthetic)
    updated = prepare_geographic_config_for_mesh(geographic, mesh_cfg, active_bc=active_bc)
    assert updated is geographic


def test_a_mesh_read_from_a_file_needs_the_network_for_a_stream_boundary() -> None:
    updated = prepare_geographic_config_for_mesh(
        _geographic(), _voronoi_reading("mesh.msh"), active_bc=(" Stream ",)
    )
    assert updated.river_network.enabled is True


def test_a_network_switched_on_without_threshold_is_refused() -> None:
    with pytest.raises(ConfigValidationError, match="threshold_area_km2") as caught:
        prepare_geographic_config_for_mesh(
            _geographic(threshold=None), MeshConfig(engine="triangle"), active_bc=()
        )
    assert 'mesh.engine = "triangle"' in str(caught.value)


def test_a_network_already_on_is_left_as_it_is() -> None:
    geographic = _geographic(enabled=True)

    assert (
        prepare_geographic_config_for_mesh(geographic, MeshConfig(engine="triangle"), active_bc=())
        is geographic
    )


_HAND = {"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}
_NO_RIVERS = {"rivers": "none", "geology": "none", "lakes": "none", "barriers": "none"}


def test_a_zone_on_the_height_above_the_stream_needs_the_traced_network() -> None:
    hand = MeshConfig(
        engine="voronoi", cell_size=80.0, families=_NO_RIVERS, refinement_zone=[_HAND]
    )
    bare = MeshConfig(engine="voronoi", cell_size=80.0, families=_NO_RIVERS)

    assert hand.requires_river_trace(active_bc=set(), synthetic=False) is True
    assert bare.requires_river_trace(active_bc=set(), synthetic=False) is False
    assert (
        MeshConfig(engine="regular", refinement_zone=[_HAND]).requires_river_trace(
            active_bc=set(), synthetic=False
        )
        is False
    )
    with pytest.raises(ConfigValidationError, match="where = 'height_above_stream'"):
        prepare_geographic_config_for_mesh(_geographic(threshold=None), hand, active_bc=())
