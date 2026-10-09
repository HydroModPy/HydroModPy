"""Write what each validation test measured to a JSON file.

Set ``HMP_VALIDATION_RESULTS`` to a directory and run pytest on
``tests/validation``. Each process (the main one, or each xdist worker)
writes one ``part-*.json`` there at the end of the session: the outcome of
every validation test it ran, the metrics and thresholds the test recorded
through ``tests.validation.helpers``, the curves it compared, and the run
facts (commit, package version, date). ``python -m tools.docs.validation_results``
merges the parts into the snapshot the documentation reads.

Without the variable nothing is written. Recording never changes an outcome.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.validation.helpers import results

ENV_VAR = "HMP_VALIDATION_RESULTS"
SCHEMA = 1
_REPO = Path(__file__).resolve().parents[2]
_RECORDS: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _validation_record(request: pytest.FixtureRequest):
    """Route the metrics a test records to its own record."""
    record = results.new_record()
    request.node._hmp_validation_record = record
    with results.recording(record):
        yield record


def _skip_reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).removeprefix("Skipped: ")
    return str(longrepr or "")


def _failure(report: pytest.TestReport) -> str:
    crash = getattr(report.longrepr, "reprcrash", None)
    message = str(getattr(crash, "message", "") or "")
    return (message.splitlines() or [""])[0]


def _outcome(reports: dict[str, pytest.TestReport]) -> tuple[str, str]:
    """Collapse the setup, call and teardown reports into one outcome."""
    setup, call, teardown = (reports.get(k) for k in ("setup", "call", "teardown"))
    if setup is not None and setup.skipped:
        return "skipped", _skip_reason(setup)
    if setup is not None and setup.failed:
        return "error", _failure(setup) or "setup failed"
    if call is not None and call.skipped:
        return "skipped", _skip_reason(call)
    if call is not None and call.failed:
        return "failed", _failure(call)
    if teardown is not None and teardown.failed:
        return "error", _failure(teardown) or "teardown failed"
    return ("passed", "") if call is not None else ("not run", "")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    reports = item.__dict__.setdefault("_hmp_validation_reports", {})
    reports[report.when] = report
    if report.when == "teardown" and os.environ.get(ENV_VAR):
        _RECORDS.append(_entry(item, reports))
    return report


def _entry(item: pytest.Item, reports: dict[str, pytest.TestReport]) -> dict[str, Any]:
    outcome, reason = _outcome(reports)
    record = getattr(item, "_hmp_validation_record", None) or results.new_record()
    callspec = getattr(item, "callspec", None)
    params = callspec.params if callspec is not None else {}
    solver = params.get("solver")
    return {
        "nodeid": item.nodeid,
        "file": item.nodeid.split("::", 1)[0],
        "function": getattr(item, "originalname", None) or item.name.split("[", 1)[0],
        "params": callspec.id if callspec is not None else "",
        "solver": str(solver) if isinstance(solver, str) else None,
        "outcome": outcome,
        "reason": reason[:300],
        "duration_s": round(sum(r.duration for r in reports.values()), 2),
        **record,
    }


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=_REPO, capture_output=True, text=True, timeout=20, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def run_facts(config: pytest.Config) -> dict[str, Any]:
    """The facts of this run that every record of it shares."""
    from hydromodpy.core.version import __version__

    server, repo, run_id = (
        os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")
    )
    commit = os.environ.get("GITHUB_SHA") or _git("rev-parse", "HEAD")
    branch = os.environ.get("GITHUB_REF_NAME") or _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {
        "date": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "commit": commit,
        "dirty": dirty if not os.environ.get("GITHUB_SHA") else False,
        "branch": "" if branch == "HEAD" else branch,
        "version": __version__,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "ci_run": f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else "",
        "markers": config.option.markexpr or "",
        "command": " ".join(["pytest", *config.invocation_params.args]),
    }


_FACTS: dict[str, Any] = {}


def pytest_collection_finish(session: pytest.Session) -> None:
    """Read the commit when the code is imported, not when the run ends."""
    if os.environ.get(ENV_VAR) and not _FACTS:
        _FACTS.update(run_facts(session.config))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    out_dir = os.environ.get(ENV_VAR)
    if not out_dir or not _RECORDS:
        return
    facts = {**(_FACTS or run_facts(session.config))}
    facts["date"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    path = Path(out_dir) / f"part-{worker}-{os.getpid()}-{int(time.time())}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA, "run": facts, "tests": _RECORDS}
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"\nvalidation results: {len(_RECORDS)} tests -> {path}", file=sys.stderr)
