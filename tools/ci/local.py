"""Replay the Linux steps of the CI workflows on this machine.

The workflows under ``.github/workflows`` stay the one place that holds the test
commands. This script reads them, keeps the Linux row and the Python 3.13 row of
each job, and plays the steps that run a test command. Every other step is listed
as not played locally, with its reason.

    python tools/ci/local.py list [--workflow main-ci.yml ...]
    python tools/ci/local.py run --out DIR [--workflow ...] [--job ...] [--workers N] [--dry]

A step is played when each command of its ``run:`` text starts with
``python -m pytest``, ``python tools/ci/``, ``coverage``, ``ruff`` or ``git grep``.
Jobs run in the order of ``needs:`` and a failed step does not stop the others,
so one run shows every red. A command that an earlier step already plays is listed
as "same command as <job>/<step>". Each step writes ``DIR/<job>__<step>.log`` and
one line ``<job>/<step> <code>`` in ``DIR/status``, then ``ALLDONE`` closes the file.
Coverage data goes to ``DIR/coverage/<workflow>/.coverage``, so a combine step reads
the files of its own workflow only. The exit code is 0 when every played step ends
with 0, 1 when one fails and 2 when a workflow cannot be read.
"""

from __future__ import annotations

import argparse
import itertools
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_VERSION = "3.13"
TARGET_BRANCH = "dev"
PLAYED_PREFIXES = ("python -m pytest", "python tools/ci/", "coverage ", "ruff ", "git grep")
HARMLESS_SEGMENTS = ("true", ":")
GITHUB_BASH = ("bash", "--noprofile", "--norc", "-eo", "pipefail", "-c")


class WorkflowError(Exception):
    """A workflow file cannot be read."""


class Unresolved(Exception):
    """An expression names something the local copy cannot know."""


# --- Expressions of the form ${{ ... }} ---------------------------------------------

_TOKEN = re.compile(
    r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<op>==|!=|&&|\|\||[()!])"
    r"|(?P<name>[A-Za-z_][\w-]*(?:\.[\w-]+)*(?:\(\))?)|(?P<num>\d+(?:\.\d+)?))"
)
_TEMPLATE = re.compile(r"\$\{\{(.*?)\}\}", re.S)
_FUNCTIONS = {"always()": True, "success()": True, "failure()": False, "cancelled()": False}
_LITERALS = {"true": True, "false": False, "null": None}


def _tokens(text: str) -> list[tuple[str, str]]:
    found, pos, text = [], 0, text.rstrip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            raise Unresolved(text.strip())
        kind = match.lastgroup or ""
        found.append((kind, match.group(kind)))
        pos = match.end()
    return found


class _Parser:
    """Recursive descent over ``||``, ``&&``, ``==``/``!=`` and ``!``, with short circuits."""

    def __init__(self, text: str, context: dict[str, object]) -> None:
        self.tokens, self.context, self.at, self.live = _tokens(text), context, 0, True

    def peek(self) -> str | None:
        return self.tokens[self.at][1] if self.at < len(self.tokens) else None

    def parse(self) -> object:
        value = self.either()
        if self.at != len(self.tokens):
            raise Unresolved(self.peek() or "")
        return value

    def either(self) -> object:
        value = self.both()
        while self.peek() == "||":
            self.at += 1
            value = self._branch(value, keep=bool(value), parse=self.both)
        return value

    def both(self) -> object:
        value = self.compare()
        while self.peek() == "&&":
            self.at += 1
            value = self._branch(value, keep=not value, parse=self.compare)
        return value

    def _branch(self, value: object, keep: bool, parse) -> object:
        """Parse the right side, and read it only when the left side did not decide."""
        outer = self.live
        self.live = outer and not keep
        right = parse()
        self.live = outer
        return value if keep else right

    def compare(self) -> object:
        left = self.unary()
        while self.peek() in ("==", "!="):
            op = self.tokens[self.at][1]
            self.at += 1
            right = self.unary()
            if self.live:
                same = _text(left).lower() == _text(right).lower()
                left = same if op == "==" else not same
        return left

    def unary(self) -> object:
        kind, token = self.tokens[self.at] if self.at < len(self.tokens) else ("", "")
        self.at += 1
        if token == "!" and kind == "op":
            return not self.unary()
        if token == "(" and kind == "op":
            value = self.either()
            if self.peek() != ")":
                raise Unresolved("(")
            self.at += 1
            return value
        if kind == "str":
            return token[1:-1].replace("''", "'")
        if kind == "num":
            return token
        if kind == "name":
            return self.name(token)
        raise Unresolved(token or "end of expression")

    def name(self, token: str) -> object:
        if not self.live:
            return None
        if token in _LITERALS:
            return _LITERALS[token]
        if token in _FUNCTIONS:
            return _FUNCTIONS[token]
        if token in self.context:
            return self.context[token]
        raise Unresolved(token)


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def evaluate(expression: str, context: dict[str, object]) -> object:
    """Value of one expression, Unresolved when it names a name outside ``context``."""
    return _Parser(expression, context).parse()


def resolve(text: str, context: dict[str, object]) -> str:
    """Replace each ``${{ expression }}`` of a text by its value."""
    return _TEMPLATE.sub(lambda m: _text(evaluate(m.group(1), context)), text)


def condition(raw: object, context: dict[str, object]) -> bool:
    """Value of an ``if:`` field, with or without the ``${{ }}`` wrapper."""
    text = str(raw).strip()
    match = _TEMPLATE.fullmatch(text)
    return bool(evaluate(match.group(1) if match else text, context))


# --- Commands of a ``run:`` text -----------------------------------------------------


def logical_commands(script: str) -> list[str]:
    """The commands of a shell text, joined over backslash breaks, heredoc bodies dropped."""
    lines, found, at = script.splitlines(), [], 0
    while at < len(lines):
        text, at = lines[at].strip(), at + 1
        if not text or text.startswith("#"):
            continue
        while text.endswith("\\") and at < len(lines):
            text, at = text[:-1].rstrip() + " " + lines[at].strip(), at + 1
        heredoc = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", text)
        if heredoc:
            while at < len(lines) and lines[at].strip() != heredoc.group(1):
                at += 1
            at += 1
        found.append(text)
    return found


def _head(segment: str) -> str:
    """A command without its ``!`` and its leading ``NAME=value`` assignments."""
    return re.sub(r"^(?:!\s+)?(?:[A-Za-z_]\w*=\S*\s+)*", "", segment.strip())


def _why_not(head: str) -> str:
    """The reason a command is not played here."""
    first = " ".join(head.split()[:3])
    if re.match(r"(python -m )?(pip|uv)\b", head):
        return f"installs packages, the environment is already built ({first})"
    if re.match(r"(sudo|apt|apt-get)\b", head):
        return f"installs system packages ({first})"
    if "install-binaries" in head:
        return "installs solver binaries, they are linked from the cache"
    if head.startswith("docker"):
        return "needs a Docker daemon"
    if "GITHUB_ENV" in head or "GITHUB_PATH" in head:
        return "sets the environment of the runner"
    return f"not a test command ({first})"


def unplayed_reason(script: str) -> str | None:
    """None when every command of the text is played, else the reason for the first that is not."""
    commands = [c for c in logical_commands(script) if not c.startswith("set ")]
    if not commands:
        return "empty command"
    for command in commands:
        for segment in re.split(r"&&|;", command):
            head = _head(segment.split("||")[0])
            if head not in HARMLESS_SEGMENTS and not head.startswith(PLAYED_PREFIXES):
                return _why_not(head)
    return None


def interpreter_script(script: str, python: str) -> str:
    """The text with ``python`` at the start of a command replaced by the interpreter path."""
    return re.sub(
        r"(?m)(^|&&|\|\||;)(\s*(?:[A-Za-z_]\w*=\S*\s+)*)python3?(?=\s)",
        lambda m: f"{m.group(1)}{m.group(2)}{shlex.quote(python)}",
        script,
    )


def with_workers(script: str, workers: int) -> str:
    """The text with each ``-n 2``, ``-n 4`` or ``-n auto`` set to the worker count."""
    return re.sub(r"(?<!\S)-n\s+(?:auto|\d+)(?!\S)", f"-n {workers}", script)


def default_workers() -> int:
    """Six workers, four when more than 35 GiB of memory is already in use."""
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        kib = {k: int(v.split()[0]) for k, v in info.items() if k in ("MemTotal", "MemAvailable")}
        used_gib = (kib["MemTotal"] - kib["MemAvailable"]) / 2**20
    except (OSError, KeyError, ValueError):
        return 6
    return 4 if used_gib > 35 else 6


# --- The plan ------------------------------------------------------------------------


@dataclass
class Step:
    """One step of one job row, with its command resolved and its reason when not played."""

    workflow: str
    job: str
    name: str
    command: str = ""
    cwd: Path = REPO_ROOT
    env: dict[str, str] = field(default_factory=dict)
    reason: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.job}/{self.name}"

    @property
    def played(self) -> bool:
        return self.reason is None


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-") or "step"


def matrix_rows(matrix: object) -> list[dict[str, object]]:
    """Rows of a job matrix, with ``exclude`` and ``include`` applied as GitHub does."""
    if not matrix:
        return [{}]
    if not isinstance(matrix, dict):
        raise Unresolved(f"matrix {matrix}")
    axes = {k: v if isinstance(v, list) else [v] for k, v in matrix.items()}
    include, exclude = axes.pop("include", []), axes.pop("exclude", [])
    rows = [dict(zip(axes, combo)) for combo in itertools.product(*axes.values())] if axes else []
    rows = [r for r in rows if not any(all(r.get(k) == v for k, v in x.items()) for x in exclude)]
    for extra in include:
        shared = [k for k in axes if k in extra]
        hits = [r for r in rows if shared and all(r[k] == extra[k] for k in shared)]
        for row in hits:
            row.update(extra)
        if not hits:
            rows.append(dict(extra))
    return rows or [{}]


def _row_label(row: dict[str, object]) -> str:
    return ", ".join(f"{k}={v}" for k, v in row.items())


def _context(root: Path, out: Path, row: dict[str, object] | None = None) -> dict[str, object]:
    context: dict[str, object] = {
        "runner.os": "Linux",
        "runner.temp": str(out / "runner_temp"),
        "github.workspace": str(root),
    }
    context.update({f"matrix.{k}": v for k, v in (row or {}).items()})
    return context


def _resolved_env(raw: object, context: dict[str, object]) -> dict[str, str]:
    """Resolve an ``env:`` table and add it to the context as ``env.*``."""
    env = {str(k): resolve(_text(v), context) for k, v in (raw or {}).items()}
    context.update({f"env.{k}": v for k, v in env.items()})
    return env


def _all_env(context: dict[str, object]) -> dict[str, str]:
    return {k[4:]: str(v) for k, v in context.items() if k.startswith("env.")}


def _title(raw: dict, index: int) -> str:
    first_line = str(raw.get("run") or "").strip().splitlines()[:1]
    return str(raw.get("name") or raw.get("uses") or "".join(first_line) or index)


def _step_reason(
    step: Step, raw: dict, context: dict[str, object], defaults: dict, root: Path, workers: int
):
    """Fill the command of a step, or its reason when it is not played here."""
    local = dict(context)
    step_env = _resolved_env(raw.get("env"), local)
    if "if" in raw and not condition(raw["if"], local):
        step.reason = f"condition is false on Linux: if {raw['if']}"
    elif "uses" in raw:
        step.reason = f"action {raw['uses']}"
    elif str(raw.get("shell") or defaults.get("shell") or "bash").split()[0] != "bash":
        step.reason = f"shell {raw.get('shell')}"
    else:
        step.command = with_workers(resolve(str(raw.get("run", "")), local), workers)
        step.reason = unplayed_reason(step.command)
        folder = raw.get("working-directory") or defaults.get("working-directory") or "."
        step.cwd = (root / resolve(str(folder), local)).resolve()
        step.env = {**_all_env(context), **step_env}


def _job_steps(
    workflow: dict, job_id: str, job: dict, context: dict[str, object], root: Path, workers: int
):
    """The steps of one job row, each played or with its reason."""
    defaults = {}
    for table in (workflow.get("defaults"), job.get("defaults")):
        defaults.update((table or {}).get("run") or {})
    steps, names = [], set()
    try:
        _resolved_env(job.get("env"), context)
        failure = ""
    except Unresolved as error:
        failure = f"needs the expression {error}"
    for index, raw in enumerate(job.get("steps") or [], start=1):
        name = slug(re.sub(r"\$\{\{.*?\}\}", "", _title(raw, index)))
        while name in names:
            name += "-2"
        names.add(name)
        step = Step(workflow["_file"], job_id, name, reason=failure or None)
        try:
            if not failure:
                _step_reason(step, raw, context, defaults, root, workers)
        except Unresolved as error:
            step.reason = f"needs the expression {error}"
        steps.append(step)
    return steps


def _job_rows(job: dict, root: Path, out: Path, base: dict[str, object]):
    """Rows of a job that run here, labels of the rows dropped, and a reason for the whole job."""
    try:
        rows = matrix_rows((job.get("strategy") or {}).get("matrix"))
    except Unresolved as error:
        return [], [], f"needs the expression {error}"
    kept, dropped = [], []
    for row in rows:
        context = {**base, **_context(root, out, row)}
        wrong = [
            f"{k}={row[k]}"
            for k, want in (("python-version", PYTHON_VERSION), ("target_branch", TARGET_BRANCH))
            if k in row and str(row[k]) != want
        ]
        try:
            runs_on = resolve(str(job.get("runs-on", "")), context)
            if not runs_on.startswith("ubuntu"):
                wrong.append(f"runs-on {runs_on}")
            if not wrong and "if" in job and not condition(job["if"], context):
                return [], [], f"condition is false on Linux: if {job['if']}"
        except Unresolved as error:
            return [], [], f"needs the expression {error}"
        if wrong:
            dropped.append(_row_label(row) or ", ".join(wrong))
        else:
            kept.append(row)
    return kept, dropped, None


def _job_order(jobs: dict) -> list[str]:
    """Job ids in file order, each after the jobs it needs."""
    order: list[str] = []

    def visit(job_id: str, path: tuple[str, ...] = ()) -> None:
        if job_id in order or job_id in path or job_id not in jobs:
            return
        needs = (jobs[job_id] or {}).get("needs") or []
        for need in [needs] if isinstance(needs, str) else needs:
            visit(need, (*path, job_id))
        order.append(job_id)

    for job_id in jobs:
        visit(job_id)
    return order


def read_workflow(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise WorkflowError(f"{path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        raise WorkflowError(f"{path}: no jobs table")
    data["_file"] = path.name
    return data


def plan(
    root: Path, workflows: Sequence[Path], workers: int, out: Path, jobs: Sequence[str] = ()
) -> list[Step]:
    """Every step of the Linux rows, in run order, with identical commands marked as played once."""
    steps: list[Step] = []
    taken: set[str] = set()
    for path in workflows:
        workflow = read_workflow(path)
        base = _context(root, out)
        try:
            _resolved_env(workflow.get("env"), base)
            env_failure = None
        except Unresolved as error:
            env_failure = f"needs the expression {error}"
        for job_id in _job_order(workflow["jobs"]):
            if jobs and job_id not in jobs:
                continue
            job = workflow["jobs"][job_id] or {}
            kept, dropped, whole = _job_rows(job, root, out, base)
            name = job_id if job_id not in taken else f"{path.stem}.{job_id}"
            taken.add(job_id)
            if whole or dropped:
                reason = whole or "matrix rows dropped: " + "; ".join(dropped)
                steps.append(Step(path.name, name, "(job)", reason=reason))
            for row in kept:
                row_id = name
                if len(kept) > 1:
                    row_id = f"{name}.{slug('-'.join(map(str, row.values())))}"
                context = {**base, **_context(root, out, row)}
                found = _job_steps(workflow, row_id, job, context, root, workers)
                for step in found:
                    step.reason = env_failure or step.reason
                steps.extend(found)
    seen: dict[tuple[str, Path], str] = {}
    for step in steps:
        if not (step.played and step.command.lstrip().startswith("python -m pytest")):
            continue
        if (step.command, step.cwd) in seen:
            step.reason = f"same command as {seen[step.command, step.cwd]}"
        else:
            seen[step.command, step.cwd] = step.ref
    return steps


def describe(step: Step) -> str:
    """One line of ``list`` for a step."""
    if step.played:
        return f"play  {step.ref}  {' ; '.join(logical_commands(step.command))}"
    return f"skip  {step.ref}  not played locally: {step.reason}"


# --- Running -------------------------------------------------------------------------


def run_step(step: Step, out: Path, root: Path, python: str) -> int:
    """Play one step under bash with the environment of the workflow, its log in ``out``."""
    stem = f"{step.workflow.rsplit('.', 1)[0]}"
    env = dict(os.environ)
    env["PATH"] = str(Path(python).parent) + os.pathsep + env.get("PATH", "")
    env.update(GITHUB_WORKSPACE=str(root), RUNNER_TEMP=str(out / "runner_temp"), RUNNER_OS="Linux")
    env.setdefault("COVERAGE_FILE", str(out / "coverage" / stem / ".coverage"))
    if "COVERAGE_FILE" in step.env:
        env["COVERAGE_FILE"] = step.env["COVERAGE_FILE"]
    env.update(step.env)
    Path(env["COVERAGE_FILE"]).parent.mkdir(parents=True, exist_ok=True)
    log = out / f"{step.job}__{step.name}.log"
    script = interpreter_script(step.command, python)
    try:
        with log.open("wb") as handle:
            done = subprocess.run(
                [*GITHUB_BASH, script],
                cwd=step.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        return done.returncode
    except OSError as error:
        log.write_text(f"{error}\n", encoding="utf-8")
        return 127


def run(steps: Sequence[Step], out: Path, root: Path, python: str = sys.executable) -> int:
    """Play the steps in order, write the status file, and return the exit code."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "runner_temp").mkdir(exist_ok=True)
    status = out / "status"
    status.write_text("", encoding="utf-8")
    skipped = [describe(s) for s in steps if not s.played]
    (out / "not_played").write_text("".join(f"{line}\n" for line in skipped), encoding="utf-8")
    print("\n".join(skipped), flush=True)
    failed = 0
    for step in (s for s in steps if s.played):
        code = run_step(step, out, root, python)
        failed += code != 0
        with status.open("a", encoding="utf-8") as handle:
            handle.write(f"{step.ref} {code}\n")
        print(f"{step.ref} {code}", flush=True)
    with status.open("a", encoding="utf-8") as handle:
        handle.write("ALLDONE\n")
    print("ALLDONE", flush=True)
    return 1 if failed else 0


# --- Command line --------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "run"):
        one = sub.add_parser(name)
        one.add_argument("--workflow", action="append", default=[], help="file name or path")
        one.add_argument("--job", action="append", default=[])
        one.add_argument("--workers", type=int, default=None)
        one.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
        one.add_argument("--out", type=Path, default=None if name == "run" else Path("<out>"))
    sub.choices["run"].add_argument("--dry", action="store_true")
    return parser


def _workflow_paths(root: Path, names: Sequence[str]) -> list[Path]:
    folder = root / ".github" / "workflows"
    if not names:
        return sorted(folder.glob("*.yml"))
    return [Path(n) if Path(n).exists() and "/" in n else folder / n for n in names]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run" and args.out is None and not args.dry:
        print("run needs --out DIR", file=sys.stderr)
        return 2
    root, out = args.root.resolve(), args.out or Path("<out>")
    workers = args.workers or default_workers()
    try:
        steps = plan(root, _workflow_paths(root, args.workflow), workers, out, args.job)
    except WorkflowError as error:
        print(error, file=sys.stderr)
        return 2
    if args.command == "list":
        print("\n".join(describe(s) for s in steps))
        return 0
    if args.dry:
        for step in steps:
            print(
                describe(step)
                if not step.played
                else f"play  {step.ref}\n{interpreter_script(step.command, sys.executable)}"
            )
        return 0
    return run(steps, out.resolve(), root)


if __name__ == "__main__":
    raise SystemExit(main())
