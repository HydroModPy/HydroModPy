"""Wrapper to expose `ExecutionContext` from the external package.

This repository no longer provides an internal ExecutionContext; the external
package must be installed.
"""
try:
    from validity_frame.auto_capture.context import Context, ExecutionContext
except Exception as exc:  # pragma: no cover - environment dependent
    raise ImportError(
        "validity_frame external package not found; install it with 'pip install -e validity_frame'"
    ) from exc

__all__ = ["Context", "ExecutionContext"]
