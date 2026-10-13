"""A rebuilt geographic drops the cell mesh, its bundle and its support together.

A support kept beside a new mesh describes the cells of the old one: the next
reload refuses the pair and the mesh step silently meshes again.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.project import phases


def _project() -> SimpleNamespace:
    setup = SimpleNamespace(cell_mesh=object(), mesh_bundle=object(), mesh_support=object())
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
def test_the_mesh_support_goes_with_the_mesh(drop) -> None:
    project = _project()

    drop(project)

    setup = project._ctx.setup
    assert setup.cell_mesh is None
    assert setup.mesh_bundle is None
    assert setup.mesh_support is None
    assert project._phase == "geographic"
