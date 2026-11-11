"""Two runs of one project are played by two processes of one server, then replayed together.

The root of the server is short and the project name is padded, so the project folder is
99 characters long, the longest root a project keeps below the Windows path limit. One
server, one project, played in order:
1. The server prints its address.
2. Two documents of the steady island that differ by their recharge are posted as two
   ``run`` requests, one after the other without waiting. Both answer 202 and both jobs
   end ``done``.
3. Two runs completed under ``runs/``, each sealed in version 4 with nothing to repair,
   two different request ids, ``status`` lists both, the index lock and the temporary
   files of the project are gone, the mesh sits once in the product store and both runs
   cite its key, and no path of the project is longer than the Windows limit.
4. Both runs are posted to ``replay`` together. Both jobs end ``done`` and each replay is
   class ``bit`` in its lineage.
5. The server is stopped by a signal, and killed if it has not ended after 10 s.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hydromodpy.core.io.filesystem import PROJECT_TREE_DEPTH, WINDOWS_PATH_LIMIT
from hydromodpy.results.products.cited import read_cited
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.results.record.manifest import read_seal, seal_problems
from hydromodpy.solver.modflow_common.binaries import exe_filename
from tests.scenarios.factory import island_files, write_project
from tests.scenarios.launcher import link_binaries

SCHEMA = "hydromodpy.request.v1"
PROJECT_PATH_LENGTH = WINDOWS_PATH_LIMIT - PROJECT_TREE_DEPTH
RECHARGES = {"one": 1.0, "two": 2.0}


def _ask(url: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url + path, data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _until(check: Callable[[], Any], seconds: float, what: str) -> Any:
    """Return the first truthy answer of ``check()``, or fail when ``what`` takes too long."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        found = check()
        if found:
            return found
        time.sleep(0.2)
    raise AssertionError(f"{what} did not happen in {seconds:.0f} s")


def _post_together(url: str, project: str, verb: str, bodies: dict[str, dict]) -> dict[str, str]:
    """Post one call per key without waiting, and return the job of each."""
    jobs = {}
    for key, body in bodies.items():
        status, started = _ask(url, "POST", f"{project}/{verb}", body)
        assert status == 202, started
        jobs[key] = started["job"]
    return jobs


def _jobs_end(url: str, project: str, jobs: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Wait for every job to leave ``running`` and return what each said, all ``done``."""
    said: dict[str, dict[str, Any]] = {}

    def ended() -> bool:
        for key, job in jobs.items():
            if key not in said:
                status, answer = _ask(url, "GET", f"{project}/jobs/{job}")
                assert status == 200
                if answer["state"] != "running":
                    said[key] = answer
        return len(said) == len(jobs)

    _until(ended, 240, f"the jobs {sorted(jobs)} ending")
    assert {key: found["state"] for key, found in said.items()} == dict.fromkeys(jobs, "done"), said
    return said


def _documents() -> dict[str, dict[str, Any]]:
    """Return the steady island twice, each with its own recharge, so the requests differ.

    The island reads no user file: a replay pins the files a run read, and the piezometry
    files of ``calage`` are not among what it pins today.
    """
    base = tomllib.loads(island_files("calage")["project.toml"])
    base["data"]["types"] = ["oceanic", "recharge"]
    del base["data"]["piezometry"]
    documents = {}
    for name, value in RECHARGES.items():
        document = copy.deepcopy(base)
        document["data"]["recharge"]["sources"][0]["values"] = [value]
        documents[name] = document
    return documents


def _project_name(root: Path) -> str:
    """Return the project name that makes ``<root>/acme/projects/<name>`` 99 characters long."""
    room = PROJECT_PATH_LENGTH - len(str(root / "acme" / "projects")) - 1
    assert 8 <= room <= 40, (
        f"the root {root} leaves {room} characters for the project name, which needs 8 to 40: "
        "point TMPDIR at a shorter folder"
    )
    return "island-" + "x" * (room - len("island-"))


def test_two_runs_in_two_processes(scenario_env: dict[str, str], scenario_cache: Path) -> None:
    link_binaries(scenario_cache, tuple(exe_filename(s) for s in ("mf6", "libmf6")))
    root = Path(tempfile.mkdtemp(prefix="h", dir=tempfile.gettempdir())).resolve()
    log = root.with_name(root.name + ".log")
    server = None
    try:
        name = _project_name(root)
        project = write_project(
            root / "acme" / "projects" / name,
            {"project.toml": island_files("calage")["project.toml"]},
        )
        assert len(str(project)) == PROJECT_PATH_LENGTH
        route = f"/v1/acme/{name}"
        argv = [sys.executable, "-m", "hydromodpy_server", "--root", str(root), "--port", "0"]
        with log.open("w", encoding="utf-8") as sink:
            server = subprocess.Popen(argv, env=scenario_env, stdout=sink, stderr=sink)

            # 1. The address comes first.
            def address() -> str | None:
                lines = log.read_text(encoding="utf-8").splitlines()
                found = [row for row in lines if row.startswith("serving on http://")]
                assert server.poll() is None, "\n".join(lines[-20:])
                return found[0].split()[-1] if found else None

            url = _until(address, 60, "the server printing its address")

            # 2. Two runs asked for together, in two processes.
            requests = {
                key: {"source": {"schema": SCHEMA, "config": document, "name": key}}
                for key, document in _documents().items()
            }
            ran = _jobs_end(url, route, _post_together(url, route, "run", requests))
            outcomes = {key: found["result"] for key, found in ran.items()}
            assert {key: (o["status"], o["run_dir"]) for key, o in outcomes.items()} == {
                key: ("completed", f"runs/{key}") for key in RECHARGES
            }

            # 3. What both runs left in the project.
            seals = {key: read_seal(project / outcomes[key]["run_dir"]) for key in RECHARGES}
            assert {seal.manifest_version for seal in seals.values()} == {4}
            for key in RECHARGES:
                assert seal_problems(project / "runs" / key) == [], key
            assert len({seal.identity.request_id for seal in seals.values()}) == 2
            status, listed = _ask(url, "POST", f"{route}/status", {})
            assert status == 200
            assert {item["name"]: item["status"] for item in listed} == dict.fromkeys(
                RECHARGES, "completed"
            )
            left = [
                path.relative_to(project).as_posix()
                for pattern in ("*.lock", "*.part")
                for path in (project / ".hmp").rglob(pattern)
            ]
            assert left == []
            stored = ProductStore(products_root(project)).entries()
            meshes = {entry.key for entry in stored if entry.kind == "mesh"}
            assert len(meshes) == 1, stored
            for key in RECHARGES:
                cited = {p.key for p in read_cited(project / "runs" / key) if p.kind == "mesh"}
                assert cited == meshes, key
            longest = max(len(str(path)) for path in project.rglob("*"))
            assert longest <= WINDOWS_PATH_LIMIT, longest

            # 4. Both replayed together, each reproduces its source to the bit.
            replays = {key: {"ref": key} for key in RECHARGES}
            replayed = _jobs_end(url, route, _post_together(url, route, "replay", replays))
            for key, found in replayed.items():
                assert found["result"]["run_dir"] == f"runs/{key}.v2"
                replay_dir = project / found["result"]["run_dir"]
                replay = read_seal(replay_dir).lineage.replay
                assert replay is not None
                assert replay.of == seals[key].identity.sim_id
                assert replay.class_ == "bit", replay.model_dump(mode="json", by_alias=True)
                assert seal_problems(replay_dir) == []
    finally:
        # 5. The server ends on a signal, and by force when it does not.
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        shutil.rmtree(root, ignore_errors=True)
        log.unlink(missing_ok=True)
