"""Import-regression tests for geographic modules."""

from __future__ import annotations

import importlib


def test_geographic_config_import_does_not_trigger_circular_import() -> None:
    """Synthetic geographic support should not recurse back into GeographicConfig."""

    module = importlib.import_module("hydromodpy.geographic.geographic_config")

    assert hasattr(module, "GeographicConfig")
