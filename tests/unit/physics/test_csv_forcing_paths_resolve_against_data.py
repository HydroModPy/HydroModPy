"""A CSV forcing of a lake, an outlet or an SFR reach is found like a well forcing."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.physics.flow.flow_toml_loader import resolve_well_forcing_paths

pytestmark = pytest.mark.unit


def _csv(name: str) -> dict[str, object]:
    return {"kind": "csv", "path_file": name, "value_column": "v"}


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "project"
    data = tmp_path / "workspace" / "data"
    (data / "lakes").mkdir(parents=True)
    base.mkdir()
    for name in ("rain.csv", "release.csv", "inflow.csv", "seg.csv"):
        (data / "lakes" / name).write_text("date,v\n2020-01-01,1\n", encoding="utf-8")
    return base, data


def test_lake_outlet_and_sfr_csv_resolve_against_data(layout) -> None:
    base, data = layout
    raw = {
        "lakes": {
            "lac0": {
                "rainfall": _csv("rain.csv"),
                "outlet": {"kind": "specified", "forcing": _csv("release.csv")},
                "inflow": {
                    "kind": "piecewise",
                    "segments": [{"start": "2020-01-01", "forcing": _csv("seg.csv")}],
                },
            }
        },
        "sfr": {"headwater_inflow": _csv("inflow.csv")},
    }
    out = resolve_well_forcing_paths(raw, base_dir=base, workspace_data_dir=data)
    lac = out["lakes"]["lac0"]
    assert Path(lac["rainfall"]["path_file"]) == (data / "lakes" / "rain.csv").resolve()
    assert Path(lac["outlet"]["forcing"]["path_file"]) == (data / "lakes" / "release.csv").resolve()
    seg = lac["inflow"]["segments"][0]["forcing"]
    assert Path(seg["path_file"]) == (data / "lakes" / "seg.csv").resolve()
    # SFR has no data/sfr folder here: the bare name falls back to data/ then stays beside the TOML.
    assert Path(out["sfr"]["headwater_inflow"]["path_file"]).name == "inflow.csv"


def test_a_missing_lake_csv_keeps_a_predictable_path(layout) -> None:
    base, data = layout
    raw = {"lakes": {"lac0": {"rainfall": _csv("absent.csv")}}}
    out = resolve_well_forcing_paths(raw, base_dir=base, workspace_data_dir=data)
    assert Path(out["lakes"]["lac0"]["rainfall"]["path_file"]) == (base / "absent.csv").resolve()
