"""``hmp config figures`` lists the registered figures and which ones a run can draw."""

from __future__ import annotations

from tests._helpers.cli_runner import CliRunner


def _availability(sim_ref: str, *, workspace: object = None):
    from hydromodpy.display.figure import FigureSpec

    return [
        (FigureSpec(name="piezometric_map", title="p", kind="spatial"), None),
        (
            FigureSpec(name="particle_tracks", title="t", kind="particles"),
            "missing result field(s): particles",
        ),
    ]


def test_figures_of_a_run(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", _availability)

    result = CliRunner().invoke(["config", "figures", "--run", "abc123"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["piezometric_map", "spatial", "run", "available"]
    assert lines[1].split()[:3] == ["particle_tracks", "particles", "run"]
    assert lines[1].endswith("missing result field(s): particles")
    assert "2 figure(s), 1 available for abc123" in result.stdout


def test_figures_kind_filter(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", _availability)

    result = CliRunner().invoke(["config", "figures", "--run", "abc123", "--kind", "particles"])

    assert "piezometric_map" not in result.stdout
    assert "1 figure(s), 0 available for abc123" in result.stdout


def test_figures_unknown_run(monkeypatch) -> None:
    from hydromodpy.results.catalog.discovery import SimulationNotFoundError

    def unknown(sim_ref: str, *, workspace: object = None):
        raise SimulationNotFoundError(f"Reference {sim_ref!r} not found.")

    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", unknown)

    result = CliRunner().invoke(["config", "figures", "--run", "nope"])

    assert result.exit_code == 10
    assert "Reference 'nope' not found." in result.stderr


def test_figures_registry() -> None:
    result = CliRunner().invoke(["config", "figures", "--format", "json"])

    assert result.exit_code == 0
    assert '"schema": "hmp.config.figures.v2"' in result.stdout
