"""The key of a product: every component moves it, and the array digest."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.results.products import key as key_module
from hydromodpy.results.products.key import array_digest, product_key


@pytest.fixture(autouse=True)
def _fake_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the test fast: the fingerprint itself is tested in test_code_fingerprint."""
    monkeypatch.setattr(
        key_module,
        "code_fingerprint",
        lambda layers: {layer: f"digest-{layer}" for layer in layers},
    )


def _key(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "kind": "mesh",
        "codec": "hydromodpy.mesh_cache.v1",
        "package": "mesh",
        "inputs": {"request": "a" * 64},
        "processing": {"request": "canonical"},
        "engine": {"engine_id": "voronoi", "engine_version": "1"},
    }
    kwargs.update(overrides)
    return product_key(**kwargs)


def test_array_digest_ignores_the_sign_of_a_nan() -> None:
    assert array_digest(np.array([np.nan])) == array_digest(np.array([-np.nan]))


def test_array_digest_ignores_the_sign_of_a_zero() -> None:
    assert array_digest(np.array([-0.0])) == array_digest(np.array([0.0]))
