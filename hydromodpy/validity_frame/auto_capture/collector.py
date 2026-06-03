"""Wrapper that delegates to the external `validity_frame` package.

This repository no longer provides an internal implementation; the external
package must be installed. If it is not installed, importing this module
will raise an informative ImportError.
"""
try:
    from validity_frame.auto_capture.collector import (
        AutoCaptureCollector,
        AutoCaptureSnapshot,
    )
except Exception as exc:  # pragma: no cover - user environment dependent
    raise ImportError(
        "validity_frame external package not found; install it with 'pip install -e validity_frame'"
    ) from exc

__all__ = ["AutoCaptureCollector", "AutoCaptureSnapshot"]
