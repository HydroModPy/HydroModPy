"""``max_trials`` is the one number that bounds a search.

``max_iter`` counted evaluations, and ``maxfev``, ``max_evaluations`` and
gp_mapping's own ``max_iter`` counted them too, under four names that did not
agree about what an iteration was. A key renamed or removed is refused with the
name that replaces it, the doctor rewrites the file, and a sealed run config
still reads.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibPhaseDecl,
    CalibrationConfig,
    CalibrationProtocolDecl,
)
from hydromodpy.calibration.optim.method_config import (
    method_options_problem,
    validate_method_kwargs,
)
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import fix_config_file, migrate_sealed_config_doc
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests.unit.config.test_a_renamed_key_warns_and_a_sealed_one_reads import (
    PROJECT,
    _project,
)

PROTOCOL = "matching_hydrographic_network"


def _phase(**fields: object) -> CalibPhaseDecl:
    return CalibPhaseDecl.model_validate({"name": "sy", "parameters": ["Sy"], **fields})


def test_the_section_refuses_max_iter_and_names_max_trials() -> None:
    with pytest.raises(ValidationError, match=r"'max_iter' is not accepted any more: renamed") as e:
        CalibrationConfig.model_validate({"max_iter": 30})

    assert "'max_trials'" in str(e.value)
    assert "hmp doctor --fix-config" in str(e.value)
    assert CalibrationConfig.model_validate({"max_trials": 30}).max_trials == 30


def test_a_phase_refuses_max_iter_and_names_max_trials() -> None:
    with pytest.raises(ValidationError, match="renamed to 'max_trials'"):
        _phase(max_iter=30)

    assert _phase(max_trials=30).max_trials == 30
    assert _phase().max_trials is None
    assert _phase(max_trials="auto").max_trials == "auto"


def test_the_protocol_refuses_its_stage_budgets_and_names_the_new_ones() -> None:
    with pytest.raises(ValidationError, match="renamed to 'steady_max_trials'"):
        CalibrationProtocolDecl.model_validate({"name": PROTOCOL, "steady_max_iter": 20})
    with pytest.raises(ValidationError, match="renamed to 'transient_max_trials'"):
        CalibrationProtocolDecl.model_validate({"name": PROTOCOL, "transient_max_iter": 20})

    declared = CalibrationProtocolDecl.model_validate(
        {"name": PROTOCOL, "steady_max_trials": 20, "transient_max_trials": 40}
    )
    assert (declared.steady_max_trials, declared.transient_max_trials) == (20, 40)


@pytest.mark.parametrize(
    ("method", "option"),
    [
        ("scipy_nelder_mead", "maxfev"),
        ("cma_es", "max_evaluations"),
        ("gp_mapping", "max_iter"),
    ],
)
def test_a_method_option_that_counted_evaluations_is_refused_for_max_trials(
    method: str, option: str
) -> None:
    problem = method_options_problem(method, {option: 10})

    assert problem is not None
    assert f"{option}" in problem
    assert "max_trials" in problem
    with pytest.raises(ValueError, match="max_trials"):
        validate_method_kwargs(method, {option: 10})


@pytest.mark.parametrize("method", ["scipy_nelder_mead", "scipy_de"])
def test_maxiter_is_refused_because_an_iteration_is_not_an_evaluation(method: str) -> None:
    problem = method_options_problem(method, {"maxiter": 10})

    assert problem is not None
    assert "not an evaluation count" in problem
    assert "max_trials" in problem


def test_the_chain_length_of_da_mh_gp_has_its_own_name() -> None:
    problem = method_options_problem("da_mh_gp", {"max_iter": 100})

    assert problem is not None
    assert "chain_length" in problem
    assert validate_method_kwargs("da_mh_gp", {"chain_length": 100}).chain_length == 100


def test_the_budget_is_not_a_method_option_of_any_method() -> None:
    for method in ("grid", "optuna", "bisection", "cma_es", "gp_mapping"):
        problem = method_options_problem(method, {"max_trials": 10})
        assert problem is not None
        assert "[calibration] max_trials" in problem


def test_a_phase_and_a_stage_refuse_a_budget_option_at_load() -> None:
    with pytest.raises(ValidationError, match="phase 'sy' method_options.*max_trials"):
        _phase(method="cma_es", method_options={"max_evaluations": 20})
    with pytest.raises(ValidationError, match="transient_method_options.*max_trials"):
        CalibrationProtocolDecl.model_validate(
            {"name": PROTOCOL, "transient_method_options": {"maxfev": 20}}
        )
    with pytest.raises(ValidationError, match=r"\[calibration\] method_options.*max_trials"):
        CalibrationConfig.model_validate(
            {"method": "gp_mapping", "method_options": {"max_iter": 20}}
        )


def test_the_doctor_renames_the_budgets_and_moves_the_options_into_them(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration]\n"
        'method = "scipy_nelder_mead"\n'
        "max_iter = 60\n"
        "method_options = { maxfev = 25, xatol = 0.01 }\n"
        "[[calibration.phases]]\n"
        'name = "a"\n'
        'method = "cma_es"\n'
        'max_iter = "auto"\n'
        "method_options = { max_evaluations = 40, popsize = 4 }\n"
        "[[calibration.phases]]\n"
        'name = "b"\n'
        'method = "gp_mapping"\n'
        "method_options = { max_iter = 15, n_init = 5 }\n"
        "[[calibration.phases]]\n"
        'name = "c"\n'
        'method = "da_mh_gp"\n'
        "max_iter = 30\n"
        "method_options = { max_iter = 200 }\n"
        "[[calibration.phases]]\n"
        'name = "d"\n'
        'method = "scipy_de"\n'
        "method_options = { maxiter = 5 }\n"
        "[calibration.protocol]\n"
        'name = "matching_hydrographic_network"\n'
        "steady_max_iter = 20\n"
        "transient_max_iter = 90\n"
        'transient_method = "scipy_nelder_mead"\n'
        "transient_method_options = { maxfev = 50 }\n",
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    document = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]
    phases = {phase["name"]: phase for phase in document["phases"]}
    assert document["max_trials"] == 25
    assert document["method_options"] == {"xatol": 0.01}
    assert phases["a"]["max_trials"] == 40
    assert phases["a"]["method_options"] == {"popsize": 4}
    assert phases["b"]["max_trials"] == 15
    assert phases["b"]["method_options"] == {"n_init": 5}
    assert phases["c"]["max_trials"] == 30
    assert phases["c"]["method_options"] == {"chain_length": 200}
    assert phases["d"]["method_options"] == {"maxiter": 5}
    assert document["protocol"]["steady_max_trials"] == 20
    assert document["protocol"]["transient_max_trials"] == 50
    assert "transient_method_options" not in document["protocol"]
    assert any("not an evaluation count" in change and "[3]" in change for change in changes)
    assert "max_iter" not in path.read_text(encoding="utf-8")


def test_the_doctor_keeps_the_smaller_of_the_two_budgets(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[calibration]\nmethod = "cma_es"\nmax_iter = 20\n'
        "method_options = { max_evaluations = 90 }\n",
        encoding="utf-8",
    )

    fix_config_file(path)

    assert tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["max_trials"] == 20


def test_a_phase_takes_the_method_and_budget_of_the_section(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[calibration]\nmethod = "scipy_nelder_mead"\nmax_trials = 50\n'
        '[[calibration.phases]]\nname = "a"\nmethod_options = { maxfev = 80 }\n'
        '[[calibration.phases]]\nname = "b"\nmethod_options = { maxfev = 30 }\n',
        encoding="utf-8",
    )

    fix_config_file(path)

    phases = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]["phases"]
    assert [phase["max_trials"] for phase in phases] == [50, 30]
    assert all("method_options" not in phase for phase in phases)


def test_a_budget_option_without_a_method_is_left_with_the_reason(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text("[calibration]\nmethod_options = { max_iter = 20 }\n", encoding="utf-8")

    changes = fix_config_file(path)

    assert "max_iter = 20" in path.read_text(encoding="utf-8")
    assert any("method" in change and "left" in change for change in changes)


def test_a_sealed_document_reads_the_old_budget_keys_and_drops_the_old_options() -> None:
    doc = {
        "calibration": {
            "method": "gp_mapping",
            "max_iter": 50,
            "method_options": {"max_iter": 10, "n_init": 4},
            "phases": [
                {"name": "p", "method": "da_mh_gp", "method_options": {"max_iter": 80}},
                {"name": "q", "method": "scipy_nelder_mead", "method_options": {"maxfev": 9}},
            ],
            "protocol": {"steady_max_iter": 12},
        }
    }

    migrate_sealed_config_doc(doc)

    section = doc["calibration"]
    assert section["max_trials"] == 50
    assert section["method_options"] == {"n_init": 4}
    assert section["phases"][0]["method_options"] == {"chain_length": 80}
    assert "method_options" not in section["phases"][1]
    assert section["protocol"] == {"steady_max_trials": 12}


def test_a_frozen_protocol_run_with_the_old_budget_keys_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path)
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = frozen.replace("max_trials", "max_iter")
    assert old != frozen
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")
    assert PROJECT  # the same project the run was frozen from

    replayed = HydroModPyConfig.from_toml(sealed)

    expected = [p.model_dump(mode="json") for p in cfg.calibration.phases]
    assert [p.model_dump(mode="json") for p in replayed.calibration.phases] == expected
    document = tomllib.loads(old)
    with pytest.raises(ConfigValidationError):
        HydroModPyConfig.from_dict(document, base_dir=project)
    assert (
        HydroModPyConfig.from_snapshot({**document, "workspace": {"project_root": str(project)}})
        .calibration.phases[0]
        .max_trials
        == cfg.calibration.phases[0].max_trials
    )
