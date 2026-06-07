"""Helpers to make Whitebox-backed tests deterministic."""

from __future__ import annotations

import pytest


def configure_whitebox_single_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reduce Whitebox run-to-run variance by forcing one worker."""
    monkeypatch.setenv("RAYON_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("NUMEXPR_NUM_THREADS", "1")

    from hydromodpy.spatial.delineation import (
        clear_whitebox_backend_cache,
        get_whitebox_backend,
    )

    clear_whitebox_backend_cache()
    tool = get_whitebox_backend()
    env = getattr(tool.raster, "_env", None)
    if env is not None and hasattr(env, "max_procs"):
        env.max_procs = 1
