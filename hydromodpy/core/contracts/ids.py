"""Typed IDs used across the simulation, calibration, and observation stack.

These are ``NewType`` aliases over ``str``. They tighten type-checker
diagnostics (an ``SimId`` cannot be silently mixed with a ``RunId``) while
keeping zero runtime cost. Call sites are migrated incrementally; this
module only exposes the names so future code can adopt them.
"""

from __future__ import annotations

from typing import NewType

SimId = NewType("SimId", str)
RunId = NewType("RunId", str)
StationId = NewType("StationId", str)
TrialId = NewType("TrialId", str)
SessionId = NewType("SessionId", str)


__all__ = (
    "RunId",
    "SessionId",
    "SimId",
    "StationId",
    "TrialId",
)
