"""Development import shim for the ``validity_frame`` src-layout package."""

from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent / "src" / "validity_frame"
if _SRC_PACKAGE.is_dir():
    __path__.append(str(_SRC_PACKAGE))

from .auto_capture.collector import AutoCaptureCollector
from .auto_capture.context import ExecutionContext
from .loader import create_validity_frame
from .validity import ValidityFrame

__all__ = [
    "AutoCaptureCollector",
    "ExecutionContext",
    "ValidityFrame",
    "create_validity_frame",
]
