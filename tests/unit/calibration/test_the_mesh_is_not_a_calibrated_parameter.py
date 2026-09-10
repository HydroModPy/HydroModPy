"""A mesh setting is not a parameter a search may move.

The mesh appears in the configuration next to the hydraulic properties, and a
calibration parameter takes any dotted path, so nothing stopped a file from
searching over a mesh resolution. Two reasons it must not:

The criterion moves with the mesh. The validity bound of the stream-network
method is normalised by cell size precisely because the distances it measures
shrink as the mesh refines. Optimising the mesh against that criterion is
circular: the search improves the number by changing the yardstick.

And a mesh setting does not reach the mesh through this route anyway. The mesh
step reads the mesh sections resolved once from the raw file, not the per-trial
configuration, so a value written into a trial's config would leave the mesh
exactly as it was and the trial would score the same model.

The route for a mesh question is a sweep: one run per mesh, compared, and read
for convergence rather than for a best score.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace


def _declaration(path: str) -> dict[str, dict[str, object]]:
    return {"m": {"bounds": [50.0, 500.0], "path": path}}


@pytest.mark.parametrize(
    "path",
    [
        "mesh_catchment.resolution",
        "mesh_catchment.refinement.stream_buffer_m",
        "mesh_input.mesh_path",
    ],
)
def test_a_mesh_path_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match="mesh"):
        ParameterSpace.from_toml_mapping(_declaration(path))


def test_the_refusal_points_at_the_route_that_works() -> None:
    with pytest.raises(ValueError) as caught:
        ParameterSpace.from_toml_mapping(_declaration("mesh_catchment.resolution"))

    message = str(caught.value)
    assert "mesh_catchment.resolution" in message
    assert "compare" in message


def test_a_target_naming_the_mesh_is_refused_too() -> None:
    with pytest.raises(ValueError, match="mesh"):
        ParameterSpace.from_toml_mapping(
            {"m": {"bounds": [50.0, 500.0], "target": "mesh_catchment.resolution"}}
        )


def test_a_hydraulic_path_is_untouched() -> None:
    space = ParameterSpace.from_toml_mapping(
        {"K": {"bounds": [1e-8, 1e-2], "transform": "log", "path": "flow.param.K.field.value"}}
    )

    assert [param.name for param in space] == ["K"]


def test_a_path_that_merely_contains_the_word_is_untouched() -> None:
    """The refusal is on the section, not on a substring."""
    space = ParameterSpace.from_toml_mapping(
        {"c": {"bounds": [1.0, 2.0], "path": "flow.param.mesh_factor.field.value"}}
    )

    assert [param.name for param in space] == ["c"]
