"""A run cut by Ctrl+C or SIGTERM is closed as failed, not left "running"."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.project.test_run_pipeline_state import DEM, PROJECT_TOML

SIM_ID = "11111111-2222-3333-4444-555555555555"


@pytest.mark.parametrize("signal_error", [KeyboardInterrupt, RuntimeError])
def test_an_interrupted_run_is_finalized_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signal_error: type[BaseException]
) -> None:
    from hydromodpy.project import phases as project_phases
    from hydromodpy.project.facade import Project

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()), encoding="utf-8"
    )
    finalized: list[tuple[str, str]] = []

    class _Store:
        def finalize(self, sim_id: str, status: str = "completed") -> None:
            finalized.append((sim_id, status))

    class _Pipeline:
        def __init__(self, steps, *, workspace) -> None:
            self.steps = steps

        def run(self, state, **kwargs):
            raise signal_error("cut")

    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)
    project = Project(config_path, no_display=True)
    monkeypatch.setattr(
        project_phases, "open_catalog", lambda proj: setattr(proj, "_store", _Store())
    )
    project._ctx.sim_id = SIM_ID

    with pytest.raises(signal_error):
        project.simulate(name="asked_name")

    assert finalized == [(SIM_ID, "failed")]
