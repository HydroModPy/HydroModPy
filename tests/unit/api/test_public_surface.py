"""Public surface snapshot for the functional facade (interface refactor).

Locks which symbols ``hydromodpy`` exposes at the top level so a removed
verb cannot silently reappear and a new one is a deliberate edit here.
"""

from __future__ import annotations

import pytest

import hydromodpy as hmp

pytestmark = [pytest.mark.fast]

# Verbs that must stay reachable as ``hmp.<name>``.
PRESENT = (
    "open",
    "read",
    "export",
    "run",
    "calibrate",
    "index",
    "compare_pair",
    "report",
    "doctor",
)

# Verbs removed by the interface refactor: merged into ``hmp.open`` /
# ``hmp.run`` dispatch. They must not come back.
REMOVED = ("open_catalog", "overview", "compare", "mesh", "testbed")


@pytest.mark.parametrize("name", PRESENT)
def test_present_symbol(name: str) -> None:
    assert hasattr(hmp, name), f"hmp.{name} missing"
    assert name in hmp.__all__


@pytest.mark.parametrize("name", REMOVED)
def test_removed_symbol(name: str) -> None:
    assert name not in hmp.__all__, f"hmp.{name} must not be in __all__"
    with pytest.raises(AttributeError):
        getattr(hmp, name)


def test_open_catalog_function_is_gone() -> None:
    with pytest.raises(AttributeError):
        hmp.open_catalog  # noqa: B018
