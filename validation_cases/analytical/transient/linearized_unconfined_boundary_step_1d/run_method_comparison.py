"""Compatibility entry point for the canonical boundary-step comparison runner."""

from __future__ import annotations

from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d.run_comparison import (
    DEFAULT_COMPARISON_ID,
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT_ROOT,
    _build_parser,
    _build_payload,
    main,
)

__all__ = (
    "DEFAULT_COMPARISON_ID",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_OUTPUT_ROOT",
    "_build_parser",
    "_build_payload",
    "main",
)


if __name__ == "__main__":
    raise SystemExit(main())
