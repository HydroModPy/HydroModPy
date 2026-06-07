from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def simulation_regression_fixture(name: str) -> Path:
    """Path to a TOML fixture under tests/regression/.../simulation_regression."""
    return (
        REPO_ROOT
        / "tests"
        / "regression"
        / "fixtures"
        / "projects"
        / "simulation_regression"
        / name
    )


def example_project_config(*parts: str) -> Path:
    """Path to a project.toml under examples/projects."""
    return REPO_ROOT.joinpath("examples", "projects", *parts)
