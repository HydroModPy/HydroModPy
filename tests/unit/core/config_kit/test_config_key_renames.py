"""Moving a TOML key must not go unseen by the files that already use it.

Every configuration model forbids unknown keys, so a key that moves is a hard break
for every project file at once. The rows of ``schema/changes.toml`` say where a key
went, the migration reads a file under the new name, and ``warn_old_form`` tells the
reader of the file, with both names, what to write instead. This file holds what the
base of the models owes that seam: the warning reaches its reader, and a model never
accepts a key it does not hold.
"""

from __future__ import annotations

import pytest
from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase


class _Engine(HydroModelBase):
    """A model whose ``engine`` key used to be called ``method``."""

    engine: str = Field(default="grid", description="Optimizer name.")


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _Engine.model_validate({"methode": "optuna"})


# Python's own filters when no -W option is given, first match wins: a
# DeprecationWarning raised outside __main__ is dropped before anything prints it.
_PYTHON_DEFAULT_FILTERS = (
    ("default", DeprecationWarning, "__main__"),
    ("ignore", DeprecationWarning, ""),
    ("ignore", PendingDeprecationWarning, ""),
    ("ignore", ImportWarning, ""),
    ("ignore", ResourceWarning, ""),
)
