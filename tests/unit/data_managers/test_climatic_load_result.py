"""Tests for LoadResult container behavior (climatic data managers)."""

from __future__ import annotations

import pytest

from hydromodpy.data.contracts.load_result import LoadResult

from ._test_climatic_managers_builders import _make_field_record, _make_point_record


@pytest.mark.fast
class TestLoadResultEmpty:
    def test_len_zero(self):
        r = LoadResult()
        assert len(r) == 0

    def test_bool_false(self):
        r = LoadResult()
        assert not r

    def test_has_points_false(self):
        r = LoadResult()
        assert r.has_points is False

    def test_has_fields_false(self):
        r = LoadResult()
        assert r.has_fields is False

    def test_all_records_empty(self):
        r = LoadResult()
        assert r.all_records == []


@pytest.mark.fast
class TestLoadResultPointsOnly:
    def test_has_points_true(self):
        r = LoadResult(points=[_make_point_record()])
        assert r.has_points is True

    def test_has_fields_false(self):
        r = LoadResult(points=[_make_point_record()])
        assert r.has_fields is False

    def test_len(self):
        r = LoadResult(points=[_make_point_record(), _make_point_record("ST02")])
        assert len(r) == 2

    def test_bool_true(self):
        r = LoadResult(points=[_make_point_record()])
        assert r


@pytest.mark.fast
class TestLoadResultFieldsOnly:
    def test_has_points_false(self):
        r = LoadResult(fields=[_make_field_record()])
        assert r.has_points is False

    def test_has_fields_true(self):
        r = LoadResult(fields=[_make_field_record()])
        assert r.has_fields is True

    def test_len(self):
        r = LoadResult(fields=[_make_field_record()])
        assert len(r) == 1


@pytest.mark.fast
class TestLoadResultMixed:
    def test_both_true(self):
        r = LoadResult(
            points=[_make_point_record()],
            fields=[_make_field_record()],
        )
        assert r.has_points is True
        assert r.has_fields is True

    def test_len_sums_both(self):
        r = LoadResult(
            points=[_make_point_record(), _make_point_record("ST02")],
            fields=[_make_field_record()],
        )
        assert len(r) == 3

    def test_all_records_flat_list(self):
        pt = _make_point_record()
        fr = _make_field_record()
        r = LoadResult(points=[pt], fields=[fr])
        flat = r.all_records
        assert len(flat) == 2
        assert flat[0] is pt
        assert flat[1] is fr
