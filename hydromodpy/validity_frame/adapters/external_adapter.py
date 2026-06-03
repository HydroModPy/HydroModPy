"""Adapter that prefers the external `validity_frame` package and falls back
to the internal implementation when the external package is not available.
"""
try:
    from validity_frame import AutoCaptureCollector, ExecutionContext  # type: ignore
except Exception as exc:  # pragma: no cover - environment dependent
    raise ImportError(
        "validity_frame external package not found; install it with 'pip install -e validity_frame'"
    ) from exc

__all__ = ["AutoCaptureCollector", "ExecutionContext"]
