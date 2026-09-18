"""The catalog of a run is a scope, not a field.

``WorkflowContext`` carried a live ``Catalog`` until F8b. These tests pin what
replaced it: a question about the run (does it write an index at all?) and a
scope that opens a handle and closes it before the caller returns.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.results.catalog import Catalog
from hydromodpy.workflow.run_catalog import run_catalog, run_is_catalogued


def _ctx(*, save_catalog: bool, lightweight: bool, workspace: object) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=save_catalog))
            )
        ),
        effective_results_config=None,
        execution=SimpleNamespace(lightweight=lightweight),
        setup=SimpleNamespace(workspace=workspace),
    )


def test_the_context_carries_no_catalog_handle() -> None:
    """The field is gone, not renamed: nothing on the context holds a connection."""
    fields = {f for f in WorkflowContext.__dataclass_fields__}
    assert "store" not in fields


def test_a_run_that_writes_an_index_is_catalogued() -> None:
    assert run_is_catalogued(_ctx(save_catalog=True, lightweight=False, workspace=object()))


@pytest.mark.parametrize(
    ("save_catalog", "lightweight", "workspace"),
    [
        (False, False, object()),
        (True, True, object()),
        (True, False, None),
    ],
)
def test_a_run_without_an_index_is_not_catalogued(save_catalog, lightweight, workspace) -> None:
    ctx = _ctx(save_catalog=save_catalog, lightweight=lightweight, workspace=workspace)
    assert not run_is_catalogued(ctx)


def test_the_scope_closes_the_handle_it_opened(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    workspace = SimpleNamespace(
        project_root=project_root,
        catalog_path=project_root / ".hmp" / "index.duckdb",
        runs_dir=project_root / "runs",
    )
    ctx = _ctx(save_catalog=True, lightweight=False, workspace=workspace)

    with run_catalog(ctx) as store:
        assert isinstance(store, Catalog)
        store.backend.fetch_one("SELECT count(*) FROM simulations")

    # A closed CatalogConnection refuses further statements; that is the proof
    # the scope ended the handle rather than handing it on.
    with pytest.raises(Exception, match="[Cc]losed"):
        store.backend.fetch_one("SELECT count(*) FROM simulations")


def test_a_run_without_a_workspace_cannot_open_a_catalog() -> None:
    ctx = _ctx(save_catalog=True, lightweight=False, workspace=None)
    with pytest.raises(PipelineError, match="workspace is required"):
        with run_catalog(ctx):
            pass
