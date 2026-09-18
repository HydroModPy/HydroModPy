"""Every capability this build serves has its declared egress checked by a run.

``reaches_network`` defaults to ``()``. A capability added without a gate would
therefore publish ``"network": []`` in its process description and have nobody
compare it to what a socket did -- which is the exact defect the member was
introduced to remove, reappearing one level up.

This file is the pin, and it lives here rather than beside one capability's
tests because the claim is about the **registry**: it used to sit in the
``terrain-delineate`` file, where the second capability's gate could not be
named. What it holds is that each served capability is paired with a test module
that runs it and reads the names it resolved, and that the module is on disk and
still carries that test.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.cli._workers.process import capability_ids

REPO_ROOT = Path(__file__).resolve().parents[3]

EGRESS_GATE_NAME = "test_the_only_hosts_it_contacts_are_the_ones_it_declares"
"""The one test name every capability's egress gate is spelled with."""

EGRESS_GATES: dict[str, str] = {
    "data-fetch": "tests/integration/data/test_data_fetch_seals_a_job.py",
    "domain-build": "tests/integration/domain/test_domain_build_seals_a_job.py",
    "terrain-delineate": ("tests/integration/site_selection/test_terrain_delineate_seals_a_job.py"),
}
"""Which module runs each capability and reads back what it reached.

A path and not a boolean: a pinned list of ids would say that a gate exists
without anything being able to find it, and the two gates are not
interchangeable -- one asserts the capability resolves nothing at all, the other
that everything it resolved is declared.
"""


def test_every_capability_this_build_serves_is_paired_with_an_egress_gate() -> None:
    assert set(capability_ids()) == set(EGRESS_GATES), (
        "a capability was added or removed without its egress gate; "
        f"gated: {sorted(EGRESS_GATES)}, served: {sorted(capability_ids())}"
    )


def test_every_named_gate_is_on_disk_and_still_carries_its_test() -> None:
    """A pin pointing at a file that moved protects nothing, and hides the next."""
    for capability_id, relative in sorted(EGRESS_GATES.items()):
        module = REPO_ROOT / relative
        assert module.is_file(), f"{capability_id}: {relative} is not on disk"
        text = module.read_text(encoding="utf-8")
        assert f"def {EGRESS_GATE_NAME}(" in text, (
            f"{capability_id}: {relative} carries no {EGRESS_GATE_NAME}"
        )
