"""Tests for ``hmp data get``: both forms serve a request into a folder."""

from __future__ import annotations

import argparse
import importlib
import json
import sys

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.source.port import FetchRequest, FetchResult
from hydromodpy.data.variables.hydrometry.apis.hubeau import HubeauHydrometry

from ._hmp import run_main as _run


def _station(station_id: str) -> PointRecord:
    dates = pd.date_range("2019-12-01", periods=120, freq="D")
    return PointRecord(
        station_id=station_id,
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": np.arange(120, dtype=float)}),
        date_start=dates[0].to_pydatetime(),
        date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id=station_id, x=-1.7, y=48.1, crs="EPSG:4326"),
    )


@pytest.fixture
def hubeau_stub(monkeypatch) -> list[dict]:
    """Replace the Hub'Eau hydrometry fetch; record what each call asked."""
    calls: list[dict] = []

    def fake_hubeau(self, request: FetchRequest) -> FetchResult:
        calls.append(
            {
                "bbox": request.extent.bbox if request.extent is not None else None,
                "station_ids": list(request.station_ids),
            }
        )
        return FetchResult(
            source_id="hubeau",
            kind="points",
            variables=self.variables,
            extent=request.extent,
            period=request.period,
            points=(_station("J0001"),),
        )

    monkeypatch.setattr(HubeauHydrometry, "fetch", fake_hubeau)
    return calls


def test_a_request_document_is_served(monkeypatch, tmp_path, hubeau_stub) -> None:
    document = tmp_path / "ask.json"
    document.write_text(
        json.dumps(
            {
                "data": {"hydrometry": {"sources": [{"source": "hubeau"}]}},
                "extent": {"station_ids": ["J0001"]},
                "period": {"start": "2020-01-01", "end": "2020-01-31"},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    code = _run(monkeypatch, ["hmp", "data", "get", str(document), "--to", str(out)])
    assert code == 0
    report = json.loads((out / "request.json").read_text(encoding="utf-8"))
    assert report["files"][0]["path"] is not None


def test_a_negative_bbox_parses_with_the_equals_form(monkeypatch, tmp_path, hubeau_stub) -> None:
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "get",
            "hydrometry",
            "--bbox=-1.8,48.0,-1.6,48.2",
            "--crs",
            "EPSG:4326",
            "--start",
            "2020-01-01",
            "--end",
            "2020-01-31",
            "--to",
            str(tmp_path / "out"),
        ],
    )
    assert code == 0
    assert hubeau_stub, "the source was asked"


def test_a_failed_variable_exits_with_the_validation_code(monkeypatch, tmp_path, capsys) -> None:
    def broken(self, request: FetchRequest) -> FetchResult:
        raise RuntimeError("upstream down")

    monkeypatch.setattr(HubeauHydrometry, "fetch", broken)
    code = _run(
        monkeypatch,
        [
            "hmp",
            "data",
            "get",
            "hydrometry",
            "--stations",
            "J0001",
            "--start",
            "2020-01-01",
            "--end",
            "2020-01-31",
            "--to",
            str(tmp_path / "out"),
        ],
    )
    assert code == 16
    assert "FAILED" in capsys.readouterr().err
    assert (tmp_path / "out" / "request.json").is_file()


def test_an_unknown_variable_is_a_config_error(monkeypatch, tmp_path, capsys) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "data", "get", "not_a_var", "--stations", "X", "--to", str(tmp_path)],
    )
    assert code == 14
    assert "Unknown variable" in capsys.readouterr().err


@pytest.mark.parametrize(
    "selector",
    [[], ["--bbox", "0,0,1,1"]],
    ids=["no-extent", "bbox-without-crs"],
)
def test_an_incomplete_extent_is_a_config_error(monkeypatch, tmp_path, capsys, selector) -> None:
    out = tmp_path / "out"
    code = _run(monkeypatch, ["hmp", "data", "get", "dem", *selector, "--to", str(out)])
    assert code == 14
    assert not out.exists(), "a refused request writes nothing"


def test_a_mask_that_is_not_there_is_not_found(monkeypatch, tmp_path) -> None:
    out = tmp_path / "out"
    code = _run(
        monkeypatch,
        ["hmp", "data", "get", "dem", "--mask", str(tmp_path / "absent.gpkg"), "--to", str(out)],
    )
    assert code == 10
    assert not out.exists()


@pytest.mark.parametrize("bbox", ["not-floats", "0,1,2"])
def test_a_malformed_bbox_is_a_usage_error(monkeypatch, tmp_path, bbox) -> None:
    code = _run(
        monkeypatch,
        ["hmp", "data", "get", "dem", "--bbox", bbox, "--to", str(tmp_path)],
    )
    assert code == 2


def test_parse_bbox_rejects_non_floats() -> None:
    from hydromodpy.cli.commands.data.get import _parse_bbox

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_bbox("a,b,c,d")
