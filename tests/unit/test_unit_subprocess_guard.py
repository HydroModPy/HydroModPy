from __future__ import annotations

import importlib
import subprocess
import sys

import pytest


def test_unit_guard_keeps_popen_class_shape() -> None:
    assert isinstance(subprocess.Popen, type)

    if sys.platform == "win32":
        windows_utils = importlib.import_module("asyncio.windows_utils")
        assert isinstance(windows_utils.Popen, type)


def test_unit_guard_blocks_direct_popen_calls() -> None:
    with pytest.raises(RuntimeError, match="subprocess is forbidden in unit/"):
        subprocess.Popen([sys.executable, "-c", "print('blocked')"])
