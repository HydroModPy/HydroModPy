"""The river network is switched on exactly when the mesh follows the rivers (rule D3).

A generated mesh that follows the rivers, a refinement zone on the height above
the stream, or a stream boundary on a mesh read from a file needs the network
traced from the DEM. The config refuses such a mesh without a threshold when it
loads, so the switch only turns the network on.

A new geographic drops the whole mesh with it, summary included.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.catchment.algorithms.river_network_config import (
    RiverNetworkConfig,
    river_network_for_the_mesh,
)
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.project import phases


def _geographic(*, synthetic: bool = False, enabled: bool = False) -> GeographicConfig:
    network = RiverNetworkConfig(threshold_area_km2=0.5, enabled=enabled)
    base = GeographicConfig(source_mode="synthetic", river_network=network)
    # A standard config needs a catchment; only the source mode matters here.
    return base if synthetic else base.model_copy(update={"source_mode": "standard"})


def _cfg(
    geographic: GeographicConfig, mesh: MeshConfig | None, active_bc: tuple[str, ...] = ()
) -> SimpleNamespace:
    return SimpleNamespace(
        geographic=geographic, mesh=mesh, flow=SimpleNamespace(active_bc=list(active_bc))
    )


def _voronoi_reading(path: str) -> MeshConfig:
    return MeshConfig(engine="voronoi", triangle={"path": path}, voronoi={"seeds": "triangulation"})


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_a_generated_mesh_that_follows_the_rivers_switches_the_network_on(engine: str) -> None:
    geographic = _geographic()

    updated = river_network_for_the_mesh(_cfg(geographic, MeshConfig(engine=engine)))

    assert updated.river_network.enabled is True
    assert geographic.river_network.enabled is False


def test_a_zone_on_the_height_above_the_stream_switches_the_network_on() -> None:
    hand = MeshConfig(
        engine="voronoi",
        cell_size=80.0,
        families={"rivers": "none", "geology": "none", "lakes": "none", "barriers": "none"},
        refinement_zone=[{"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}],
    )

    assert river_network_for_the_mesh(_cfg(_geographic(), hand)).river_network.enabled is True


@pytest.mark.parametrize(
    ("mesh_cfg", "active_bc", "synthetic"),
    [
        (None, ("stream",), False),
        (MeshConfig(engine="regular"), ("stream",), False),
        (MeshConfig(engine="triangle", families={"rivers": "none"}), (), False),
        (MeshConfig(engine="voronoi"), ("stream",), True),
        (_voronoi_reading("mesh.msh"), ("drain",), False),
    ],
    ids=["no-mesh", "regular", "rivers-none", "synthetic", "file-without-stream"],
)
def test_the_network_stays_as_it_is(
    mesh_cfg: MeshConfig | None, active_bc: tuple[str, ...], synthetic: bool
) -> None:
    geographic = _geographic(synthetic=synthetic)

    assert river_network_for_the_mesh(_cfg(geographic, mesh_cfg, active_bc)) is geographic


def test_a_mesh_read_from_a_file_needs_the_network_for_a_stream_boundary() -> None:
    updated = river_network_for_the_mesh(
        _cfg(_geographic(), _voronoi_reading("mesh.msh"), (" Stream ",))
    )

    assert updated.river_network.enabled is True


def test_a_network_already_on_is_left_as_it_is() -> None:
    geographic = _geographic(enabled=True)

    assert river_network_for_the_mesh(_cfg(geographic, MeshConfig(engine="triangle"))) is geographic


def _project() -> SimpleNamespace:
    setup = SimpleNamespace(cell_mesh=object(), mesh_summary={"engine": "regular"})
    ctx = SimpleNamespace(
        setup=setup,
        loaded_data=SimpleNamespace(loaded_plan_types=("dem",)),
        data_plan=SimpleNamespace(types=()),
    )
    return SimpleNamespace(_ctx=ctx, _phase="mesh", _data_loaded={"dem"})


def _drop_with_build_geographic(project: SimpleNamespace) -> None:
    phases.build_geographic(project)


def _drop_with_adopted_pipeline_phase(project: SimpleNamespace) -> None:
    phases.adopt_pipeline_phase(project, ["build_geographic"])


@pytest.mark.parametrize("drop", [_drop_with_build_geographic, _drop_with_adopted_pipeline_phase])
def test_the_mesh_summary_goes_with_the_mesh(drop) -> None:
    project = _project()

    drop(project)

    setup = project._ctx.setup
    assert setup.cell_mesh is None
    assert setup.mesh_summary is None
    assert project._phase == "geographic"
