"""A degraded resume (full restart) must not be silent."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.project import runner as runner_mod
from hydromodpy.workflow.tracking.resume import ResumePlan


def _patch_planner(monkeypatch, plan: ResumePlan) -> None:
    class _FakePlanner:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def compute(self, **kwargs) -> ResumePlan:
            return plan

    monkeypatch.setattr("hydromodpy.workflow.tracking.resume.ResumePlanner", _FakePlanner)


def _capture_logs(monkeypatch) -> dict[str, list[str]]:
    logs: dict[str, list[str]] = {"warning": [], "info": []}

    def _rec(level: str):
        def _fn(msg, *args, **kwargs):
            logs[level].append(msg % args if args else msg)

        return _fn

    monkeypatch.setattr(runner_mod.logger, "warning", _rec("warning"))
    monkeypatch.setattr(runner_mod.logger, "info", _rec("info"))
    return logs


def test_full_restart_logs_a_warning(tmp_path: Path, monkeypatch) -> None:
    _patch_planner(
        monkeypatch,
        ResumePlan(
            run_id="r",
            restart_index=0,
            last_completed=None,
            invalidated=(),
            full_restart=True,
            reason="blueprint mismatch",
        ),
    )
    logs = _capture_logs(monkeypatch)
    idx = runner_mod._resolve_resume_step_index(tmp_path / "ws", "r", steps_blueprint=("a", "b"))
    assert idx == 0
    assert any("cannot pick up where it left off" in m for m in logs["warning"])


def test_clean_resume_logs_info_not_warning(tmp_path: Path, monkeypatch) -> None:
    _patch_planner(
        monkeypatch,
        ResumePlan(
            run_id="r",
            restart_index=3,
            last_completed=None,
            invalidated=(),
            full_restart=False,
            reason=None,
        ),
    )
    logs = _capture_logs(monkeypatch)
    idx = runner_mod._resolve_resume_step_index(tmp_path / "ws", "r", steps_blueprint=("a", "b"))
    assert idx == 3
    assert logs["warning"] == []
    assert any("picks up from step 3" in m for m in logs["info"])
