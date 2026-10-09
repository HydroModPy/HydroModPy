"""A bare name resolves to a live run before a trashed one.

``if_exists = "replace"`` trashes the old run and keeps its name, so
``cat["x"]`` used to return the run that had just been replaced.
"""

from __future__ import annotations

import uuid

from tests._helpers.fixtures_catalog import simulation_catalog


def _run(cat, name: str, *, if_exists: str = "version") -> str:
    sid = str(uuid.uuid4())
    cat.register_simulation(sid, project="p", solver="modflow6", name=name, if_exists=if_exists)
    cat.finalize(sid, "completed")
    return sid


def test_a_replaced_name_resolves_to_the_run_that_replaced_it(tmp_path) -> None:
    with simulation_catalog(tmp_path / "ws") as cat:
        old = _run(cat, "x")
        new = _run(cat, "x", if_exists="replace")
        assert cat["x"].status == "completed"
        assert cat.resolve("x") == new
        # The trashed run is still reached by its id.
        assert cat.resolve(old) == old


def test_a_trashed_name_is_reached_when_nothing_live_holds_it(tmp_path) -> None:
    with simulation_catalog(tmp_path / "ws") as cat:
        old = _run(cat, "x")
        new = _run(cat, "x", if_exists="replace")
        cat.trash(new)
        assert cat.resolve("x") == old


def test_a_live_first_version_keeps_its_name(tmp_path) -> None:
    with simulation_catalog(tmp_path / "ws") as cat:
        first = _run(cat, "x")
        _run(cat, "x")
        assert cat.resolve("x") == first
