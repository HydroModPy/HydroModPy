"""The stopwatch times a block, keeps its line when the block fails, and says the process age."""

from __future__ import annotations

import builtins
import sys
from datetime import UTC

import pytest

from hydromodpy.core.runtime import stopwatch
from hydromodpy.core.runtime.stopwatch import (
    MEASURE_KINDS,
    Measure,
    max_rss_mb,
    measured,
    process_age_s,
)


@pytest.mark.parametrize("kind", MEASURE_KINDS)
def test_a_block_has_a_duration_a_utc_start_and_a_memory_peak(kind: str) -> None:
    with measured(kind, "build_mesh") as measure:
        assert measure.duration_s is None

    assert (measure.kind, measure.name) == (kind, "build_mesh")
    assert measure.duration_s is not None and measure.duration_s >= 0.0
    assert measure.started_at.tzinfo is UTC
    if sys.platform != "win32":
        assert measure.max_rss_mb is not None and measure.max_rss_mb > 0.0


def test_a_block_that_raises_is_still_measured() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with measured("step", "run_solver") as measure:
            raise RuntimeError("boom")

    assert measure.duration_s is not None and measure.duration_s >= 0.0


def test_a_stop_inside_the_block_is_still_measured() -> None:
    with pytest.raises(KeyboardInterrupt):
        with measured("solve", "flow_main::modflow6") as measure:
            raise KeyboardInterrupt

    assert measure.duration_s is not None


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


def test_the_process_has_a_positive_age_or_none() -> None:
    age = process_age_s()

    assert age is None or 0.0 <= age < 30 * 24 * 3600.0


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
