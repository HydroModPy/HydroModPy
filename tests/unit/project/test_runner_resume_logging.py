"""A degraded resume (full restart) must not be silent."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.project import runner as runner_mod
from hydromodpy.workflow.resume import ResumePlan


def _patch_planner(monkeypatch, plan: ResumePlan) -> None:
    class _FakePlanner:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def compute(self, **kwargs) -> ResumePlan:
            return plan

    monkeypatch.setattr("hydromodpy.workflow.resume.ResumePlanner", _FakePlanner)


def test_full_restart_logs_a_warning(tmp_path: Path, monkeypatch, capsys) -> None:
    plan = ResumePlan(
        run_id="r",
        restart_index=0,
        last_completed=None,
        invalidated=(),
        full_restart=True,
        reason="blueprint mismatch",
    )
    _patch_planner(monkeypatch, plan)
    idx = runner_mod._resolve_resume_step_index(tmp_path / "ws", "r", steps_blueprint=("a", "b"))
    assert idx == 0
    assert "cannot pick up where it left off" in capsys.readouterr().err


def test_clean_resume_does_not_warn(tmp_path: Path, monkeypatch, capsys) -> None:
    plan = ResumePlan(
        run_id="r",
        restart_index=3,
        last_completed=None,
        invalidated=(),
        full_restart=False,
        reason=None,
    )
    _patch_planner(monkeypatch, plan)
    idx = runner_mod._resolve_resume_step_index(tmp_path / "ws", "r", steps_blueprint=("a", "b"))
    assert idx == 3
    assert "cannot pick up" not in capsys.readouterr().err
