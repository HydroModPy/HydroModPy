"""Workspace ``data/<var>/{raw,processed}/`` layout helpers."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.data.layout import (
    DATA_DIRNAME,
    PROCESSED_DIRNAME,
    RAW_DIRNAME,
    ensure_data_layout,
    processed_dir,
    raw_dir,
    variable_dir,
)


def test_constants_are_canonical():
    assert DATA_DIRNAME == "data"
    assert RAW_DIRNAME == "raw"
    assert PROCESSED_DIRNAME == "processed"


def test_variable_dir_layout(tmp_path: Path):
    ws = tmp_path / "ws"
    assert variable_dir(ws, "dem") == ws.resolve() / "data" / "dem"
    assert raw_dir(ws, "dem") == ws.resolve() / "data" / "dem" / "raw"
    assert processed_dir(ws, "dem") == ws.resolve() / "data" / "dem" / "processed"


def test_ensure_data_layout_creates_both(tmp_path: Path):
    ws = tmp_path / "ws"
    raw, processed = ensure_data_layout(ws, "climate")
    assert raw.is_dir()
    assert processed.is_dir()
    assert raw.parent == processed.parent
    assert raw.name == "raw"
    assert processed.name == "processed"


def test_ensure_data_layout_idempotent(tmp_path: Path):
    ws = tmp_path / "ws"
    first_raw, first_processed = ensure_data_layout(ws, "geology")
    second_raw, second_processed = ensure_data_layout(ws, "geology")
    assert first_raw == second_raw
    assert first_processed == second_processed
