"""The W3C PROV-O vocabulary of the export is pinned to the canonical documentation host."""

from __future__ import annotations

import pytest

from hydromodpy.results.export.prov import HYDROMODPY_NAMESPACE

pytestmark = pytest.mark.fast


def test_namespace_is_the_canonical_docs_host():
    assert HYDROMODPY_NAMESPACE == "https://docs.hydromodpy.fr/schema#"
