"""A run plays only the short list of files that ``run_path.toml`` names, and plays all of them.

The island of each flow chain runs through ``hmp run project.toml`` under the profiler of
``run_trace.py``, in one process. The test reads ``trace.json`` and checks that every file of
the variant was called. The count of files the run called beyond the list is not judged, it
is a number of the final survey. The list itself is guarded by
``tests/unit/architecture/test_the_run_path_is_short.py``.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play

HERE = Path(__file__).resolve().parent
RUN_PATH = tomllib.loads(
    (HERE.parents[1] / "tests/unit/architecture/run_path.toml").read_text(encoding="utf-8")
)

# The island variant and the variant of run_path.toml it plays, with the solver files it needs.
VARIANTS = {
    "gwt": ("gwt", ("mf6", "libmf6.so")),
    "nwt": ("modflow_nwt", ("mf6", "libmf6.so", "mfnwt")),
}


def _nominal(variant: str) -> list[str]:
    """Return the paths that run_path.toml lists for *variant*."""
    return [path for group in RUN_PATH["variants"][variant] for path in RUN_PATH[group]["files"]]


@pytest.mark.parametrize("island", sorted(VARIANTS))
def test_a_run_calls_every_file_of_its_short_path(
    island: str, tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    variant, needs = VARIANTS[island]
    scenario = Scenario(
        name=f"path_{island}",
        covers=f"the files called by an {island} run against the list of {variant}",
        files=island_files(island),
        python=(HERE / "run_trace.py").read_text(encoding="utf-8"),
        needs=needs,
        expected_s=40.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    trace = json.loads((played.root / "trace.json").read_text(encoding="utf-8"))
    not_called = sorted(set(_nominal(variant)) - set(trace["called"]))
    assert not not_called, f"the {variant} run did not call: {not_called}"
