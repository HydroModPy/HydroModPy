"""``precision`` bounds the parameter, ``cost_margin`` bounds the cost.

``tolerance`` named both: how finely a search pins a parameter, and how far a
cost may sit from the best before a trial stops counting as tied with it. The
first is a ``precision`` on the parameter. The second is a ``cost_margin``
that carries its unit, ``"5%"`` of the best cost or ``"75 m"`` of network
distance, so the ``mode`` key that said how to read a bare number is gone. A
key renamed is refused with the new name, the doctor rewrites the file, and a
sealed run config still reads.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibPhaseDecl,
    CalibPhaseUncertaintyDecl,
    CalibrationConfig,
    CalibrationProtocolDecl,
    CalibUncertaintyDecl,
)
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import fix_config_file, migrate_sealed_config_doc
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import (
    PROJECT,
    _project,
)

PROTOCOL = "matching_hydrographic_network"
K = {"K": {"bounds": [1e-7, 1e-3]}}


def _section(**fields: Any) -> CalibrationConfig:
    return CalibrationConfig.model_validate({"parameters": K, **fields})


def _phase(**fields: Any) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["K"], **fields})


# -- precision ---------------------------------------------------------------


def test_the_section_a_phase_and_the_protocol_name_precision() -> None:
    assert _section(precision=0.01).precision == 0.01
    assert _phase(precision=0.05).precision == 0.05
    declared = CalibrationProtocolDecl.model_validate(
        {"name": PROTOCOL, "steady_precision": 0.01, "transient_precision": 0.05}
    )
    assert (declared.steady_precision, declared.transient_precision) == (0.01, 0.05)


@pytest.mark.parametrize(
    ("build", "new"),
    [
        (lambda: _section(tolerance=0.01), "'precision'"),
        (lambda: _phase(tolerance=0.01), "'precision'"),
        (
            lambda: CalibrationProtocolDecl.model_validate(
                {"name": PROTOCOL, "steady_tolerance": 0.01}
            ),
            "'steady_precision'",
        ),
        (
            lambda: CalibrationProtocolDecl.model_validate(
                {"name": PROTOCOL, "transient_tolerance": 0.01}
            ),
            "'transient_precision'",
        ),
    ],
)
def test_tolerance_is_refused_with_the_name_that_replaces_it(build: Any, new: str) -> None:
    with pytest.raises(ValidationError, match="is not accepted any more: renamed") as refused:
        build()

    assert new in str(refused.value)
    assert "hmp doctor --fix-config" in str(refused.value)


# -- cost_margin: what a file may write --------------------------------------


@pytest.mark.parametrize("text", ["5%", " 5 % ", "0.5%", "75 m", "25m", "0.1 km", "1e2 m"])
def test_a_margin_is_a_share_of_the_best_cost_or_a_length(text: str) -> None:
    decl = CalibUncertaintyDecl.model_validate({"cost_margin": text})

    assert decl.cost_margin is not None
    assert CalibPhaseUncertaintyDecl.model_validate({"cost_margin": text}).cost_margin


def test_the_margin_is_read_into_its_kind_and_its_value() -> None:
    from hydromodpy.core.cost_margin import parse_cost_margin

    share = parse_cost_margin("5%")
    assert (share.kind, share.value) == ("relative", pytest.approx(0.05))
    length = parse_cost_margin("0.1 km")
    assert (length.kind, length.value) == ("absolute", pytest.approx(100.0))


@pytest.mark.parametrize("value", [0.05, 25, 25.0, "0.05", "25", True])
def test_a_bare_number_is_refused_because_it_has_no_unit(value: object) -> None:
    with pytest.raises(ValidationError, match=r"write '5%' or '25 m'"):
        CalibUncertaintyDecl.model_validate({"cost_margin": value})
    with pytest.raises(ValidationError, match=r"write '5%' or '25 m'"):
        CalibPhaseUncertaintyDecl.model_validate({"cost_margin": value})


@pytest.mark.parametrize("text", ["0%", "-5%", "0 m", "-3 m", "abc", "5 s", "% 5", "", "nan %"])
def test_a_margin_that_is_not_a_positive_share_or_length_is_refused(text: str) -> None:
    with pytest.raises(ValidationError, match="cost_margin"):
        CalibUncertaintyDecl.model_validate({"cost_margin": text})


def test_tolerance_and_mode_of_the_uncertainty_are_refused_naming_cost_margin() -> None:
    for model in (CalibUncertaintyDecl, CalibPhaseUncertaintyDecl):
        for key, value in (("tolerance", 0.05), ("mode", "relative")):
            with pytest.raises(ValidationError, match="renamed to 'cost_margin'") as refused:
                model.model_validate({key: value})
            assert "hmp doctor --fix-config" in str(refused.value)


def test_a_phase_keeps_the_error_of_a_bad_section_margin_out_of_its_name() -> None:
    with pytest.raises(ValidationError, match="cost_margin"):
        _section(uncertainty={"cost_margin": 0.05})


# -- cost_margin: what a search scores ---------------------------------------


def test_a_length_margin_is_refused_on_a_search_that_is_not_a_network_distance() -> None:
    with pytest.raises(ValidationError, match="network distance"):
        _section(uncertainty={"cost_margin": "75 m"})
    with pytest.raises(ValidationError, match="network distance"):
        _section(
            phases=[{"name": "sy", "parameters": ["K"], "uncertainty": {"cost_margin": "75 m"}}]
        )

    assert _section(objective="distance_gap", uncertainty={"cost_margin": "75 m"})
    assert _section(uncertainty={"cost_margin": "5%"})


def test_the_width_a_search_reads_follows_the_margin_it_was_given() -> None:
    cfg = _section(uncertainty={"cost_margin": "5%"})
    width = cfg.interval_width_for()
    assert (width.margin, width.kind, width.source) == (pytest.approx(0.05), "relative", "section")

    cfg = _section(objective="distance_gap", uncertainty={"cost_margin": "75 m"})
    width = cfg.interval_width_for()
    assert (width.margin, width.kind, width.source) == (pytest.approx(75.0), "absolute", "section")
    assert width.on_distances is True

    width = _section().interval_width_for()
    assert (width.margin, width.kind, width.source) == (pytest.approx(0.05), "relative", "default")
    width = _section(objective="distance_gap").interval_width_for()
    assert (width.margin, width.kind, width.rule) == (None, "absolute", "one mesh cell")
    assert set(width.to_dict()) == {"margin", "kind", "source", "on_distances", "rule"}


def test_a_length_margin_of_the_section_is_read_by_the_phases_that_score_distances() -> None:
    cfg = _section(
        outputs={
            "net": {"support": "network", "stream_geometry_path": "s.gpkg"},
            "q": {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observed_values": [1.0, 2.0, 3.0],
            },
        },
        objective_blocks=[
            {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
            {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["q"]},
        ],
        phases=[
            {"name": "k", "parameters": ["K"], "objective_blocks": ["network"]},
            {"name": "sy", "parameters": ["K"], "objective_blocks": ["hydrograph"]},
        ],
        uncertainty={"cost_margin": "150 m"},
    )
    k_phase, sy_phase = cfg.phases

    assert cfg.interval_width_for(k_phase).margin == pytest.approx(150.0)
    assert cfg.interval_width_for(sy_phase).source == "default"
    assert cfg.uncertainty_for(sy_phase).cost_margin is None


# -- the doctor --------------------------------------------------------------

DISTANCES = '[calibration]\nobjective = "distance_gap"\n[calibration.uncertainty]\n{uncertainty}\n'
EFFICIENCY = "[calibration]\n[calibration.uncertainty]\n{uncertainty}\n"


@pytest.mark.parametrize(
    ("template", "uncertainty", "expected"),
    [
        (EFFICIENCY, "tolerance = 0.05", "5%"),
        (EFFICIENCY, 'tolerance = 0.1\nmode = "relative"', "10%"),
        (EFFICIENCY, "tolerance = 0.07", "7%"),
        (DISTANCES, "tolerance = 75.0", "75 m"),
        (DISTANCES, 'mode = "absolute"\ntolerance = 25', "25 m"),
        (DISTANCES, 'mode = "relative"\ntolerance = 0.2', "20%"),
    ],
)
def test_the_doctor_writes_the_unit_the_old_mode_implied(
    tmp_path: Path, template: str, uncertainty: str, expected: str
) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(template.format(uncertainty=uncertainty), encoding="utf-8")

    changes = fix_config_file(path)

    section = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["uncertainty"]
    assert section == {"cost_margin": expected}
    assert any("cost_margin" in change for change in changes)


def test_the_doctor_leaves_an_absolute_width_that_has_no_unit_to_write(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        EFFICIENCY.format(uncertainty='mode = "absolute"\ntolerance = 0.3'), encoding="utf-8"
    )

    changes = fix_config_file(path)

    section = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["uncertainty"]
    assert section == {"mode": "absolute", "tolerance": 0.3}
    assert any("left" in change and "unit" in change for change in changes)


def test_the_doctor_leaves_a_width_it_cannot_read_the_search_of(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[calibration]\nprotocol = "matching_hydrographic_network"\n'
        "[calibration.uncertainty]\ntolerance = 0.05\n",
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert "tolerance = 0.05" in path.read_text(encoding="utf-8")
    assert any("protocol" in change and "left" in change for change in changes)


def test_the_doctor_reads_what_each_phase_scores_and_the_mode_it_inherits(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration.uncertainty]\n"
        'mode = "absolute"\n'
        "[[calibration.objective_blocks]]\n"
        'name = "network"\nmetric = "distance_gap"\n'
        "[[calibration.objective_blocks]]\n"
        'name = "hydrograph"\nmetric = "nse_log"\n'
        "[[calibration.phases]]\n"
        'name = "k"\nobjective_blocks = ["network"]\n'
        "uncertainty = { tolerance = 225.0 }\n"
        "[[calibration.phases]]\n"
        'name = "sy"\nobjective_blocks = { hydrograph = 99, network = 1 }\n'
        'uncertainty = { mode = "relative", tolerance = 0.1 }\n',
        encoding="utf-8",
    )

    fix_config_file(path)

    document = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]
    assert [phase["uncertainty"] for phase in document["phases"]] == [
        {"cost_margin": "225 m"},
        {"cost_margin": "10%"},
    ]
    assert "tolerance" not in path.read_text(encoding="utf-8")


def test_the_doctor_renames_the_precision_in_the_section_a_phase_and_the_protocol(
    tmp_path: Path,
) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration]\ntolerance = 0.01  # one per cent\n"
        "[[calibration.phases]]\nname = 'a'\ntolerance = 0.05\n"
        "[calibration.protocol]\nname = 'matching_hydrographic_network'\n"
        "steady_tolerance = 0.01\ntransient_tolerance = 0.05\n",
        encoding="utf-8",
    )

    fix_config_file(path)

    text = path.read_text(encoding="utf-8")
    document = tomllib.loads(text)["calibration"]
    assert document["precision"] == 0.01
    assert document["phases"][0]["precision"] == 0.05
    assert (
        document["protocol"]["steady_precision"],
        document["protocol"]["transient_precision"],
    ) == (
        0.01,
        0.05,
    )
    assert "# one per cent" in text
    assert "tolerance" not in text


# -- a sealed run ------------------------------------------------------------


def test_a_sealed_document_reads_the_old_precision_and_width_keys() -> None:
    doc = {
        "calibration": {
            "tolerance": 0.02,
            "uncertainty": {"tolerance": 0.05},
            "objective_blocks": [
                {"name": "network", "metric": "distance_gap"},
                {"name": "hydrograph", "metric": "nse_log"},
            ],
            "phases": [
                {
                    "name": "k",
                    "tolerance": 0.01,
                    "objective_blocks": ["network"],
                    "uncertainty": {"tolerance": 80.0},
                },
                {
                    "name": "sy",
                    "objective_blocks": ["hydrograph"],
                    "uncertainty": {"mode": "absolute", "tolerance": 0.4},
                },
            ],
            "protocol": {"steady_tolerance": 0.01, "transient_tolerance": 0.05},
        }
    }

    migrate_sealed_config_doc(doc)

    section = doc["calibration"]
    assert section["precision"] == 0.02
    assert section["uncertainty"] == {"cost_margin": "5%"}
    k_phase, sy_phase = section["phases"]
    assert (k_phase["precision"], k_phase["uncertainty"]) == (0.01, {"cost_margin": "80 m"})
    # An absolute width on a search that is no distance has no unit: the run's
    # interval is read at the default, its calibrated value is untouched.
    assert sy_phase["uncertainty"] == {}
    assert section["protocol"] == {"steady_precision": 0.01, "transient_precision": 0.05}


def test_a_frozen_protocol_run_with_the_old_names_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(
        PROJECT.replace(
            f'name = "{PROTOCOL}"',
            f'name = "{PROTOCOL}"\nsteady_precision = 0.02\ntransient_precision = 0.05'
            '\n\n[calibration.uncertainty]\ncost_margin = "5%"',
        ),
        encoding="utf-8",
    )
    cfg = HydroModPyConfig.from_toml(toml)
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = re.sub(r"^precision = ", "tolerance = ", frozen, flags=re.MULTILINE)
    old = re.sub(r"\b(steady|transient)_precision\b", r"\1_tolerance", old)
    old = old.replace('cost_margin = "5%"', 'tolerance = 0.05\nmode = "relative"')
    assert old != frozen
    assert "tolerance" in old and "cost_margin" not in old
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")

    replayed = HydroModPyConfig.from_toml(sealed)

    expected = [p.model_dump(mode="json") for p in cfg.calibration.phases]
    assert [p.model_dump(mode="json") for p in replayed.calibration.phases] == expected
    assert replayed.calibration.uncertainty.cost_margin == "5%"
    assert [phase.precision for phase in replayed.calibration.phases] == [0.02, 0.05]
