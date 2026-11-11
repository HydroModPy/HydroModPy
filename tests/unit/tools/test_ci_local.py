"""Tests of the local CI replay: tables over workflows written in a temporary folder."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from tools.ci import local

OUT = Path("OUT")
CTX = {"runner.os": "Linux", "matrix.os": "ubuntu-latest", "matrix.py": "3.13"}


def write_workflow(root: Path, jobs: dict, name: str = "w.yml", **top) -> Path:
    path = root / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"name": "w", "jobs": jobs, **top}), encoding="utf-8")
    return path


def one_step(step: dict, **job) -> dict:
    return {"job": {"runs-on": "ubuntu-latest", "steps": [step], **job}}


def plan_of(root: Path, *paths: Path, workers: int = 3, jobs=()) -> list[local.Step]:
    return local.plan(root, list(paths), workers, OUT, jobs)


def lines(steps: list[local.Step]) -> list[str]:
    return [local.describe(s) for s in steps]


# --- Expressions ---------------------------------------------------------------------

EXPRESSIONS = [
    ("runner.os == 'Linux'", True),
    ("runner.os != 'Linux'", False),
    ("RUNNER.os == 'linux'", None),
    ("matrix.os == 'ubuntu-latest' && matrix.py == '3.13'", True),
    ("!(matrix.py == '3.13')", False),
    ("matrix.py == '3.11' || matrix.py == '3.13'", True),
    ("matrix.py == '3.11' && '3.11' || '3.13'", "3.13"),
    ("always()", True),
    ("failure()", False),
    ("success() && matrix.py == 3.13", True),
    ("failure() && github.event_name == 'push'", False),
    ("true || github.event_name", True),
]


@pytest.mark.parametrize(("expression", "expected"), EXPRESSIONS)
def test_an_expression_is_evaluated_with_short_circuits(expression, expected):
    if expected is None:
        with pytest.raises(local.Unresolved, match=r"RUNNER\.os"):
            local.evaluate(expression, CTX)
    else:
        assert local.evaluate(expression, CTX) == expected


@pytest.mark.parametrize(
    "expression", ["github.event_name == 'push'", "secrets.TOKEN", "(runner.os"]
)
def test_an_unknown_name_or_a_broken_expression_is_unresolved(expression):
    with pytest.raises(local.Unresolved):
        local.evaluate(expression, CTX)


def test_a_template_is_replaced_inside_a_text():
    text = "pip ${{ matrix.py }} on ${{ runner.os }} ${{ matrix.py == '3.13' }}"
    assert local.resolve(text, CTX) == "pip 3.13 on Linux true"


# --- Commands ------------------------------------------------------------------------

COMMANDS = [
    ("python -m pytest tests/unit -q", None),
    ("set -e\npython -m pytest tests/unit", None),
    ("HMP_REQUIRE_BINARIES=1 python -m pytest tests/ports", None),
    ("python tools/ci/check_example_catalog.py", None),
    ("coverage combine || true\ncoverage report --fail-under=90", None),
    ("ruff check .", None),
    ("! git grep -n 'x' -- hydromodpy", None),
    ("python -m pytest a \\\n  b \\\n  -q", None),
    ("pip install -e .[test]", "installs packages"),
    ("python -m pip install ruff", "installs packages"),
    ("sudo apt-get update && sudo apt-get install -y libglu1-mesa", "installs system packages"),
    ("python -m hydromodpy install-binaries --subset mf6", "installs solver binaries"),
    ("docker run --rm image", "needs a Docker daemon"),
    ('echo "A=1" >> "$GITHUB_ENV"', "sets the environment of the runner"),
    ("python -m pytest a\npip install b", "installs packages"),
    ("python -m pytest a && pip install b", "installs packages"),
    ("python - <<'PY'\nprint(1)\nPY", """not a test command (python - <<'PY')"""),
    ("mypy hydromodpy", "not a test command (mypy hydromodpy)"),
    ("set -e", "empty command"),
]


@pytest.mark.parametrize(("script", "reason"), COMMANDS)
def test_a_run_text_is_played_or_given_a_reason(script, reason):
    got = local.unplayed_reason(script)
    assert got is None if reason is None else reason in got


def test_the_commands_of_a_text_join_their_line_breaks_and_drop_heredoc_bodies():
    script = "# note\npython -m pytest a \\\n  -q\n\npython - <<'EOF'\nimport os\nEOF\nruff check ."
    assert local.logical_commands(script) == [
        "python -m pytest a -q",
        "python - <<'EOF'",
        "ruff check .",
    ]


REWRITES = [
    ("python -m pytest -n 2 --dist loadgroup", 5, "python -m pytest -n 5 --dist loadgroup"),
    ("python -m pytest -n auto -q", 4, "python -m pytest -n 4 -q"),
    ("python -m pytest -n 4", 2, "python -m pytest -n 2"),
    ("python -m pytest --dist loadgroup -q", 2, "python -m pytest --dist loadgroup -q"),
    ("python -m pytest -k run-n 2", 2, "python -m pytest -k run-n 2"),
]


@pytest.mark.parametrize(("script", "workers", "expected"), REWRITES)
def test_the_worker_count_of_a_command_is_replaced(script, workers, expected):
    assert local.with_workers(script, workers) == expected


def test_the_interpreter_replaces_python_at_the_start_of_a_command():
    script = (
        "python -m pytest a\nX=1 python tools/ci/b.py && python -c 'x' || python3 c\necho python"
    )
    got = local.interpreter_script(script, "/venv/bin/python")
    assert got.splitlines() == [
        "/venv/bin/python -m pytest a",
        "X=1 /venv/bin/python tools/ci/b.py && /venv/bin/python -c 'x' || /venv/bin/python c",
        "echo python",
    ]


def test_the_default_worker_count_is_six_or_four():
    assert local.default_workers() in (4, 6)


# --- The plan: one step at a time ----------------------------------------------------

STEPS = [
    ({"run": "python -m pytest tests/unit -q"}, None),
    ({"run": "pip install -e .[test]"}, "installs packages"),
    ({"uses": "actions/checkout@v4"}, "action actions/checkout@v4"),
    ({"uses": "codecov/codecov-action@v5", "if": "always()"}, "action codecov/codecov-action@v5"),
    ({"run": "docker run --rm x"}, "needs a Docker daemon"),
    ({"run": "python -m pytest a", "if": "runner.os == 'Windows'"}, "condition is false"),
    ({"run": "python -m pytest a", "if": "runner.os != 'Linux'"}, "condition is false"),
    ({"run": "python -m pytest a", "if": "runner.os == 'Linux'"}, None),
    ({"run": "python -m pytest a", "if": "always()"}, None),
    (
        {"run": "python -m pytest a", "if": "success() && github.event_name == 'push'"},
        "github.event_name",
    ),
    ({"run": "python -m pytest ${{ secrets.X }}"}, "needs the expression secrets.X"),
    (
        {"run": "python -m pytest a", "env": {"T": "${{ secrets.X }}"}},
        "needs the expression secrets.X",
    ),
    ({"run": "python -m pytest a", "shell": "pwsh"}, "shell pwsh"),
    ({"run": "python -m pytest a", "shell": "bash"}, None),
    ({"run": "python -m pytest -n auto a"}, None),
]


@pytest.mark.parametrize(("step", "reason"), STEPS)
def test_a_step_is_played_or_listed_with_its_reason(tmp_path, step, reason):
    path = write_workflow(tmp_path, one_step(step))
    (got,) = plan_of(tmp_path, path)
    if reason is None:
        assert got.played
        assert got.command
    else:
        assert not got.played
        assert reason in got.reason
        assert local.describe(got).startswith("skip  job/")
        assert "not played locally" in local.describe(got)


def test_list_prints_the_command_of_a_played_step_with_the_worker_count(tmp_path):
    step = {"name": "Run it", "run": "python -m pytest -n auto \\\n  tests/unit -q"}
    path = write_workflow(tmp_path, one_step(step))
    assert lines(plan_of(tmp_path, path, workers=3)) == [
        "play  job/run-it  python -m pytest -n 3 tests/unit -q"
    ]


def test_expressions_resolve_in_commands_working_directory_and_env(tmp_path):
    step = {
        "name": "Go",
        "run": "python -m pytest ${{ runner.temp }} ${{ github.workspace }} ${{ env.KIND }}",
        "working-directory": "sub",
        "env": {"LOCAL": "${{ env.KIND }}-x"},
    }
    path = write_workflow(tmp_path, one_step(step, env={"KIND": "job"}), env={"TOP": "1"})
    (got,) = plan_of(tmp_path, path)
    assert got.command == f"python -m pytest {OUT / 'runner_temp'} {tmp_path} job"
    assert got.cwd == (tmp_path / "sub").resolve()
    assert got.env == {"TOP": "1", "KIND": "job", "LOCAL": "job-x"}


def test_step_names_become_unique_slugs(tmp_path):
    steps = [
        {"name": "Run tests", "run": "ruff check ."},
        {"name": "Run tests", "run": "ruff format"},
    ]
    path = write_workflow(tmp_path, {"job": {"runs-on": "ubuntu-latest", "steps": steps}})
    assert [s.ref for s in plan_of(tmp_path, path)] == ["job/run-tests", "job/run-tests-2"]


# --- The plan: jobs and matrices -----------------------------------------------------

MATRICES = [
    (
        {"os": ["ubuntu-latest", "macos-latest"], "python-version": ["3.11", "3.13"]},
        "${{ matrix.os }}",
        "matrix.os",
        "ruff check ubuntu-latest",
    ),
    (
        {"python-version": ["3.11", "3.12", "3.13"]},
        "ubuntu-latest",
        "matrix.python-version",
        "ruff check 3.13",
    ),
    ({"target_branch": ["main", "dev"]}, "ubuntu-latest", "matrix.target_branch", "ruff check dev"),
    (
        {"python-version": ["3.12"], "include": [{"python-version": "3.13"}]},
        "ubuntu-latest",
        "matrix.python-version",
        "ruff check 3.13",
    ),
    (
        {
            "python-version": ["3.13"],
            "os": ["ubuntu-latest", "windows-latest"],
            "exclude": [{"os": "ubuntu-latest"}],
        },
        "${{ matrix.os }}",
        "matrix.os",
        None,
    ),
]


@pytest.mark.parametrize(("matrix", "runs_on", "name", "command"), MATRICES)
def test_a_matrix_keeps_the_linux_python_313_dev_row(tmp_path, matrix, runs_on, name, command):
    jobs = {
        "job": {
            "runs-on": runs_on,
            "strategy": {"matrix": matrix},
            "steps": [{"name": "Go", "run": "ruff check ${{ " + name + " }}"}],
        }
    }
    played = [s for s in plan_of(tmp_path, write_workflow(tmp_path, jobs)) if s.played]
    assert [(s.ref, s.command) for s in played] == ([("job/go", command)] if command else [])


def test_dropped_matrix_rows_are_listed(tmp_path):
    jobs = {
        "job": {
            "runs-on": "${{ matrix.os }}",
            "strategy": {
                "matrix": {
                    "os": ["ubuntu-latest", "macos-latest"],
                    "python-version": ["3.12", "3.13"],
                }
            },
            "steps": [{"name": "Run", "run": "ruff check ."}],
        }
    }
    got = lines(plan_of(tmp_path, write_workflow(tmp_path, jobs)))
    assert got[0] == (
        "skip  job/(job)  not played locally: matrix rows dropped: "
        "os=ubuntu-latest, python-version=3.12; os=macos-latest, python-version=3.12; "
        "os=macos-latest, python-version=3.13"
    )
    assert got[1] == "play  job/run  ruff check ."


def test_a_matrix_with_several_rows_gets_one_job_name_per_row(tmp_path):
    jobs = {
        "job": {
            "runs-on": "ubuntu-latest",
            "strategy": {"matrix": {"bounds": ["low", "high"]}},
            "steps": [{"name": "Go", "run": "ruff check ${{ matrix.bounds }}"}],
        }
    }
    refs = [s.ref for s in plan_of(tmp_path, write_workflow(tmp_path, jobs))]
    assert refs == ["job.low/go", "job.high/go"]


JOBS = [
    ({"runs-on": "windows-latest", "steps": [{"run": "ruff check ."}]}, "runs-on windows-latest"),
    ({"runs-on": "macos-latest", "steps": [{"run": "ruff check ."}]}, "runs-on macos-latest"),
    (
        {
            "runs-on": "ubuntu-latest",
            "if": "github.event_name == 'push'",
            "steps": [{"run": "ruff ."}],
        },
        "github.event_name",
    ),
    (
        {"runs-on": "ubuntu-latest", "if": "runner.os != 'Linux'", "steps": [{"run": "ruff ."}]},
        "condition is false",
    ),
    (
        {
            "runs-on": "ubuntu-latest",
            "strategy": {"matrix": "${{ fromJson(x) }}"},
            "steps": [{"run": "ruff ."}],
        },
        "needs the expression matrix",
    ),
]


@pytest.mark.parametrize(("job", "reason"), JOBS)
def test_a_job_that_cannot_run_here_is_listed_once_with_its_reason(tmp_path, job, reason):
    (got,) = plan_of(tmp_path, write_workflow(tmp_path, {"job": job}))
    assert (got.ref, got.played) == ("job/(job)", False)
    assert reason in got.reason


def test_jobs_run_after_the_jobs_they_need(tmp_path):
    step = [{"name": "Go", "run": "ruff check ."}]
    jobs = {
        "late": {"runs-on": "ubuntu-latest", "needs": ["mid", "early"], "steps": step},
        "mid": {"runs-on": "ubuntu-latest", "needs": "early", "steps": step},
        "early": {"runs-on": "ubuntu-latest", "steps": step},
        "other": {"runs-on": "ubuntu-latest", "needs": "elsewhere", "steps": step},
    }
    refs = [s.ref for s in plan_of(tmp_path, write_workflow(tmp_path, jobs))]
    assert refs == ["early/go", "mid/go", "late/go", "other/go"]


def test_the_job_option_keeps_the_named_jobs(tmp_path):
    step = [{"name": "Go", "run": "ruff check ."}]
    jobs = {
        "a": {"runs-on": "ubuntu-latest", "steps": step},
        "b": {"runs-on": "ubuntu-latest", "steps": step},
    }
    path = write_workflow(tmp_path, jobs)
    assert [s.ref for s in plan_of(tmp_path, path, jobs=["b"])] == ["b/go"]


def test_a_job_name_used_by_an_earlier_workflow_takes_the_workflow_name(tmp_path):
    jobs = one_step({"name": "Go", "run": "ruff check ."})
    first = write_workflow(tmp_path, jobs, "first.yml")
    second = write_workflow(tmp_path, jobs, "second.yml")
    assert [s.ref for s in plan_of(tmp_path, first, second)] == ["job/go", "second.job/go"]


# --- The plan: identical commands ----------------------------------------------------


def test_an_identical_test_command_is_played_once(tmp_path):
    step = {"name": "Go", "run": "python -m pytest tests/unit -q"}
    jobs = {
        "a": one_step(step)["job"],
        "b": one_step(step)["job"],
        "c": one_step({**step, "name": "Other", "run": "python -m pytest x"})["job"],
    }
    got = plan_of(tmp_path, write_workflow(tmp_path, jobs))
    assert [s.reason for s in got] == [None, "same command as a/go", None]


def test_an_identical_coverage_command_is_played_each_time(tmp_path):
    step = {"name": "Report", "run": "coverage combine || true\ncoverage report"}
    jobs = {"a": one_step(step)["job"], "b": one_step(step)["job"]}
    assert [s.played for s in plan_of(tmp_path, write_workflow(tmp_path, jobs))] == [True, True]


def test_the_same_command_in_another_folder_is_not_a_duplicate(tmp_path):
    step = {"name": "Go", "run": "python -m pytest q"}
    jobs = {"a": one_step(step)["job"], "b": one_step({**step, "working-directory": "sub"})["job"]}
    assert [s.played for s in plan_of(tmp_path, write_workflow(tmp_path, jobs))] == [True, True]


# --- The real workflows --------------------------------------------------------------


def test_every_pytest_step_of_the_main_workflow_is_played():
    path = local.REPO_ROOT / ".github" / "workflows" / "main-ci.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    written = sum(
        1
        for job in workflow["jobs"].values()
        if job.get("runs-on") == "ubuntu-latest"
        for step in job.get("steps", [])
        if str(step.get("run", "")).lstrip().startswith("python -m pytest")
        and "github." not in str(step.get("if", ""))
    )
    got = [
        s
        for s in local.plan(local.REPO_ROOT, [path], 6, OUT)
        if s.command.lstrip().startswith("python -m pytest")
    ]
    assert len(got) == written > 5
    assert all(s.reason is None or s.reason.startswith("same command as") for s in got)
    assert all(f"-n {n}" not in s.command for s in got for n in ("auto", 2, 4))


def test_every_step_of_the_real_workflows_is_listed_with_a_job_and_a_step(capsys):
    names = ["main-ci.yml", "ci-nightly.yml", "ci-weekly.yml"]
    args = ["list", "--workers", "6"] + [a for n in names for a in ("--workflow", n)]
    assert local.main(args) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed
    assert all(line.startswith(("play  ", "skip  ")) and "/" in line.split()[1] for line in printed)
    assert all("not played locally: " in line for line in printed if line.startswith("skip"))


# --- Running -------------------------------------------------------------------------


def make_project(root: Path) -> None:
    ci = root / "tools" / "ci"
    ci.mkdir(parents=True)
    (ci / "ok.py").write_text(
        "import os, sys\nprint('ok', os.environ.get('MARK'), sys.executable)\n"
    )
    (ci / "three.py").write_text("raise SystemExit(3)\n")
    (ci / "cov.py").write_text(
        "import os\nprint(os.environ['COVERAGE_FILE'], os.environ['RUNNER_TEMP'])\n"
    )


RUN_JOBS = {
    "first": {
        "runs-on": "ubuntu-latest",
        "env": {"MARK": "seen"},
        "steps": [
            {"uses": "actions/checkout@v4"},
            {"name": "Good", "run": "python tools/ci/ok.py"},
            {"name": "Bad", "run": "python tools/ci/three.py"},
            {"name": "After", "run": "python tools/ci/cov.py", "if": "always()"},
        ],
    },
    "second": {
        "runs-on": "ubuntu-latest",
        "needs": "first",
        "steps": [{"name": "Fine", "run": "python tools/ci/ok.py"}],
    },
}


def run_args(root: Path, out: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--root",
        str(root),
        "--out",
        str(out),
        "--workflow",
        "w.yml",
        "--workers",
        "2",
        *extra,
    ]


@pytest.mark.allow_subprocess
def test_a_run_writes_logs_status_and_the_not_played_list(tmp_path, capsys):
    make_project(tmp_path)
    write_workflow(tmp_path, RUN_JOBS)
    out = tmp_path / "out"
    assert local.main(run_args(tmp_path, out)) == 1
    assert (out / "status").read_text().splitlines() == [
        "first/good 0",
        "first/bad 3",
        "first/after 0",
        "second/fine 0",
        "ALLDONE",
    ]
    assert "ok seen " + sys.executable in (out / "first__good.log").read_text()
    assert (out / "not_played").read_text() == (
        "skip  first/actions-checkout-v4  not played locally: action actions/checkout@v4\n"
    )
    assert capsys.readouterr().out.splitlines()[-1] == "ALLDONE"


@pytest.mark.allow_subprocess
def test_a_run_sets_the_coverage_file_and_the_runner_folder_under_out(tmp_path, monkeypatch):
    # A COVERAGE_FILE set by the caller wins, and the unit job of main-ci.yml sets one.
    monkeypatch.delenv("COVERAGE_FILE", raising=False)
    make_project(tmp_path)
    write_workflow(tmp_path, RUN_JOBS)
    out = tmp_path / "out"
    local.main(run_args(tmp_path, out))
    coverage, temp = (out / "first__after.log").read_text().split()
    assert coverage == str(out / "coverage" / "w" / ".coverage")
    assert temp == str(out / "runner_temp")
    assert (out / "coverage" / "w").is_dir()


@pytest.mark.allow_subprocess
def test_a_run_of_green_steps_exits_zero(tmp_path):
    make_project(tmp_path)
    jobs = {
        "only": {
            "runs-on": "ubuntu-latest",
            "steps": [{"name": "Good", "run": "python tools/ci/ok.py"}],
        }
    }
    write_workflow(tmp_path, jobs)
    assert local.main(run_args(tmp_path, tmp_path / "out")) == 0
    assert (tmp_path / "out" / "status").read_text() == "only/good 0\nALLDONE\n"


def test_a_dry_run_prints_the_commands_and_writes_nothing(tmp_path, capsys):
    make_project(tmp_path)
    write_workflow(tmp_path, RUN_JOBS)
    out = tmp_path / "out"
    assert local.main(run_args(tmp_path, out, "--dry")) == 0
    printed = capsys.readouterr().out
    assert f"play  first/good\n{sys.executable} tools/ci/ok.py" in printed
    assert "skip  first/actions-checkout-v4" in printed
    assert not out.exists()


@pytest.mark.allow_subprocess
def test_the_job_option_limits_a_run(tmp_path):
    make_project(tmp_path)
    write_workflow(tmp_path, RUN_JOBS)
    out = tmp_path / "out"
    assert local.main(run_args(tmp_path, out, "--job", "second")) == 0
    assert (out / "status").read_text() == "second/fine 0\nALLDONE\n"


# --- Refusals ------------------------------------------------------------------------


def test_a_run_without_out_is_a_usage_error(tmp_path, capsys):
    write_workflow(tmp_path, RUN_JOBS)
    assert local.main(["run", "--root", str(tmp_path), "--workflow", "w.yml"]) == 2
    assert "--out" in capsys.readouterr().err


@pytest.mark.parametrize(
    "text",
    ["jobs: [unclosed", "name: w\n", "- a\n- b\n", "jobs: {}\nname: [", "jobs: text\n"],
)
def test_an_unreadable_workflow_exits_two(tmp_path, text, capsys):
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "w.yml").write_text(textwrap.dedent(text), encoding="utf-8")
    assert local.main(["list", "--root", str(tmp_path), "--workflow", "w.yml"]) == 2
    assert "w.yml" in capsys.readouterr().err


def test_a_missing_workflow_exits_two(tmp_path, capsys):
    assert local.main(["list", "--root", str(tmp_path), "--workflow", "none.yml"]) == 2
    assert "none.yml" in capsys.readouterr().err
