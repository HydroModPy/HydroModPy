"""Marker, timeout and environment fixtures of the scenario tests.

The ``scenario`` marker is declared in ``pytest.ini``, so a test outside this
folder can carry it too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.launcher import isolated_env

HERE = Path(__file__).resolve().parent
TIMEOUT_S = 900


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark every item of this folder ``scenario``, with a timeout unless it sets one."""
    for item in items:
        if HERE not in Path(item.path).resolve().parents:
            continue
        item.add_marker(pytest.mark.scenario)
        if item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(TIMEOUT_S))


@pytest.fixture(scope="session")
def scenario_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One HMP_CACHE_HOME per xdist worker, shared by the scenarios of that worker."""
    return tmp_path_factory.mktemp("scenario_cache")


@pytest.fixture
def scenario_env(tmp_path: Path, scenario_cache: Path) -> dict[str, str]:
    """The environment of one scenario, with HOME, state and TMPDIR under ``tmp_path``."""
    return isolated_env(tmp_path / "home", scenario_cache, tmp_path / "state", tmp_path / "tmp")
