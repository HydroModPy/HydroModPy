"""``run_capability`` points the NDJSON sink at the job directory.

F4g item 12: ``core`` cannot resolve a job directory (it imports no sibling
layer), so ``cli`` -- which already resolves one through ``JobDirectory`` to
run the capability -- is where the sink's environment variable gets its
value. Covered here rather than through a real capability: the wiring is the
same regardless of which one runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli._workers import process as process_module
from hydromodpy.core import progress as core_progress
from hydromodpy.core import progress_ndjson


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(progress_ndjson.ENV_VAR, raising=False)
    monkeypatch.setattr(progress_ndjson, "_open_path", None, raising=False)
    monkeypatch.setattr(progress_ndjson, "_open_handle", None, raising=False)


def _job_dir(tmp_path: Path) -> Path:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "request.json").write_text("{}", encoding="utf-8")
    return job_dir


def test_run_capability_sets_the_env_var_to_the_job_progress_path(tmp_path, monkeypatch):
    job_dir = _job_dir(tmp_path)
    seen: dict[str, object] = {}

    def fake_run(job, *, exit_code_for):
        seen["env_during_run"] = os.environ.get(progress_ndjson.ENV_VAR)
        seen["expected"] = str(job.progress_path)
        with core_progress.phase("probe"):
            pass
        return SimpleNamespace(reused=False, exit_code=0)

    monkeypatch.setattr(process_module, "capability", lambda cap_id: SimpleNamespace(run=fake_run))

    process_module.run_capability("probe", job_dir)

    assert seen["env_during_run"] == seen["expected"]


def test_run_capability_restores_the_previous_env_var_after(tmp_path, monkeypatch):
    job_dir = _job_dir(tmp_path)
    monkeypatch.setenv(progress_ndjson.ENV_VAR, "/previous/value.ndjson")

    def fake_run(job, *, exit_code_for):
        return SimpleNamespace(reused=False, exit_code=0)

    monkeypatch.setattr(process_module, "capability", lambda cap_id: SimpleNamespace(run=fake_run))

    process_module.run_capability("probe", job_dir)

    assert os.environ.get(progress_ndjson.ENV_VAR) == "/previous/value.ndjson"


def test_run_capability_clears_the_env_var_when_it_was_unset_before(tmp_path, monkeypatch):
    job_dir = _job_dir(tmp_path)

    def fake_run(job, *, exit_code_for):
        return SimpleNamespace(reused=False, exit_code=0)

    monkeypatch.setattr(process_module, "capability", lambda cap_id: SimpleNamespace(run=fake_run))

    process_module.run_capability("probe", job_dir)

    assert progress_ndjson.ENV_VAR not in os.environ


def test_progress_reaches_the_job_progress_file_with_no_terminal(tmp_path, monkeypatch, capsys):
    """No terminal, stdout stays empty, and the file carries the events."""
    import io

    from rich.console import Console

    fake_console = Console(file=io.StringIO(), force_terminal=False, width=100)
    monkeypatch.setattr(core_progress, "console", fake_console)
    core_progress.set_console_mode("verbose")

    job_dir = _job_dir(tmp_path)

    def fake_run(job, *, exit_code_for):
        with core_progress.task("Counting", total=2) as handle:
            handle.advance()
            handle.advance()
        return SimpleNamespace(reused=False, exit_code=0)

    monkeypatch.setattr(process_module, "capability", lambda cap_id: SimpleNamespace(run=fake_run))

    process_module.run_capability("probe", job_dir)

    progress_file = job_dir / "progress.ndjson"
    assert progress_file.is_file()
    lines = progress_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4  # started, progress, progress, completed
    captured = capsys.readouterr()
    assert captured.out == ""
