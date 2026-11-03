"""Public surface snapshot for the functional facade (interface refactor).

Locks which symbols ``hydromodpy`` exposes at the top level so a removed
verb cannot silently reappear and a new one is a deliberate edit here. A name
removed before the first stable version is gone, with no entry. From that version
on a name that moves keeps working for its delay, through ``OLD_NAMES``.
"""

from __future__ import annotations

import pytest

import hydromodpy as hmp
from hydromodpy._lazy import OLD_NAMES, OldName

pytestmark = [pytest.mark.fast]

# Verbs that must stay reachable as ``hmp.<name>``.
PRESENT = (
    "open",
    "index",
    "read",
    "export",
    "run",
    "calibrate",
    "compare",
    "compare_pair",
    "report",
    "doctor",
)

# Verbs removed by the interface refactor, before the first stable version:
# merged into ``hmp.open`` / ``hmp.run`` dispatch. They must not come back.
REMOVED = ("open_catalog", "overview", "mesh", "testbed")


@pytest.mark.parametrize("name", PRESENT)
def test_present_symbol(name: str) -> None:
    assert hasattr(hmp, name), f"hmp.{name} missing"
    assert name in hmp.__all__


@pytest.mark.parametrize("name", REMOVED)
def test_a_name_removed_before_the_tag_has_no_entry_and_is_gone(name: str) -> None:
    assert name not in hmp.__all__, f"hmp.{name} must not be in __all__"
    assert name not in OLD_NAMES
    with pytest.raises(AttributeError):
        getattr(hmp, name)


@pytest.mark.parametrize(
    ("old", "new"), [("old_run", "run"), ("OldProject", "Project"), ("old_workspace", "Workspace")]
)
def test_a_name_that_moved_after_the_tag_warns_and_forwards(
    old: str, new: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(OLD_NAMES, old, OldName(new, "2.3.0"))

    with pytest.warns(FutureWarning, match=rf"hydromodpy\.{old} is now hydromodpy\.{new}.*2\.3\.0"):
        assert getattr(hmp, old) is getattr(hmp, new)
    assert old not in hmp.__all__


def test_every_old_name_forwards_to_a_name_of_the_facade() -> None:
    for old, entry in OLD_NAMES.items():
        assert entry.new in hmp.__all__, f"hmp.{old} forwards to hmp.{entry.new}, not public"
        assert old not in hmp.__all__, f"hmp.{old} is public and still listed as old"
