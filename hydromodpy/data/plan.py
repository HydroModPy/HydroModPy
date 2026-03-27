"""Immutable runtime objects for resolved data-manager activation.

The planner emits one ``DataLoadPlan`` per launcher run. The plan is consumed
by orchestration code for transparency/debugging.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DataLoadPlan:
    """Resolved data-manager activation plan.

    ``explicit_types`` come from ``[data].types``.
    ``inferred_types`` are appended by planner rules.
    """

    explicit_types: tuple[str, ...] = field(default_factory=tuple)
    inferred_types: tuple[str, ...] = field(default_factory=tuple)
    reasons_by_type: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def types(self) -> tuple[str, ...]:
        """Return the ordered union of explicit and inferred manager types."""
        merged: list[str] = []
        seen: set[str] = set()
        # Keep deterministic order: explicit declarations first, then inferred.
        for type_name in (*self.explicit_types, *self.inferred_types):
            if type_name in seen:
                continue
            seen.add(type_name)
            merged.append(type_name)
        return tuple(merged)

    def has(self, type_name: str) -> bool:
        """Return ``True`` when *type_name* is active in the resolved plan."""
        normalized = str(type_name).strip().lower()
        return normalized in self.types

    def reasons_for(self, type_name: str) -> tuple[str, ...]:
        """Return planner reasons recorded for *type_name*."""
        normalized = str(type_name).strip().lower()
        return self.reasons_by_type.get(normalized, ())
