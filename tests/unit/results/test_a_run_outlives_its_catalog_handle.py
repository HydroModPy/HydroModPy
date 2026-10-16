"""A ``Run`` keeps reading after the catalog that made it was closed.

A ``Project`` closes its catalog at the end of its ``with`` block, and every
``Run`` taken from it used to fail with ``Connection already closed``. The run
reopens a reader on the same index instead.
"""

from __future__ import annotations

from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.run import Run
from tests._helpers.sealed_runs import make_project, seal_run


def test_a_run_reopens_a_closed_catalog(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "x")
    rebuild_index(root)
    cat = Catalog(root)
    run = Run(sid, cat)
    group = cat.find(project="demo")
    cat.close()
    assert cat.closed

    assert run.name == "x"
    assert run.status == "completed"
    assert group[0].name == "x"
    assert run._catalog is not cat
    assert run._catalog.closed is False
    run._catalog.close()


def test_two_readers_of_one_index_coexist(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "x")
    rebuild_index(root)
    first = Catalog(root)
    run = Run(sid, first)
    first.close()
    assert run.name == "x"
    reader = Catalog(root)
    assert reader[sid].name == "x"
    reader.close()
    run._catalog.close()
