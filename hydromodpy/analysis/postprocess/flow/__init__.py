"""Flow-family postprocess helpers.

Keep imports lazy so flow config can be loaded without optional runtime
dependencies used by matching-stream diagnostics.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "apply_intermittency_columns",
    "IntermittencyPostprocessConfig",
    "MatchingStreams",
    "run_matching_streams",
]


def __getattr__(name: str) -> Any:
    if name == "apply_intermittency_columns":
        from hydromodpy.analysis.postprocess.flow.intermittency import apply_intermittency_columns

        return apply_intermittency_columns

    if name == "IntermittencyPostprocessConfig":
        from hydromodpy.analysis.postprocess.flow.intermittency_config import (
            IntermittencyPostprocessConfig,
        )

        return IntermittencyPostprocessConfig

    if name in {"MatchingStreams", "run_matching_streams"}:
        from hydromodpy.analysis.postprocess.flow.matching_streams import (
            MatchingStreams,
            run_matching_streams,
        )

        return {
            "MatchingStreams": MatchingStreams,
            "run_matching_streams": run_matching_streams,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
