"""Record which files of hydromodpy/ run code during ``hmp run project.toml``.

This file is never imported. The scenario reads its text and plays it as
``python -c`` in the folder of the project. From the first call in
``cli/commands/run.py:run`` the profiler notes each file of ``hydromodpy/`` where a
function is called. A module body or a class body is not a call, so a file
that is only imported late does not count. The run happens in this process,
and ``trace.json`` is written to the project folder on exit, with ``called`` (the
files with a call) and ``loaded`` (the files imported at exit), both relative to
``hydromodpy/`` and sorted.
"""

import atexit
import importlib.util
import inspect
import json
import sys
import threading
from pathlib import Path

ROOT = Path(importlib.util.find_spec("hydromodpy").origin).resolve().parent.as_posix() + "/"
ENTRY = ROOT + "cli/commands/run.py"
called = set()
started = [False]


def profile(frame, event, arg):
    if event != "call":
        return
    name = Path(frame.f_code.co_filename).as_posix()
    if not started[0]:
        if name == ENTRY and frame.f_code.co_name == "run":
            started[0] = True
        else:
            return
    # A module or a class body runs without CO_OPTIMIZED; only a function has it.
    if name.startswith(ROOT) and frame.f_code.co_flags & inspect.CO_OPTIMIZED:
        called.add(name[len(ROOT) :])


def dump():
    sys.setprofile(None)
    threading.setprofile(None)
    loaded = {
        Path(module.__file__).as_posix()[len(ROOT) :]
        for module in list(sys.modules.values())
        if getattr(module, "__file__", None) and Path(module.__file__).as_posix().startswith(ROOT)
    }
    payload = {"called": sorted(called), "loaded": sorted(loaded)}
    Path("trace.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")


atexit.register(dump)

from hydromodpy.cli.main import main  # noqa: E402

sys.setprofile(profile)
threading.setprofile(profile)
main(["run", "project.toml", "--no-display"])
