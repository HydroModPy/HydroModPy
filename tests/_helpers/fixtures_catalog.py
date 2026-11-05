"""Open the index reader over the runs sealed under a test project.

A test writes and seals its runs on disk first, through
``tests/_helpers/run_stores.py`` or ``tests/_helpers/sealed_runs.py``. This
helper then rebuilds the index from the tree, the way ``hmp catalog reindex``
does, and opens :class:`~hydromodpy.results.catalog.Catalog` over it. The
reader writes nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project


@contextmanager
def simulation_catalog(project: Path) -> Iterator[Catalog]:
    """Index what *project* holds on disk, open the reader, close it after the test."""
    if not (project / PROJECT_MARKER_FILENAME).is_file():
        make_project(project)
    rebuild_index(project)
    cat = Catalog(project)
    try:
        yield cat
    finally:
        cat.close()
