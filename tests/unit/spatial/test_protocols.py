"""The geology data source is wired by the data layer, and read by spatial."""

from __future__ import annotations

import pytest

from hydromodpy.spatial import protocols


def test_reading_the_source_before_it_is_wired_names_the_fix(monkeypatch) -> None:
    monkeypatch.setattr(protocols, "_geology_data_source", None)

    with pytest.raises(RuntimeError, match="hydromodpy.bootstrap"):
        protocols.get_geology_data_source()

    source = object()
    protocols.register_geology_data_source(source)  # type: ignore[arg-type]
    assert protocols.get_geology_data_source() is source
