"""Report-intent helpers for site-selection workflows."""

from __future__ import annotations

from typing import Any


def site_selection_report_html_requested(config: Any) -> bool:
    """Return whether the final site-selection HTML report should be built."""

    return bool(getattr(config, "report_html_build_at_end", False))


__all__ = ["site_selection_report_html_requested"]
