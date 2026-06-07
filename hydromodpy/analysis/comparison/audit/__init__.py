"""Post-run equivalence audit for simulation-comparison experiments."""

from __future__ import annotations

from .audit_engine import build_equivalence_audit
from .audit_render import write_audit_files

__all__ = (
    "build_equivalence_audit",
    "write_audit_files",
)
