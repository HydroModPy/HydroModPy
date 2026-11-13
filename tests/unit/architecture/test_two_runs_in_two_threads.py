"""Two runs in two threads of one process change nothing the other run reads (rule 15).

A cold child process writes two basin projects of different recharge, each with one
figure of the request path, and notes the state of the process: the environment, the
working directory, the matplotlib backend (read without resolving it) and ``rcParams``,
the font files, the handlers of the ``hydromodpy`` logger, the warning filters and the
SIGTERM handler. The child imports no ``hydromodpy`` submodule before the threads start.
It plays both projects by ``hydromodpy.run`` in two threads while a third thread notes
the environment and ``rcParams`` every 10 ms with no lock, then plays both again. Four runs must seal, no state may change,
the font list may only gain the files ``display/theme.py`` registers, no ``run.log`` may
name the other run, and each run of the threads must hold the values of its twin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.display.theme import FONT_FILES
from tests.scenarios.factory import basin_files
from tests.scenarios.launcher import isolated_env, play_script

pytestmark = [pytest.mark.scenario, pytest.mark.allow_subprocess, pytest.mark.timeout(600)]

FIGURE = "discharge"
"""A series the request path draws in each lumped run, which has no mesh for a map."""

PRELOADED = ("flopy", "geopandas", "pandera", "pyogrio", "pyproj", "zarr")
"""Libraries that write the environment on import, loaded before the threads."""

EXEMPT = ("hydromodpy.config.check",)
"""The one module whose catch_warnings block is transitional (process_state.yaml, E61)."""

SCRIPT = f'''
import json
import logging
import os
import signal
import threading
import sys
import time
import warnings
from importlib import import_module
from pathlib import Path

import matplotlib
from matplotlib import font_manager

for name in {PRELOADED!r}:
    import_module(name)
import hydromodpy

assert not any(m.startswith("hydromodpy.display") for m in sys.modules), "display is loaded"
ROOT = Path.cwd()
NAMES = ("basin_a", "basin_b")
# catch_warnings is not safe across threads before Python 3.14, so the filters are
# judged by who writes them: no function of hydromodpy may (an import may).
WRITERS = []
EXEMPT = {set(EXEMPT)!r}


def caller():
    frame = sys._getframe(2)
    module = frame.f_globals.get("__name__", "")
    if module.startswith("hydromodpy") and module not in EXEMPT and frame.f_code.co_name != "<module>":
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
    return {{key: repr(value) for key, value in dict.items(matplotlib.rcParams)}}


def state():
    return {{
        "environ": dict(os.environ),
        "cwd": os.getcwd(),
        "backend": repr(matplotlib.rcParams._get_backend_or_none()),
        "rc": rc(),
        "fonts": sorted({{Path(f.fname).name for f in font_manager.fontManager.ttflist}}),
        "handlers": [repr(h) for h in logging.getLogger("hydromodpy").handlers],
        "filters": [repr(entry) for entry in warnings.filters],
        "sigterm": repr(signal.getsignal(signal.SIGTERM)),
    }}


before = state()
seen, errors, done = [], [], threading.Event()


def watch():
    while not done.is_set():
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


def digests(folder):
    from hydromodpy.results.record.values import stored_value_digests

    return {{key: str(value) for key, value in stored_value_digests(folder).digests.items()}}


report = {{
    "errors": errors,
    "changed_while_running": len(seen),
    "changed": sorted(
        key
        for key in before
        if key not in ("filters", "fonts") and (before[key] != after_threads[key] or before[key] != after[key])
    ),
    "fonts_lost": sorted(set(before["fonts"]) - set(after["fonts"])),
    "fonts_gained": sorted(set(after["fonts"]) - set(before["fonts"])),
    "writers": sorted(set(WRITERS)),
    "runs": sorted(
        str(path.relative_to(ROOT)) for name in NAMES for path in (ROOT / name / "runs").iterdir()
    ),
    "logs": {{name: (ROOT / name / "runs" / name / "logs" / "run.log").read_text() for name in NAMES}},
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
        (
            "[display]\nenabled = false",
            f'[display]\nenabled = true\n\n[[display.figure]]\nvariable = "{FIGURE}"',
        ),
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
    assert report["fonts_lost"] == []
    assert set(report["fonts_gained"]) <= set(FONT_FILES), report["fonts_gained"]
    assert report["changed_while_running"] == 0
    for name, other in (("basin_a", "basin_b"), ("basin_b", "basin_a")):
        log = report["logs"][name]
        assert log, f"{name} wrote no run.log"
        assert other not in log, f"the run.log of {name} names {other}"
        assert report["figures"][name], f"{name} drew no {FIGURE}"
    assert report["writers"] == [], f"modules of hydromodpy set warning filters: {report}"
    assert report["twins"] == {"basin_a": True, "basin_b": True}
