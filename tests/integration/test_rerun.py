"""``keep_solver_files`` is durable: a later run of the project leaves ``solver/`` alone.

The solver scratch of a run is swept when the run ends or when its process is
gone. What the first run kept moves into ``runs/<run>/solver/``, which the next
run of the same project never touches.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._helpers.island_project import island_toml, run_island

pytestmark = [
    pytest.mark.integration,
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.slow,
    pytest.mark.allow_subprocess,
]


def test_the_solver_files_of_the_first_run_survive_the_second(tmp_path: Path) -> None:
    first = tmp_path / "first.toml"
    first.write_text(island_toml("first", keep_solver_files=True), encoding="utf-8")
    run_island(first)
    kept = tmp_path / "runs" / "first" / "solver"
    before = sorted(str(p.relative_to(kept)) for p in kept.rglob("*") if p.is_file())
    assert any(name.endswith(".lst") for name in before), before

    second = tmp_path / "second.toml"
    second.write_text(island_toml("second", keep_solver_files=True), encoding="utf-8")
    run_island(second)

    after = sorted(str(p.relative_to(kept)) for p in kept.rglob("*") if p.is_file())
    assert after == before
    assert any((tmp_path / "runs" / "second" / "solver").rglob("*.lst"))
    assert not list((tmp_path / ".hmp").rglob("*.kept"))
