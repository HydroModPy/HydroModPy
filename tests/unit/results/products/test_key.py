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


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"kind": "soil"}, id="kind"),
        pytest.param({"codec": "hydromodpy.mesh_cache.v2"}, id="codec"),
        pytest.param({"inputs": {"request": "b" * 64}}, id="input-digest"),
        pytest.param({"processing": {"request": "different"}}, id="processing"),
        pytest.param({"engine": {"engine_id": "voronoi", "engine_version": "2"}}, id="engine"),
        pytest.param({"package": "model"}, id="code-layer"),
    ],
)
def test_each_component_changes_the_key(change: dict[str, object]) -> None:
    assert _key(**change) != _key()


def test_the_order_of_a_mapping_does_not_change_the_key() -> None:
    assert _key(inputs={"a": "x", "b": "y"}) == _key(inputs={"b": "y", "a": "x"})


def test_array_digest_changes_with_dtype() -> None:
    assert array_digest(np.array([1.0], dtype=np.float32)) != array_digest(
        np.array([1.0], dtype=np.float64)
    )


def test_array_digest_changes_with_shape() -> None:
    assert array_digest(np.array([[1.0, 2.0]])) != array_digest(np.array([1.0, 2.0]))


def test_array_digest_changes_with_a_value() -> None:
    assert array_digest(np.array([1.0])) != array_digest(np.array([2.0]))


def test_array_digest_ignores_the_sign_of_a_nan() -> None:
    assert array_digest(np.array([np.nan])) == array_digest(np.array([-np.nan]))


def test_array_digest_ignores_the_sign_of_a_zero() -> None:
    assert array_digest(np.array([-0.0])) == array_digest(np.array([0.0]))
