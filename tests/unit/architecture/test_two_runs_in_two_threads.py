"""Two runs in two threads of one process change nothing the other run reads (rule 15).

A child process writes two basin projects of different recharge, each with one
figure of its run, and notes the state of the process: the environment, the
working directory, the matplotlib backend and ``rcParams``, the handlers of the
``hydromodpy`` logger, the warning filters and the SIGTERM handler. It plays both
projects by ``hydromodpy.run`` in two threads, after a first run of a third
project has imported what a run imports, while a third thread notes the
environment and ``rcParams`` every 10 ms with the render lock held, then plays
both again one after the other. Four runs must seal, no state may change, no
``run.log`` may name the other run, and each run of the threads must hold the
values of its twin played alone. The global backend needs no solver binary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.scenarios.factory import basin_files
from tests.scenarios.launcher import isolated_env, play_script

pytestmark = [pytest.mark.scenario, pytest.mark.allow_subprocess, pytest.mark.timeout(600)]

FIGURE = "hydrograph"
"""A figure of the generated name table that a run of the global backend draws."""

EXEMPT = ("hydromodpy.config.check",)
"""The one module whose catch_warnings block is transitional (process_state.yaml, E61)."""

SCRIPT = f'''
import json
import logging
import os
import signal
import threading
import time
import warnings
from pathlib import Path

import matplotlib

import hydromodpy
from hydromodpy.display.style import RENDER_LOCK
from hydromodpy.results.record.values import stored_value_digests

ROOT = Path.cwd()
NAMES = ("basin_a", "basin_b")

# A first run imports what a run imports, so what a library sets when it is
# imported is part of the state the runs must keep.
hydromodpy.run(ROOT / "warm" / "project.toml")

# Before Python 3.14 catch_warnings is not safe across threads, so a library
# that uses it in two runs at once can leave a filter behind. The filters are
# therefore judged by who writes them: no module of hydromodpy may.
WRITERS = []
EXEMPT = {set(EXEMPT)!r}


def caller():
    import sys

    module = sys._getframe(2).f_globals.get("__name__", "")
    if module.startswith("hydromodpy") and module not in EXEMPT:
        WRITERS.append(module)


def spied(function):
    def wrapper(*args, **kwargs):
        caller()
        return function(*args, **kwargs)

    return wrapper


warnings.filterwarnings = spied(warnings.filterwarnings)
warnings.simplefilter = spied(warnings.simplefilter)
_enter = warnings.catch_warnings.__enter__


def enter(self):
    caller()
    return _enter(self)


warnings.catch_warnings.__enter__ = enter


def rc():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return {{key: repr(value) for key, value in matplotlib.rcParams.items()}}


def state():
    return {{
        "environ": dict(os.environ),
        "cwd": os.getcwd(),
        "backend": matplotlib.get_backend(),
        "rc": rc(),
        "handlers": [repr(h) for h in logging.getLogger("hydromodpy").handlers],
        "filters": [repr(entry) for entry in warnings.filters],
        "sigterm": repr(signal.getsignal(signal.SIGTERM)),
    }}


before = state()
seen, errors, done = [], [], threading.Event()


def watch():
    while not done.is_set():
        with RENDER_LOCK:
            if dict(os.environ) != before["environ"] or rc() != before["rc"]:
                seen.append(time.monotonic())
        time.sleep(0.01)


def play(name, **options):
    try:
        hydromodpy.run(ROOT / name / "project.toml", **options)
    except BaseException as error:  # noqa: BLE001 - reported to the parent
        errors.append(f"{{name}}: {{error!r}}")


watcher = threading.Thread(target=watch)
watcher.start()
threads = [threading.Thread(target=play, args=(name,)) for name in NAMES]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
done.set()
watcher.join()
after_threads = state()
for name in NAMES:
    play(name, force=True)
after = state()


def logged(name):
    path = ROOT / name / "runs" / name / "logs" / "run.log"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def digests(folder):
    return {{key: str(value) for key, value in stored_value_digests(folder).digests.items()}}


report = {{
    "errors": errors,
    "changed_while_running": len(seen),
    "changed": sorted(
        key
        for key in before
        if key != "filters" and (before[key] != after_threads[key] or before[key] != after[key])
    ),
    "writers": sorted(set(WRITERS)),
    "filters_left": sorted(set(after["filters"]) - set(before["filters"])),
    "runs": sorted(
        str(path.relative_to(ROOT)) for name in NAMES for path in (ROOT / name / "runs").iterdir()
    ),
    "logs": {{name: logged(name) for name in NAMES}},
    "twins": {{
        name: digests(ROOT / name / "runs" / name) == digests(ROOT / name / "runs" / f"{{name}}.v2")
        for name in NAMES
    }},
    "figures": {{
        name: sorted(p.name for p in (ROOT / name / "runs" / name / "figures").glob("{FIGURE}*"))
        for name in NAMES
    }},
}}
(ROOT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
'''


def _project(name: str, recharge: float) -> str:
    """Return the basin named *name*, with *recharge* mm per day and one figure."""
    text = basin_files()["project.toml"]
    for old, new in (
        ('[simulation]\nname = "basin"', f'[simulation]\nname = "{name}"'),
        ("values = [1.5]", f"values = [{recharge}]"),
        ("[display]\nenabled = false", f'[display]\nenabled = true\nfigures = ["{FIGURE}"]'),
    ):
        assert old in text, old
        text = text.replace(old, new)
    return text


def test_two_runs_in_two_threads_keep_the_process_as_it_was(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    env = isolated_env(tmp_path / "home", cache, tmp_path / "state", tmp_path / "tmp")
    files = {
        "basin_a/project.toml": _project("basin_a", 1.5),
        "basin_b/project.toml": _project("basin_b", 3.0),
        "warm/project.toml": _project("warm", 1.0),
    }

    played = play_script("two_threads", files, SCRIPT, tmp_path / "play", env, cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-3000:]
    report = json.loads((played.root / "report.json").read_text(encoding="utf-8"))
    assert report["errors"] == []
    assert report["runs"] == [
        "basin_a/runs/basin_a",
        "basin_a/runs/basin_a.v2",
        "basin_b/runs/basin_b",
        "basin_b/runs/basin_b.v2",
    ]
    assert report["changed"] == []
    assert report["changed_while_running"] == 0
    for name, other in (("basin_a", "basin_b"), ("basin_b", "basin_a")):
        log = report["logs"][name]
        assert log, f"{name} wrote no run.log"
        assert other not in log, f"the run.log of {name} names {other}"
        assert report["figures"][name], f"{name} drew no {FIGURE}"
    assert report["writers"] == [], f"modules of hydromodpy set warning filters: {report}"
    assert report["twins"] == {"basin_a": True, "basin_b": True}
