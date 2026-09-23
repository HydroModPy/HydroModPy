"""Every solver an example config names resolves in the adapter registry.

A config that names a pair the registry does not hold fails at the plan, before
any work. The PRT example of project 14 kept ``modflow6prt`` after the pair was
renamed ``modflow6_prt`` and failed that way for months, unseen: no test read
the ``solvers`` lists of the examples.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.solver.base import registry

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_PROJECTS = Path("examples/projects")
PRT_EXAMPLE = (
    EXAMPLES_PROJECTS
    / "14_transport_nancon_gwt_visual_guard"
    / "run_nancon_steady_mf6_prt_pathlines.toml"
)

requires_git = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists(),
    reason="example configs are discovered through git ls-files",
)


def _tracked_toml_files() -> list[Path]:
    """Return the tracked TOML files under ``examples/projects`` still on disk."""
    if not (REPO_ROOT / ".git").exists():
        return []
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", EXAMPLES_PROJECTS.as_posix()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = (REPO_ROOT / entry for entry in completed.stdout.split("\0") if entry.endswith(".toml"))
    return sorted(path for path in paths if path.is_file())


def _declared_pairs(toml_file: Path) -> list[tuple[str, str]]:
    """Return the ``(type, solver)`` pairs the merged ``[[simulation.process]]`` declare."""
    payload = load_toml_with_base_config(toml_file)
    simulation = payload.get("simulation") or {}
    pairs: list[tuple[str, str]] = []
    for process in simulation.get("process") or []:
        for solver in process.get("solvers") or []:
            pairs.append((str(process.get("type")), str(solver)))
    return pairs


def _identifier(toml_file: Path) -> str:
    return toml_file.relative_to(REPO_ROOT).as_posix()


_CONFIGS_WITH_PROCESSES = [path for path in _tracked_toml_files() if _declared_pairs(path)]


@requires_git
def test_the_prt_example_names_a_registered_pair() -> None:
    pairs = _declared_pairs(REPO_ROOT / PRT_EXAMPLE)
    assert ("transport", "modflow6_prt") in pairs
    adapter_cls = registry.get("transport", "modflow6_prt")
    assert adapter_cls.solver_name == "modflow6_prt"


def test_the_prt_parameter_table_name_is_not_a_solver_name() -> None:
    """``modflow6prt`` names the parameter table, never the pair."""
    assert not registry.is_supported("transport", "modflow6prt")
    with pytest.raises(ValueError, match="transport/modflow6prt"):
        registry.required_bindings("transport", "modflow6prt")


@requires_git
@pytest.mark.parametrize("config_file", _CONFIGS_WITH_PROCESSES, ids=_identifier)
def test_example_solvers_resolve(config_file: Path) -> None:
    unresolved = [
        f"{process_type}/{solver}"
        for process_type, solver in _declared_pairs(config_file)
        if not registry.is_supported(process_type, solver)
    ]
    assert not unresolved, f"unregistered solver pairs: {unresolved}"
