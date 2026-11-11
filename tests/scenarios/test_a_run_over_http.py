"""A run is asked for over HTTP, followed as a job, and a document that reaches out is refused.

One server on a free port, one project of an organisation under its root, played in order:
1. The server prints its address, and the health route answers.
2. A CSV is uploaded and lands under ``inputs/`` with its digest.
3. ``check`` of the island document gives no error.
4. ``run`` of the island as a serialized run request is a 202. The job ends ``done`` with
   the outcome of the run, a completed run under ``runs/`` of the project, and ``status``
   lists it.
5. ``run`` of a document that writes ``[workspace] project_root`` elsewhere ends
   ``refused`` with HMPY.E101, and nothing is written outside the root.
6. An organisation nobody has is a 404.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from tests.scenarios.factory import island_files, write_project
from tests.scenarios.launcher import link_binaries

SCHEMA = "hydromodpy.request.v1"
PROJECT = "/v1/acme/island"


def _ask(url: str, method: str, path: str, body: Any = None, raw: bytes | None = None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    request = urllib.request.Request(url + path, data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _job_ends(url: str, job: str, seconds: float = 240) -> dict[str, Any]:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        status, said = _ask(url, "GET", f"{PROJECT}/jobs/{job}")
        assert status == 200
        if said["state"] != "running":
            return said
        time.sleep(0.2)
    raise AssertionError(f"the job {job} did not end in {seconds} s")


def test_a_run_over_http(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    link_binaries(scenario_cache, ("mf6", "libmf6.so"))
    root = tmp_path / "root"
    files = island_files("calage")
    project = write_project(root / "acme" / "projects" / "island", files)
    document = tomllib.loads(files["project.toml"])
    argv = [sys.executable, "-m", "hydromodpy_server", "--root", str(root), "--port", "0"]
    server = subprocess.Popen(
        argv, env=scenario_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    watchdog = threading.Timer(900, server.kill)
    watchdog.start()
    try:
        # 1. The address comes first, then the health route.
        assert server.stdout is not None
        line = server.stdout.readline()
        assert line.startswith("serving on http://127.0.0.1:"), line
        url = line.split()[-1]
        status, health = _ask(url, "GET", "/v1/health")
        assert (status, sorted(health)) == (200, ["image", "version"])

        # 2. A file is uploaded under inputs/.
        status, stored = _ask(
            url, "PUT", f"{PROJECT}/inputs/Rain.CSV", raw=b"date,rain\n2003-01-01,1\n"
        )
        assert status == 201
        assert (project / stored["path"]).read_bytes() == b"date,rain\n2003-01-01,1\n"

        # 3. The document checks without an error.
        status, found = _ask(url, "POST", f"{PROJECT}/check", {"source": document})
        assert status == 200
        assert [item for item in found if item["severity"] == "error"] == []

        # 4. The run is a job, and its outcome comes back through it.
        request = {"schema": SCHEMA, "config": document, "name": "island"}
        status, started = _ask(url, "POST", f"{PROJECT}/run", {"source": request})
        assert status == 202, started
        said = _job_ends(url, started["job"])
        assert said["state"] == "done", said
        outcome = said["result"]
        assert (outcome["status"], outcome["name"]) == ("completed", "island")
        assert outcome["run_dir"].startswith("runs/")
        assert (project / outcome["run_dir"] / "outcome.json").is_file()
        status, listed = _ask(url, "POST", f"{PROJECT}/status", {})
        assert status == 200
        assert "island" in {item["name"] for item in listed}

        # 5. A document that writes its project elsewhere is refused, and nothing is written there.
        elsewhere = tmp_path / "elsewhere"
        reaching = copy.deepcopy(document)
        reaching["workspace"] = {"project_root": str(elsewhere)}
        request = {"schema": SCHEMA, "config": reaching, "name": "reach"}
        status, started = _ask(url, "POST", f"{PROJECT}/run", {"source": request})
        assert status == 202, started
        said = _job_ends(url, started["job"])
        assert (said["state"], said["refusal"]["code"]) == ("refused", "HMPY.E101")
        assert "project_root" in said["refusal"]["message"]
        assert not elsewhere.exists()
        assert sorted(path.name for path in root.iterdir()) == [".inbox", "acme"]

        # 6. An organisation nobody has is a 404.
        status, _ = _ask(url, "POST", "/v1/nobody/island/check", {"source": document})
        assert status == 404
    finally:
        watchdog.cancel()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
