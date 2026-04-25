"""Auto-conversion of the deprecated [model_calibration] TOML section.

Removed in a future release. Emits a DeprecationWarning and rewrites the
section in-place to [calibration] so the rest of the dispatch can ignore
the old name.
"""

from __future__ import annotations

import warnings


def normalize_legacy_calibration_section(raw: dict) -> dict:
    """Rename top-level [model_calibration] to [calibration] in `raw`.

    No-op when the section is absent or [calibration] is already present.
    """
    if "model_calibration" not in raw:
        return raw
    if "calibration" in raw:
        warnings.warn(
            "[model_calibration] and [calibration] both present in TOML; "
            "ignoring [model_calibration].",
            DeprecationWarning,
            stacklevel=2,
        )
        raw.pop("model_calibration")
        return raw
    warnings.warn(
        "[model_calibration] is deprecated and will be removed in a future "
        "release. Rename the section to [calibration].",
        DeprecationWarning,
        stacklevel=2,
    )
    raw["calibration"] = raw.pop("model_calibration")
    return raw


__all__ = ["normalize_legacy_calibration_section"]
