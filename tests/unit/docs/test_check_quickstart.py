"""The Quick start of Get started is read by a tool, so the page and the check agree.

``tools/docs/check_quickstart.py`` takes the commands and the two lines a run
ends with from ``docs/source/get-started/index.md``. CI runs them. These tests
hold the reader of the page, not the run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.docs import check_quickstart as qs

PAGE_TEXT = qs.PAGE.read_text(encoding="utf-8")


def test_the_commands_are_the_five_of_the_page() -> None:
    commands = qs.quick_start_commands(PAGE_TEXT)
    assert [c[0] for c in commands] == ["pip", "hmp", "hmp", "hmp", "hmp"]
    runs = [c for c in commands if c[:2] == ["hmp", "run"]]
    assert len(runs) == 2
    assert runs[0][2].endswith("run_demo.toml")


def test_the_page_promises_two_lines() -> None:
    first, second = qs.promised_lines(PAGE_TEXT)
    assert first.startswith("Run completed: ")
    assert second.startswith("next: hmp catalog show ")


def test_the_promised_lines_match_themselves_and_a_real_run() -> None:
    done, following = qs.line_patterns(*qs.promised_lines(PAGE_TEXT))
    real = [
        "Run completed: demo [28693ca4] 2s",
        "next: hmp catalog show demo | hmp catalog diff demo <other> | hmp export demo --list",
    ]
    assert qs.lines_match(done, following, real)
    assert qs.lines_match(done, following, list(qs.promised_lines(PAGE_TEXT)))


@pytest.mark.parametrize(
    "last",
    [
        ["Run completed: demo [28693ca4] 2s"],
        ["Run completed: demo [28693ca4] 2s", "next: hmp catalog show demo"],
        [
            "Run completed: demo [28693ca4] 2s",
            "next: hmp catalog show other | hmp catalog diff other <other> | hmp export other --list",
        ],
        ["Run failed: demo [28693ca4] 2s", "next: hmp catalog show demo"],
    ],
)
def test_a_line_that_differs_from_the_page_is_refused(last: list[str]) -> None:
    done, following = qs.line_patterns(*qs.promised_lines(PAGE_TEXT))
    assert not qs.lines_match(done, following, last)


def test_a_page_without_the_heading_is_refused() -> None:
    with pytest.raises(ValueError, match="Quick start"):
        qs.quick_start_commands("# Get started\n")


def test_a_tilde_is_the_scratch_home_and_never_the_real_one(tmp_path: Path) -> None:
    command = ["hmp", "run", "~/hydromodpy/projects/example/run_demo.toml"]
    args = qs.expand(command, tmp_path)
    assert args[-1] == f"{tmp_path}/hydromodpy/projects/example/run_demo.toml"
    assert qs.expand(["hmp", "doctor"], tmp_path)[-1] == "doctor"


def test_the_commands_never_see_a_real_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HMP_WORKSPACE", "/home/someone/hydromodpy")
    env = qs.scratch_env(tmp_path)
    assert "HMP_WORKSPACE" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["HMP_STATE_HOME"].startswith(str(tmp_path))
