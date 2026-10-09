"""A ``Run`` keeps reading after the catalog that made it was closed.

A ``Project`` closes its catalog at the end of its ``with`` block, and every
``Run`` taken from it used to fail with ``Connection already closed``.
"""

from __future__ import annotations

import uuid

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import Run


def test_a_run_reopens_a_closed_catalog(tmp_path) -> None:
    cat = Catalog(tmp_path / "ws")
    sid = str(uuid.uuid4())
    cat.register_simulation(sid, project="p", solver="modflow6", name="x")
    cat.finalize(sid, "completed")
    run = Run(sid, cat)
    group = cat.find(project="p")
    cat.close()
    assert cat.closed

    assert run.name == "x"
    assert run.status == "completed"
    assert group[0].name == "x"
    assert run._catalog is not cat
    run._catalog.close()


def test_the_reopened_catalog_is_read_only(tmp_path) -> None:
    """Read-only like ``hmp.open``: DuckDB refuses two modes in one process."""
    import hydromodpy as hmp

    root = tmp_path / "ws"
    writable = Catalog(root)
    sid = str(uuid.uuid4())
    writable.register_simulation(sid, project="p", solver="modflow6", name="x")
    run = Run(sid, writable)
    writable.close()
    assert run.name == "x"
    assert run._catalog._read_only is True
    # A reader opened next in the same process works beside it.
    reader = hmp.open(root)
    assert reader[sid].name == "x"
    reader.close()
    run._catalog.close()


def test_an_old_snapshot_names_the_raw_mapping(tmp_path, monkeypatch) -> None:
    """A snapshot this version no longer validates says where the raw dict is."""
    import pytest

    with Catalog(tmp_path / "ws") as cat:
        sid = str(uuid.uuid4())
        cat.register_simulation(sid, project="p", solver="modflow6", name="x")
        run = Run(sid, cat)
        monkeypatch.setattr(Run, "config_snapshot", property(lambda self: {"snap_streams": 1}))
        with pytest.raises(ValueError, match="run.config_snapshot"):
            _ = run.hydromodpy_config
