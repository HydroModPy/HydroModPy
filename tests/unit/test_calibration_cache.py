"""Unit tests for hydromodpy.calibration.cache (params_hash + cache)."""

from __future__ import annotations

from hydromodpy.calibration.cache import (
    CachedEvaluation,
    ParamsHashCache,
    canonical_json,
    params_hash,
)


class TestCanonicalJSON:
    def test_sorted_keys(self):
        a = canonical_json({"b": 2.0, "a": 1.0})
        b = canonical_json({"a": 1.0, "b": 2.0})
        assert a == b

    def test_noise_below_precision_collapses(self):
        # Differ at the 15th significant digit; default precision=12.
        a = canonical_json({"x": 1.234567890123})
        b = canonical_json({"x": 1.2345678901234})
        assert a == b

    def test_above_precision_distinguishes(self):
        a = canonical_json({"x": 1.23e-6})
        b = canonical_json({"x": 1.24e-6})
        assert a != b


class TestParamsHash:
    def test_stable_across_orderings(self):
        h1 = params_hash({"a": 0.1, "b": 0.2})
        h2 = params_hash({"b": 0.2, "a": 0.1})
        assert h1 == h2

    def test_hex_string_length(self):
        h = params_hash({"a": 1.0})
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_values_different_hash(self):
        h1 = params_hash({"a": 1.0})
        h2 = params_hash({"a": 2.0})
        assert h1 != h2


class TestParamsHashCache:
    def test_empty_cache(self):
        cache = ParamsHashCache()
        assert len(cache) == 0
        assert cache.get("abc") is None
        assert "abc" not in cache

    def test_put_and_get(self):
        cache = ParamsHashCache()
        cache.put("abc", "sim-1", objective_value=0.12)
        hit = cache.get("abc")
        assert hit == CachedEvaluation(sim_id="sim-1", objective_value=0.12)
        assert "abc" in cache
        assert len(cache) == 1

    def test_put_overwrites(self):
        cache = ParamsHashCache()
        cache.put("abc", "sim-1", objective_value=0.12)
        cache.put("abc", "sim-2", objective_value=0.03)
        hit = cache.get("abc")
        assert hit is not None
        assert hit.sim_id == "sim-2"
        assert hit.objective_value == 0.03

    def test_cache_hit_returns_evaluation(self):
        """Two evaluations with identical params yield the same cached objective."""
        cache = ParamsHashCache()
        values = {"K": 1.5e-4, "Sy": 0.1}
        h = params_hash(values)
        cache.put(h, "sim-42", objective_value=1.5, components={"rmse": 1.5})

        # Second call with equivalent dict must hit the cache.
        h2 = params_hash({"Sy": 0.1, "K": 1.5e-4})
        hit = cache.get(h2)
        assert hit is not None
        assert hit.sim_id == "sim-42"
        assert hit.objective_value == 1.5
        assert hit.components == {"rmse": 1.5}
