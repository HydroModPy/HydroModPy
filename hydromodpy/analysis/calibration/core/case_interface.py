"""
Case interface layer for calibration.

This module defines the two core building blocks used by all case-specific
implementations:

1) `AbstractCalibrationCase`
   The abstract class that each case must inherit. It specifies the required
   methods expected by the generic orchestrator:
   - validate case-specific config,
   - build runtime context (observed series + simulator + parameter order),
   - optionally enrich outputs after calibration.

2) `CalibrationCaseContext`
   The typed container returned by `build_case(...)`. It carries the minimum
   runtime information needed by the generic calibration pipeline.

Why this module exists
----------------------
- Keep the contract explicit and centralized.
- Ensure all cases expose a consistent API.
- Detect integration mistakes early with clear errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(slots=True)
class CalibrationCaseContext:
    """
    Canonical output returned by a case implementation before calibration.

    Attributes
    ----------
    observed : array-like
        Target time series used for objective evaluation.
    simulator : callable
        Forward model adapter with signature `simulator(params_dict) -> series`.
    parameter_order : tuple[str, ...]
        Canonical order of model parameters expected by calibration vectors.
    chronicle : Mapping[str, Any] | None
        Optional case-specific chronicle payload.
    metadata : dict[str, Any]
        Optional case-specific metadata.
    """

    observed: Any
    simulator: Callable[[Mapping[str, float]], Any]
    parameter_order: tuple[str, ...]
    chronicle: Mapping[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.parameter_order = tuple(str(name).strip() for name in self.parameter_order)
        if not self.parameter_order:
            raise ValueError("parameter_order cannot be empty")
        if any(not name for name in self.parameter_order):
            raise ValueError("parameter_order cannot contain empty names")
        if len(set(self.parameter_order)) != len(self.parameter_order):
            raise ValueError("parameter_order contains duplicate names")
        if not callable(self.simulator):
            raise TypeError("simulator must be callable")
        if self.chronicle is not None:
            self.chronicle = dict(self.chronicle)
        self.metadata = dict(self.metadata)


class AbstractCalibrationCase(ABC):
    """
    Strict abstract interface for calibration cases.

    Required members:
    - `CASE_NAME` (str)
    - `validate_case_config(chronicle_section, calibration_section, full_config) -> Mapping`
    - `build_case(case_config, calibration_section, full_config) -> CalibrationCaseContext`
    - `build_case_outputs(...) -> Mapping` (default implementation returns empty mapping)
    """

    CASE_NAME = ""

    @abstractmethod
    def validate_case_config(
        self,
        chronicle_section: Mapping[str, Any],
        *,
        calibration_section: Mapping[str, Any],
        full_config: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Validate and normalize the case-specific `[chronicle]` section."""

    @abstractmethod
    def build_case(
        self,
        case_config: Mapping[str, Any],
        *,
        calibration_section: Mapping[str, Any],
        full_config: Mapping[str, Any],
    ) -> CalibrationCaseContext:
        """Build observed data, simulator adapter and parameter order for calibration."""

    def build_case_outputs(
        self,
        *,
        config: Mapping[str, Any],
        case_config: Mapping[str, Any],
        case_context: CalibrationCaseContext,
        calibration_engine,
        result,
        settings: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """
        Optional case-specific payload enrichment.

        Default behavior returns an empty mapping.
        """
        _ = config, case_config, case_context, calibration_engine, result, settings
        return {}


def normalize_case_name(name):
    """Return canonical case name used in registries and CLI."""
    key = str(name).strip().lower()
    if not key:
        raise ValueError("case name cannot be empty")
    return key


def validate_case_implementation(case_implementation):
    """
    Validate case implementation shape and return canonical case name.

    This check keeps runner/registry errors explicit and early.
    """
    if case_implementation is None:
        raise TypeError("case_implementation cannot be None")

    if not isinstance(case_implementation, AbstractCalibrationCase):
        raise TypeError(
            "case_implementation must inherit AbstractCalibrationCase and implement "
            "validate_case_config(...) and build_case(...)"
        )

    case_name = normalize_case_name(case_implementation.CASE_NAME)
    return case_name


# Public API boundary for this module.
# Why this list matters:
# - It documents which symbols are intended for external use.
# - It prevents helper/internal names from being exported by wildcard imports.
# - It keeps refactoring safer: code outside this module should depend only on
#   these names.
__all__ = (
    "AbstractCalibrationCase",
    "CalibrationCaseContext",
    "normalize_case_name",
    "validate_case_implementation",
)
