from __future__ import annotations

from pathlib import Path

from tools.refresh_readthedocs import (
    DOCS_ROOT,
    REPO_ROOT,
    build_refresh_steps,
)


def test_build_refresh_steps_full_pipeline() -> None:
    steps = build_refresh_steps(
        python_executable=Path("/tmp/python"),
        install_solver_binaries=True,
    )

    assert [step.title for step in steps] == [
        "Install solver binaries",
        "Run fast solver intercomparison regressions",
        "Refresh validation reports",
        "Refresh XT3D irregular-triangle diagnostics",
        "Refresh capability gallery artifacts",
        "Check capability gallery drift",
        "Build Sphinx HTML",
    ]
    assert steps[0].working_directory == REPO_ROOT
    assert steps[0].command == (
        str(Path("/tmp/python").resolve()),
        "-m",
        "hydromodpy",
        "install-binaries",
        "--subset",
        "mf6,mfnwt",
        "--quiet",
    )
    assert steps[1].working_directory == REPO_ROOT
    assert steps[1].command == (
        str(Path("/tmp/python").resolve()),
        "-m",
        "pytest",
        "tests/regression/fast/intercomparison",
        "-q",
    )
    assert steps[-1].working_directory == DOCS_ROOT
    assert steps[-1].command[-2:] == ("source", "build/html")


def test_build_refresh_steps_respects_skip_flags() -> None:
    steps = build_refresh_steps(
        python_executable=Path("/tmp/python"),
        include_intercomparison_regressions=False,
        include_validation_reports=False,
        include_xt3d_diagnostics=False,
        include_gallery_check=False,
        include_sphinx_build=False,
    )

    assert [step.title for step in steps] == ["Refresh capability gallery artifacts"]
