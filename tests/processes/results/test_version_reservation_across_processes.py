"""Two processes that reserve one run name never get the same version."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.results.catalog.registration import reserve_version_dirname


def _names(tree: Path) -> list[str]:
    return sorted(entry.name for entry in tree.iterdir())


_RESERVATIONS_PER_PROCESS = 12


def _reserve_many(project_root: str, barrier, queue) -> None:
    """Child process: wait for the sibling, then reserve the same run name repeatedly."""
    barrier.wait()
    names = [
        reserve_version_dirname(Path(project_root), "run", "case").name
        for _ in range(_RESERVATIONS_PER_PROCESS)
    ]
    queue.put(names)


def test_two_processes_reserving_one_name_never_get_the_same_version(tmp_path):
    reserve_version_dirname(tmp_path, "run", "case")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(target=_reserve_many, args=(str(tmp_path), barrier, queue))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=120) for _ in workers]
    for worker in workers:
        worker.join(timeout=120)
        assert worker.exitcode == 0

    reserved = [name for names in results for name in names]
    expected = {f"case.v{n}" for n in range(2, 2 + 2 * _RESERVATIONS_PER_PROCESS)}
    assert len(reserved) == len(set(reserved)), "a version was given out twice"
    assert set(reserved) == expected
    assert _names(tmp_path / RUNS_DIRNAME) == sorted({"case", *expected})
