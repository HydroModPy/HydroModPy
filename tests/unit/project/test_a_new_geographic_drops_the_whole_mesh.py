"""A rebuilt geographic drops the cell mesh and the summary that describes it.

A summary kept beside a new mesh names the request, the cache entry and the
quality of the old one.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.project import phases


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
