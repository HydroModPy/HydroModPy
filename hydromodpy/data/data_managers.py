"""Runtime container for active data-manager families.

Design note
-----------
``DataManagers`` is intentionally thin: it only stores the resolved ordered
type list used by orchestration code. Validation and inference live in:

- ``DataManagersConfig`` for schema/normalization,
- ``DataPlanner`` for explicit + inferred activation rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.data.plan import DataLoadPlan


@dataclass(slots=True)
class DataManagers:
    """Runtime view of active data-manager types."""

    types: list[str]

    @classmethod
    def from_config(cls, config: DataManagersConfig) -> DataManagers:
        """Build runtime container from validated declarative config."""
        return cls(types=list(config.types))

    @classmethod
    def from_plan(cls, plan: DataLoadPlan) -> DataManagers:
        """Build runtime container from resolved explicit+inferred plan."""
        return cls(types=list(plan.types))
