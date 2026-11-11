"""A two-site, two-recipe ``[sites]`` project and a fake worker for the launcher tests.

The fake worker stands in for ``hmp run <case>.toml``: the launcher starts it
exactly as it starts the real one, in a process of its own with the
environment of a launched case. It records what it saw (its flags, its
environment) under ``<project>/seen/``, then behaves as ``fake.json`` says
for its case: ``complete`` writes a seal (the hash of the plan, nothing
else) and a completed outcome, ``fail``
writes a failed outcome and exits 15, ``die`` claims the case and exits
without writing its end, ``refuse`` exits 14 before any claim. The
``session_die`` and ``session_complete`` modes stand in for a calibration:
the worker opens ``sessions/<case>/`` as the real one does (a bare
``--resume`` reopens the latest session, else a new version is reserved),
writes its descriptor and outcome, then dies or completes. A prepare
child (``--until``) writes one file and its sidecar into the shared
``data/`` folder when ``fake.json`` asks for ``register``, through the cache
index of the package under the lock of the chronicle, so the shared folder is
exercised for real; it records when it started and ended, sleeps
``prepare_sleep`` seconds, and fails with a scratch left behind (``prepare =
"fail"``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from hydromodpy.project.launch import local as launch_local
from hydromodpy.project.launch import prepare as launch_prepare
from tests._helpers.sealed_runs import manifest_document

PROJECT = """\
[workspace]
data_dir = "data"

[workflow]
mode = "simulation"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["dem"]

[[data.dem.sources]]
source = "file"
path = "dem.tif"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.bc.drainage]

[sites]
table = "sites.csv"
{sites_extra}
[sites.recipes]
base = "project.toml"
k2e_5 = {{ file = "project.toml", set = {{ "flow.param.K.field.value" = 2e-5 }} }}

[sites.bind]
"site.name" = "site"
"geographic.catchment.x_outlet" = "x_outlet"
"geographic.catchment.y_outlet" = "y_outlet"
"""

CASES = ("alpha-base", "alpha-k2e_5", "beta-base", "beta-k2e_5")

FAKE_WORKER = r"""
import json
import os
import socket
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

case = Path(sys.argv[1]).resolve()
flags = sys.argv[2:]
case_id = case.stem
root = case.parent.parent.parent
phase = "prepare" if "--until" in flags else "run"
behaviors = root / "fake.json"
behavior = json.loads(behaviors.read_text()).get(case_id, {}) if behaviors.is_file() else {}
seen = root / "seen"
seen.mkdir(exist_ok=True)
record = {
    "flags": flags,
    "pid": os.getpid(),
    "env": {key: os.environ.get(key) for key in (
        "HMP_THREADS_PER_CASE", "HMP_LAUNCHED_CASE", "HMP_SET_flow__param__K__field__value",
    )},
}

if phase == "prepare":
    import time

    record["started"] = time.time()
    time.sleep(float(behavior.get("prepare_sleep", 0)))
    if behavior.get("prepare") == "fail":
        # The preprocessing tree a failed prepare leaves in its scratch.
        scratch = root / ".hmp" / "scratch" / f"{case_id}.p{os.getpid()}" / "_preprocessing"
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "dem.tif").write_bytes(b"0" * 64)
        (seen / f"{case_id}.prepare.json").write_text(json.dumps(record))
        sys.exit(16)
    if behavior.get("register"):
        from hydromodpy.data.provenance.sidecars import FORMER_CACHE_DATABASE, CacheIndex

        data = root / "data"
        index = CacheIndex(data)
        folder = data / "discharge"
        stem = f"discharge_fake_{case_id}"
        with index.chronicle(folder, stem):
            payload = folder / f"{stem}_D.csv"
            payload.write_text("date,value\n2000-01-01,1\n")
            index.record(payload, variable="discharge", source="fake", station_id=case_id)
        record["payload"] = payload.relative_to(root).as_posix()
        record["sidecar"] = payload.with_name(payload.name + ".json").is_file()
        record["lock"] = (folder / f".{stem}.lock").is_file()
        record["database"] = (data / FORMER_CACHE_DATABASE).exists()
    record["ended"] = time.time()
    (seen / f"{case_id}.prepare.json").write_text(json.dumps(record))
    sys.exit(0)

mode = behavior.get("run", "complete")
(seen / f"{case_id}.run.json").write_text(json.dumps(record))
if mode == "refuse":
    sys.exit(14)
if mode.startswith("session_"):
    import csv
    from hydromodpy.calibration.runners.session import open_session_dir
    from hydromodpy.results.session.descriptor import (
        SessionCase, SessionDescriptor, read_session, write_session,
    )

    with open(case.parent / "cases.csv", newline="", encoding="utf-8") as handle:
        planned = {row["case_id"]: row["config_hash"] for row in csv.DictReader(handle)}
    session_dir, reopened = open_session_dir(root, case_id, resume="--resume" in flags)
    started = datetime.now(UTC)
    if reopened:
        descriptor = read_session(session_dir).model_copy(
            update={"status": "running", "ended_at": None, "error_message": None}
        )
    else:
        case_hash = planned[case_id]
        descriptor = SessionDescriptor(
            session_id=uuid.uuid4().hex, case_id=case_id, config_hash=case_hash,
            cases={case_id: SessionCase(
                config_hash=case_hash, config_file="config.toml", cost_name="nse",
            )},
            hydromodpy_version="0", method="grid", cost_name="nse", started_at=started,
        )
    write_session(session_dir, descriptor)
    outcome = {
        "schema": "hydromodpy.outcome.v1", "case_id": case_id, "site": case_id.split("-")[0],
        "project": root.name, "attempt": 1, "attempt_id": uuid.uuid4().hex,
        "status": "running", "written_by": "worker", "started_at": started.isoformat(),
        "host": socket.gethostname(), "pid": os.getpid(),
    }
    (session_dir / "outcome.json").write_text(json.dumps(outcome))
    if mode == "session_die":
        os._exit(9)
    ended = datetime.now(UTC)
    write_session(session_dir, descriptor.model_copy(update={"status": "completed", "ended_at": ended}))
    outcome.update(status="completed", ended_at=ended.isoformat(), exit_code=0)
    (session_dir / "outcome.json").write_text(json.dumps(outcome))
    sys.exit(0)
run_dir = root / "runs" / case_id
run_dir.mkdir(parents=True, exist_ok=True)
now = datetime.now(UTC).isoformat()
outcome = {
    "schema": "hydromodpy.outcome.v1", "case_id": case_id, "site": case_id.split("-")[0],
    "project": root.name, "attempt": 1, "attempt_id": uuid.uuid4().hex,
    "sim_id": str(uuid.uuid4()), "status": "running", "written_by": "worker",
    "started_at": now, "host": socket.gethostname(), "pid": os.getpid(),
}
(run_dir / "outcome.json").write_text(json.dumps(outcome))
if mode == "die":
    os._exit(9)
if mode == "fail":
    outcome.update(status="failed", ended_at=now, exit_code=15,
                   error={"type": "SolverError", "message": "boom"}, log_tail=["boom"])
    (run_dir / "outcome.json").write_text(json.dumps(outcome))
    sys.exit(15)
import csv

# The seal holds the hash of the plan, as a real worker of the plan seals it.
with open(case.parent / "cases.csv", newline="", encoding="utf-8") as handle:
    planned = {row["case_id"]: row["config_hash"] for row in csv.DictReader(handle)}
manifest = json.loads(@MANIFEST@)
manifest["identity"]["solution_key"] = planned[case_id]
(run_dir / "manifest.json").write_text(json.dumps(manifest))
outcome.update(status="completed", ended_at=now, exit_code=0)
(run_dir / "outcome.json").write_text(json.dumps(outcome))
"""


def write_project(tmp_path: Path, *, sites_extra: str = "") -> Path:
    """Write the two-site, two-recipe project under *tmp_path* and return its root."""
    project = tmp_path / "campaign"
    (project / "data").mkdir(parents=True)
    (project / "dem.tif").write_bytes(b"never read by the plan")
    (project / "project.toml").write_text(PROJECT.format(sites_extra=sites_extra), encoding="utf-8")
    (project / "sites.csv").write_text(
        "site,x_outlet,y_outlet\nalpha,389285.9,6816518.7\nbeta,377120.0,6831410.0\n",
        encoding="utf-8",
    )
    write_behaviour(project, {})
    return project


def write_behaviour(project: Path, behaviour: dict[str, dict[str, object]]) -> None:
    """Say how the fake worker behaves for each case."""
    (project / "fake.json").write_text(json.dumps(behaviour), encoding="utf-8")


def events(journal: Path, name: str) -> list[dict]:
    """Return the journal lines of the event *name*, in order."""
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line["event"] == name]


def seen(project: Path, case_id: str, phase: str = "run") -> dict:
    """Return what the fake worker of *case_id* recorded in *phase*."""
    return json.loads((project / "seen" / f"{case_id}.{phase}.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make the launcher start the fake worker instead of ``hmp run``."""
    script = tmp_path / "fake_worker.py"
    script.write_text(
        FAKE_WORKER.replace("@MANIFEST@", repr(json.dumps(manifest_document()))), encoding="utf-8"
    )

    def worker(case, flags=(), environment_flags=()):
        return [sys.executable, str(script), str(case.path), *flags, *environment_flags]

    def preparer(case, environment_flags=()):
        return [
            sys.executable,
            str(script),
            str(case.path),
            "--until",
            "load_data",
            *environment_flags,
        ]

    monkeypatch.setattr(launch_local, "worker_command", worker)
    monkeypatch.setattr(launch_prepare, "prepare_command", preparer)
    monkeypatch.setattr(launch_prepare, "POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(launch_local, "POLL_INTERVAL_S", 0.05)
    return script
