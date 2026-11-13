"""``hmp config figures`` lists what can be drawn and what a run holds of it."""

from __future__ import annotations

import json

from tests._helpers.cli_runner import CliRunner

ROWS = [
    {
        "name": "discharge",
        "kind": "variable",
        "frame": "series",
        "label": "Discharge",
        "unit": "m3 s-1",
        "detail": "",
        "status": "held",
    },
    {
        "name": "hydrograph",
        "kind": "preset",
        "frame": "series",
        "label": "",
        "unit": "",
        "detail": "holes: station",
        "status": "missing: recharge",
    },
]


def _listing(sim_ref=None, *, workspace=None, presets_of=None):
    return ROWS


def test_figures_of_a_run(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_listing", _listing)

    result = CliRunner().invoke(["config", "figures", "--run", "abc123"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split(maxsplit=3) == [
        "discharge",
        "variable",
        "series",
        "Discharge [m3 s-1]  (held)",
    ]
    assert lines[1].endswith("holes: station  (missing: recharge)")
    assert "1 variable(s), 1 preset(s), 0 special(s), 0 frame(s) for abc123" in result.stdout


def test_figures_kind_filter(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_listing", _listing)

    result = CliRunner().invoke(["config", "figures", "--kind", "preset"])

    assert "discharge" not in result.stdout
    assert result.stdout.strip().endswith("1 preset(s)")
    assert CliRunner().invoke(["config", "figures", "--kind", "spatial"]).exit_code == 2


def test_figures_unknown_run(monkeypatch) -> None:
    from hydromodpy.results.catalog.discovery import SimulationNotFoundError

    def unknown(sim_ref, *, workspace=None, presets_of=None):
        raise SimulationNotFoundError(f"Reference {sim_ref!r} not found.")

    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_listing", unknown)

    result = CliRunner().invoke(["config", "figures", "--run", "nope"])

    assert result.exit_code == 10
    assert "Reference 'nope' not found." in result.stderr


def test_figures_json() -> None:
    result = CliRunner().invoke(["config", "figures", "--format", "json"])

    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["schema"] == "hmp.config.figures.v3"
    assert {"discharge", "hydrograph", "map"} <= {row["name"] for row in payload["data"]}


def test_a_long_row_is_cut_in_the_text_and_whole_in_the_json(monkeypatch) -> None:
    long = {**ROWS[1], "detail": "d" * 90, "status": "missing: " + ", ".join(["term"] * 20)}
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_listing", lambda *a, **k: [long])

    text = CliRunner().invoke(["config", "figures"]).stdout.splitlines()[0]
    data = json.loads(CliRunner().invoke(["config", "figures", "--format", "json"]).stdout)

    assert len(text) <= 110 and "... (+" in text
    assert data["data"][0]["status"] == long["status"]
