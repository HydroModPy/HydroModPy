"""Golden-file assertion helpers (byte-equal + normalized).

These helpers underpin the golden-test infrastructure used by the T2 god-module
split. They cover the four output families produced by HydroModPy:

- Parquet tables: byte-equal SHA256 or pyarrow-tolerant comparison.
- DuckDB query results: canonical JSON serialization.
- HTML reports: lxml-normalized DOM comparison.
- Zarr field stores: recursive SHA256 over the directory contents.

Set ``HMP_REGENERATE_GOLDEN=1`` to overwrite the golden fixture with the actual
output and force the test to fail so the change is reviewed manually.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

REGEN_ENV = "HMP_REGENERATE_GOLDEN"


def _sha256_file(path: Path) -> str:
    """Return the SHA256 hex digest of a single file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(root: Path) -> str:
    """Return a SHA256 over the entire directory tree, deterministic by path."""
    digest = hashlib.sha256()
    for entry in sorted(root.rglob("*")):
        if entry.is_dir():
            continue
        rel = entry.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        with entry.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def regenerate_golden(actual_path: Path, golden_path: Path) -> bool:
    """Copy ``actual`` to ``golden`` when ``HMP_REGENERATE_GOLDEN=1``.

    Returns True when the golden was regenerated. Callers should then fail
    the test so the diff is reviewed manually before the new golden is
    committed.
    """
    if os.environ.get(REGEN_ENV) != "1":
        return False
    actual_path = Path(actual_path)
    golden_path = Path(golden_path)
    golden_path.parent.mkdir(parents=True, exist_ok=True)
    if actual_path.is_dir():
        if golden_path.exists():
            shutil.rmtree(golden_path)
        shutil.copytree(actual_path, golden_path)
    else:
        shutil.copy2(actual_path, golden_path)
    return True


def assert_parquet_equal(actual_path: Path, golden_path: Path) -> None:
    """Compare two Parquet files byte-for-byte using SHA256."""
    actual_path = Path(actual_path)
    golden_path = Path(golden_path)
    if regenerate_golden(actual_path, golden_path):
        pytest.fail(f"Regenerated golden {golden_path}; review and re-run without {REGEN_ENV}.")
    assert golden_path.exists(), f"Missing golden: {golden_path}"
    actual_sha = _sha256_file(actual_path)
    golden_sha = _sha256_file(golden_path)
    assert actual_sha == golden_sha, (
        f"Parquet byte mismatch:\n  actual={actual_path} sha={actual_sha}\n"
        f"  golden={golden_path} sha={golden_sha}"
    )


def assert_parquet_data_equal(
    actual_path: Path,
    golden_path: Path,
    *,
    float_atol: float = 1e-10,
) -> None:
    """Compare two Parquet files via pyarrow, ignoring metadata jitter."""
    actual_path = Path(actual_path)
    golden_path = Path(golden_path)
    if regenerate_golden(actual_path, golden_path):
        pytest.fail(f"Regenerated golden {golden_path}; review and re-run without {REGEN_ENV}.")
    assert golden_path.exists(), f"Missing golden: {golden_path}"
    actual_table = pq.read_table(actual_path)
    golden_table = pq.read_table(golden_path)
    assert actual_table.column_names == golden_table.column_names, (
        f"Column mismatch: actual={actual_table.column_names} golden={golden_table.column_names}"
    )
    assert actual_table.num_rows == golden_table.num_rows, (
        f"Row count mismatch: actual={actual_table.num_rows} golden={golden_table.num_rows}"
    )
    for name in golden_table.column_names:
        actual_col = actual_table[name].to_pylist()
        golden_col = golden_table[name].to_pylist()
        for idx, (a, g) in enumerate(zip(actual_col, golden_col)):
            if isinstance(g, float) and isinstance(a, float):
                assert abs(a - g) <= float_atol, (
                    f"Column '{name}' row {idx} differs: actual={a} golden={g} atol={float_atol}"
                )
            else:
                assert a == g, f"Column '{name}' row {idx} differs: actual={a!r} golden={g!r}"


def _canonical_json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Non-serializable type for canonical JSON: {type(obj)!r}")


def _canonical_json_dumps(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        default=_canonical_json_default,
    )


def assert_duckdb_query_equal(conn, query: str, golden_json_path: Path) -> None:
    """Run a DuckDB query and compare its result with a canonical JSON golden."""
    golden_json_path = Path(golden_json_path)
    result = conn.execute(query)
    columns = [desc[0] for desc in result.description]
    rows = [dict(zip(columns, row)) for row in result.fetchall()]
    payload = {"columns": columns, "rows": rows}
    actual_text = _canonical_json_dumps(payload)
    if os.environ.get(REGEN_ENV) == "1":
        golden_json_path.parent.mkdir(parents=True, exist_ok=True)
        golden_json_path.write_text(actual_text + "\n", encoding="utf-8")
        pytest.fail(
            f"Regenerated golden {golden_json_path}; review and re-run without {REGEN_ENV}."
        )
    assert golden_json_path.exists(), f"Missing golden: {golden_json_path}"
    golden_text = golden_json_path.read_text(encoding="utf-8").rstrip("\n")
    assert actual_text == golden_text, (
        f"DuckDB query golden mismatch for {golden_json_path}:\n"
        f"--- actual\n{actual_text}\n--- golden\n{golden_text}"
    )


def assert_json_canonical_equal(actual: Any, golden_json_path: Path) -> None:
    """Compare a Python object (canonicalized) with a frozen JSON golden."""
    golden_json_path = Path(golden_json_path)
    actual_text = _canonical_json_dumps(actual)
    if os.environ.get(REGEN_ENV) == "1":
        golden_json_path.parent.mkdir(parents=True, exist_ok=True)
        golden_json_path.write_text(actual_text + "\n", encoding="utf-8")
        pytest.fail(
            f"Regenerated golden {golden_json_path}; review and re-run without {REGEN_ENV}."
        )
    assert golden_json_path.exists(), f"Missing golden: {golden_json_path}"
    golden_text = golden_json_path.read_text(encoding="utf-8").rstrip("\n")
    assert actual_text == golden_text, (
        f"JSON golden mismatch for {golden_json_path}:\n"
        f"--- actual\n{actual_text}\n--- golden\n{golden_text}"
    )


def _normalize_lxml_tree(root, ignore_attrs: tuple[str, ...]) -> str:
    """Serialize an lxml tree with sorted attributes and stripped jitter."""
    from lxml import etree

    for element in root.iter():
        for attr in list(element.attrib):
            if attr in ignore_attrs:
                del element.attrib[attr]
        sorted_attrs = sorted(element.attrib.items())
        element.attrib.clear()
        for key, value in sorted_attrs:
            element.set(key, value)
    return etree.tostring(root, pretty_print=True, encoding="unicode")


def assert_html_dom_equal(
    actual_html_path: Path,
    golden_html_path: Path,
    *,
    ignore_attrs: tuple[str, ...] = ("data-time", "id"),
) -> None:
    """Compare two HTML files at the DOM level, ignoring noisy attributes.

    Falls back to a plain textual comparison when ``lxml`` is missing so the
    helper stays usable in minimal environments. The caller is expected to
    ``pytest.skip`` when lxml is required for a strict comparison.
    """
    actual_html_path = Path(actual_html_path)
    golden_html_path = Path(golden_html_path)
    if regenerate_golden(actual_html_path, golden_html_path):
        pytest.fail(
            f"Regenerated golden {golden_html_path}; review and re-run without {REGEN_ENV}."
        )
    assert golden_html_path.exists(), f"Missing golden: {golden_html_path}"

    try:
        from lxml import etree, html
    except ImportError:
        actual_text = actual_html_path.read_text(encoding="utf-8")
        golden_text = golden_html_path.read_text(encoding="utf-8")
        assert actual_text == golden_text, (
            f"HTML mismatch (lxml not installed, textual diff only): "
            f"{actual_html_path} vs {golden_html_path}"
        )
        return

    parser = etree.HTMLParser(remove_blank_text=True)
    actual_tree = html.fromstring(actual_html_path.read_bytes(), parser=parser)
    golden_tree = html.fromstring(golden_html_path.read_bytes(), parser=parser)
    actual_norm = _normalize_lxml_tree(actual_tree, ignore_attrs)
    golden_norm = _normalize_lxml_tree(golden_tree, ignore_attrs)
    assert actual_norm == golden_norm, (
        f"HTML DOM mismatch for {golden_html_path}:\n"
        f"--- actual\n{actual_norm}\n--- golden\n{golden_norm}"
    )


def assert_zarr_array_equal(actual_path: Path, golden_path: Path) -> None:
    """Compare two Zarr stores via deterministic SHA256 over the directory."""
    actual_path = Path(actual_path)
    golden_path = Path(golden_path)
    if regenerate_golden(actual_path, golden_path):
        pytest.fail(f"Regenerated golden {golden_path}; review and re-run without {REGEN_ENV}.")
    assert golden_path.exists(), f"Missing golden: {golden_path}"
    assert actual_path.is_dir(), f"Zarr actual must be a directory: {actual_path}"
    assert golden_path.is_dir(), f"Zarr golden must be a directory: {golden_path}"
    actual_sha = _sha256_tree(actual_path)
    golden_sha = _sha256_tree(golden_path)
    assert actual_sha == golden_sha, (
        f"Zarr tree mismatch:\n  actual={actual_path} sha={actual_sha}\n"
        f"  golden={golden_path} sha={golden_sha}"
    )
