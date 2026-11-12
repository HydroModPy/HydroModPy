"""The stopwatch times a block, keeps its line when the block fails, and says the process age."""

from __future__ import annotations

import builtins
import sys

import pytest

from hydromodpy.core.runtime import stopwatch
from hydromodpy.core.runtime.stopwatch import Measure, max_rss_mb, measured


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="A measure kind is one of step, solve, figure, export"):
        Measure(kind="trial", name="t0001", started_at=None)


def test_the_memory_is_none_where_resource_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _no_resource(name: str, *args: object, **kwargs: object) -> object:
        if name == "resource":
            raise ImportError("no resource module on this platform")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "resource", raising=False)
    monkeypatch.setattr(builtins, "__import__", _no_resource)

    assert max_rss_mb() is None
    with measured("figure", "heads_map") as measure:
        pass
    assert measure.max_rss_mb is None


def test_the_process_age_is_none_without_proc_and_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = builtins.open
    real_import = builtins.__import__

    def _no_proc(file: object, *args: object, **kwargs: object) -> object:
        if str(file).startswith("/proc/"):
            raise OSError("no /proc on this platform")
        return real_open(file, *args, **kwargs)

    def _no_psutil(name: str, *args: object, **kwargs: object) -> object:
        if name == "psutil":
            raise ImportError("psutil is an extra")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _no_proc)
    monkeypatch.delitem(sys.modules, "psutil", raising=False)
    monkeypatch.setattr(builtins, "__import__", _no_psutil)

    assert stopwatch.process_age_s() is None
