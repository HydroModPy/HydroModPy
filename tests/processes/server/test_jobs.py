"""What the server does with real processes: a run that is killed, and uploads that arrive together.

The server runs in a thread of the test, on a free port, over a root under ``tmp_path``.
A ``run`` is played by a real ``spawn`` process of the island of the scenarios, so the test
needs the ``mf6`` binary and is skipped without it. The other jobs of the server, refused,
failed and died by a stand-in target, are held in ``tests/unit/server/test_app.py``.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import hydromodpy as hmp
from hydromodpy.solver.modflow_common.binaries import exe_filename
from hydromodpy_server.app import Settings, serve
from tests.scenarios.factory import island_files, write_project
from tests.scenarios.launcher import isolated_env, link_binaries

pytestmark = pytest.mark.timeout(300)

SCHEMA = "hydromodpy.request.v1"
PROJECT = "/v1/acme/island"
ENDED = 120.0

A = b"date,rain\n2003-01-01,1\n" * 4096
B = b"date,rain\n2003-01-01,2\n" * 4096
C = b"date,rain\n2003-01-01,3\n" * 4096

# What is sent together under one name, and how many files must stay under inputs/.
UPLOADS = {
    "one content three times": ([A, A, A], 1),
    "three contents": ([A, B, C], 3),
    "two contents, some repeated": ([A, A, B, B, C], 3),
}


@dataclass
class Served:
    """A server in a thread, its settings and the project folder it serves."""

    url: str
    settings: Settings
    project: Path

    def ask(self, method: str, path: str, body: Any = None, raw: bytes | None = None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(self.url + path, data, method=method)
        try:
            with urllib.request.urlopen(request, timeout=ENDED) as answer:
                return answer.status, json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Served]:
    """Serve ``<root>/acme/projects/island`` from a thread, with the environment of a scenario."""
    cache = tmp_path / "cache"
    link_binaries(cache, tuple(exe_filename(s) for s in ("mf6", "libmf6")))
    env = isolated_env(tmp_path / "home", cache, tmp_path / "state", tmp_path / "tmp")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    root = tmp_path / "root"
    project = root / "acme" / "projects" / "island"
    project.mkdir(parents=True)
    settings = Settings(root)
    httpd = serve(settings, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield Served(f"http://127.0.0.1:{httpd.server_address[1]}", settings, project)
    httpd.shutdown()
    httpd.server_close()
    settings.stop_jobs()
    thread.join(10)


def _until(check: Any, what: str) -> Any:
    """Return the first truthy answer of ``check()``, or fail when ``what`` takes too long."""
    end = time.monotonic() + ENDED
    while time.monotonic() < end:
        found = check()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"{what} did not happen in {ENDED:.0f} s")


def test_a_killed_run_is_died_and_its_directory_is_stale(served: Served) -> None:
    files = island_files("calage")
    write_project(served.project, files)
    request = {"schema": SCHEMA, "config": tomllib.loads(files["project.toml"]), "name": "killed"}
    status, started = served.ask("POST", f"{PROJECT}/run", {"source": request})
    assert status == 202, started

    # The run claims its directory first, then solves. It is killed once it has claimed it.
    outcome = served.project / "runs" / "killed" / "outcome.json"
    _until(lambda: outcome.is_file(), "the run claiming its directory")
    assert json.loads(outcome.read_text(encoding="utf-8"))["status"] == "running"
    process = served.settings.jobs[started["job"]].process
    process.kill()

    def ended() -> dict[str, Any] | None:
        code, said = served.ask("GET", f"{PROJECT}/jobs/{started['job']}")
        assert code == 200
        return said if said["state"] != "running" else None

    said = _until(ended, "the job ending")
    assert said["state"] == "died", said
    assert said["exitcode"] not in (0, None)
    rows = {row.name: row.status for row in hmp.status(workspace=served.project)}
    assert rows == {"killed": "stale"}


@pytest.mark.parametrize("sent, kept", UPLOADS.values(), ids=list(UPLOADS))
def test_uploads_sent_together_leave_one_file_per_content(
    served: Served, sent: list[bytes], kept: int
) -> None:
    start = threading.Barrier(len(sent))
    answers: list[tuple[int, dict[str, Any]]] = [(0, {})] * len(sent)

    def upload(index: int) -> None:
        start.wait(30)
        answers[index] = served.ask("PUT", f"{PROJECT}/inputs/Rain.CSV", raw=sent[index])

    threads = [threading.Thread(target=upload, args=(index,)) for index in range(len(sent))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(ENDED)

    assert [status for status, _ in answers] == [201] * len(sent), answers
    for (_, stored), content in zip(answers, sent, strict=True):
        assert stored["sha256"] == hashlib.sha256(content).hexdigest()
        assert (served.project / stored["path"]).read_bytes() == content
    assert len({stored["path"] for _, stored in answers}) == kept
    assert len(list((served.project / "inputs").iterdir())) == kept
    assert list((served.settings.root / ".inbox").glob("*.part")) == []
