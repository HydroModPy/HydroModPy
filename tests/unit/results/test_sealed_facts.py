"""The facts a sealed run states about itself."""

from __future__ import annotations

from hydromodpy.results.run.sealed_facts import overrides_text


def test_overrides_read_as_dotted_paths_and_values() -> None:
    assert overrides_text({"b.k": 2e-5, "a.n": 3}) == "a.n=3, b.k=2e-05"
    assert overrides_text({}) == ""
