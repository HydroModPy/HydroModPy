"""Unit tests for hydromodpy.calibration.optim.cache (params_hash + cache)."""

from __future__ import annotations

from hydromodpy.calibration.optim.cache import (
    CachedEvaluation,
    ParamsHashCache,
    canonical_json,
    context_fingerprints,
    differing_members,
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

    def test_context_changes_hash(self):
        h1 = params_hash({"a": 1.0}, context={"calibration": "kge"})
        h2 = params_hash({"a": 1.0}, context={"calibration": "nse"})
        assert h1 != h2
        assert h1.startswith("v2:")

    def test_context_order_is_stable(self):
        h1 = params_hash({"a": 1.0}, context={"b": 2.0, "a": [3.0, 4.0]})
        h2 = params_hash({"a": 1.0}, context={"a": [3.0, 4.0], "b": 2.0})
        assert h1 == h2


class TestParamsHashCache:
    def test_empty_cache(self):
        cache = ParamsHashCache()
        assert len(cache) == 0
        assert cache.get("abc") is None
        assert "abc" not in cache

    def test_put_and_get(self):
        cache = ParamsHashCache()
        cache.put("abc", cost=0.12)
        hit = cache.get("abc")
        assert hit == CachedEvaluation(cost=0.12)
        assert "abc" in cache
        assert len(cache) == 1

    def test_put_overwrites(self):
        cache = ParamsHashCache()
        cache.put("abc", cost=0.12)
        cache.put("abc", cost=0.03)
        hit = cache.get("abc")
        assert hit is not None
        assert hit.cost == 0.03

    def test_cache_hit_returns_evaluation(self):
        """Two evaluations with identical params yield the same cached cost."""
        cache = ParamsHashCache()
        values = {"K": 1.5e-4, "Sy": 0.1}
        h = params_hash(values)
        cache.put(h, cost=1.5, components={"rmse": 1.5})

        # Second call with equivalent dict must hit the cache.
        h2 = params_hash({"Sy": 0.1, "K": 1.5e-4})
        hit = cache.get(h2)
        assert hit is not None
        assert hit.cost == 1.5
        assert hit.components == {"rmse": 1.5}
        assert not hasattr(hit, "sim_id"), "a hit never names the run of another trial"


class TestContextFingerprints:
    def test_a_member_moves_its_own_fingerprint_only(self):
        before = context_fingerprints(
            {"schema": "v4", "model": {"K": 1.0}, "calibration": {"seed": 1}}
        )
        after = context_fingerprints(
            {"schema": "v4", "model": {"K": 2.0}, "calibration": {"seed": 1}}
        )

        assert differing_members(before, after) == ["model"]
        assert before["schema"] == "v4", "the schema is kept in clear"

    def test_a_member_one_side_lacks_differs(self):
        assert differing_members({"model": "a"}, {"model": "a", "mesh": "b"}) == ["mesh"]
