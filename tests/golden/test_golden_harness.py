"""Smoke tests for the golden assertion helpers.

These tests do not exercise HydroModPy outputs. They prove the harness itself
behaves correctly so the T2 god-module split can build on it.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests._helpers.golden import (
    assert_html_dom_equal,
    assert_json_canonical_equal,
    assert_parquet_equal,
)

GOLDEN_ROOT = Path(__file__).resolve().parent


def _write_demo_parquet(target: Path) -> None:
    """Reproduce the byte layout used to seed the demo Parquet fixture."""
    table = pa.table({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target, compression="snappy")


@pytest.mark.golden
def test_parquet_byte_equal(tmp_path: Path) -> None:
    actual = tmp_path / "demo_minimal.parquet"
    _write_demo_parquet(actual)
    golden = GOLDEN_ROOT / "parquet" / "demo_minimal.parquet"
    assert_parquet_equal(actual, golden)


@pytest.mark.golden
def test_json_normalized_equal() -> None:
    actual = {"rows": [{"a": 1, "b": "x"}]}
    golden = GOLDEN_ROOT / "json" / "demo_select.json"
    assert_json_canonical_equal(actual, golden)


@pytest.mark.golden
def test_html_dom_equal(tmp_path: Path) -> None:
    try:
        import lxml  # noqa: F401
    except ImportError:
        pytest.skip("lxml not installed")
    actual = tmp_path / "demo_section.html"
    actual.write_text(
        '<html><body><div class="x">42</div></body></html>\n',
        encoding="utf-8",
    )
    golden = GOLDEN_ROOT / "html" / "demo_section.html"
    assert_html_dom_equal(actual, golden)
