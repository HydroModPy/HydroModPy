"""A run asked by an id that is not a UUID is not found, it does not crash the reader.

The index keys ``simulations`` and ``tags`` on a UUID column. Compared as is,
a free-text id made DuckDB raise a conversion error from the depths of the
row lookup; compared as text, it is a run the index does not hold.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.errors import RunNotFoundError
from hydromodpy.results.run import Run
from tests._helpers.sealed_runs import make_project, seal_run


def test_a_free_text_id_reads_as_a_run_the_index_does_not_hold(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    sim_id = seal_run(project, "alpha")
    rebuild_index(project)
    catalog = Catalog(project)
    try:
        assert Run(sim_id, catalog).name == "alpha"
        with pytest.raises(RunNotFoundError):
            Run("not-a-uuid", catalog)._load_row()  # noqa: SLF001 - the row lookup itself
    finally:
        catalog.close()
