"""``search_space``, ``sampling`` and ``cost_transform`` each name one thing.

``transform`` named two unrelated maps: the space a search walks a parameter in
(``log``, ``logit``) and the function applied to a block's cost before its
weight. ``prior`` named a probability law that a search without a Bayesian
reading only uses to draw starting points. Now the parameter says
``search_space`` and ``sampling``, the block says ``cost_transform``, and the
engine's own vocabulary follows. A key renamed is refused with the new name,
the doctor rewrites the file, a sealed run config still reads, and the
``Calibrable`` metadata a field carries uses the same words.
"""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibParameterDecl
from hydromodpy.calibration.optim.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    SimulationOutput,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import fix_config_file, migrate_sealed_config_doc
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document
from tests.unit.config.test_a_renamed_key_is_refused_and_a_sealed_one_reads import (
    PROJECT,
    _project,
)

PROTOCOL = "matching_hydrographic_network"


def _parameter(**fields_: Any) -> CalibParameterDecl:
    return CalibParameterDecl.model_validate({"bounds": [1e-7, 1e-3], **fields_})


def _block(**fields_: Any) -> CalibObjectiveBlockDecl:
    return CalibObjectiveBlockDecl.model_validate(
        {"name": "q", "metric": "rmse", "uses_outputs": ["q"], **fields_}
    )


# -- the file ----------------------------------------------------------------


def test_a_parameter_names_its_search_space_and_its_sampling() -> None:
    declared = _parameter(search_space="log", sampling="log_uniform")

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")
    assert (_parameter().search_space, _parameter().sampling) == ("identity", "uniform")
    assert "transform" not in CalibParameterDecl.model_fields
    assert "prior" not in CalibParameterDecl.model_fields


def test_a_block_names_its_cost_transform() -> None:
    assert _block(cost_transform="log").cost_transform == "log"
    assert _block().cost_transform == "identity"
    assert "transform" not in CalibObjectiveBlockDecl.model_fields


@pytest.mark.parametrize(
    ("build", "new"),
    [
        (lambda: _parameter(transform="log"), "'search_space'"),
        (lambda: _parameter(prior="uniform"), "'sampling'"),
        (lambda: _block(transform="log"), "'cost_transform'"),
    ],
)
def test_the_old_word_is_refused_with_the_name_that_replaces_it(build: Any, new: str) -> None:
    with pytest.raises(ValidationError, match="is not accepted any more: renamed") as refused:
        build()

    assert new in str(refused.value)
    assert "hmp doctor --fix-config" in str(refused.value)


def test_a_parameter_declared_in_a_file_reads_the_new_words() -> None:
    from hydromodpy.calibration.config import CalibrationConfig

    section = CalibrationConfig.model_validate(
        {
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "search_space": "log", "sampling": "normal"}
            },
            "objective_blocks": [
                {"name": "q", "metric": "rmse", "uses_outputs": ["q"], "cost_transform": "inverse"}
            ],
            "outputs": {
                "q": {
                    "support": "point",
                    "x": 1.0,
                    "y": 2.0,
                    "variable": "discharge",
                    "observed_values": [1.0, 2.0],
                }
            },
        }
    )

    assert section.parameters["K"].search_space == "log"
    assert section.parameters["K"].sampling == "normal"
    assert section.objective_blocks[0].cost_transform == "inverse"


# -- the engine --------------------------------------------------------------


def test_a_resolved_dimension_carries_the_new_words() -> None:
    names = {field.name for field in fields(CalibParameter)}

    assert {"search_space", "sampling"} <= names
    assert not {"transform", "prior"} & names
    parameter = CalibParameter("K", 1e-6, 1e-3, search_space="log", sampling="log_uniform")
    assert parameter.lower_transformed == pytest.approx(-6.0)
    assert parameter.to_physical(-5.0) == pytest.approx(1e-5)


def test_the_space_is_built_from_the_new_keys_of_a_declaration() -> None:
    space = ParameterSpace.from_toml_mapping(
        {
            "K": {
                "bounds": [1e-6, 1e-3],
                "search_space": "log",
                "sampling": "log_uniform",
                "target": "flow.param.K.field.value",
            }
        }
    )

    (parameter,) = list(space)
    assert (parameter.search_space, parameter.sampling) == ("log", "log_uniform")
    declared = space.describe_values({"K": 1e-4})["K"]
    assert (declared["search_space"], declared["sampling"]) == ("log", "log_uniform")
    assert "transform" not in declared and "prior" not in declared


def test_a_block_cost_is_transformed_by_its_cost_transform() -> None:
    from hydromodpy.calibration.optim.objective import ObjectiveValue

    class Fixed:
        name = "fixed"

        def evaluate(self, sim: Any) -> ObjectiveValue:
            return ObjectiveValue(total=9.0, components={})

    composite = CompositeObjective([(Fixed(), 1.0)], cost_transform="log")

    assert composite.cost_transform == "log"
    assert composite.evaluate(None).total == pytest.approx(0.9542425, rel=1e-5)
    simulated = SimulationOutput(
        sim_id="s",
        stations=("q",),
        times=np.arange(2),
        values={"q": np.array([2.0, 4.0])},
    )
    costs = {
        word: ConfigBlockObjective(
            name="q",
            metric="rmse",
            uses_outputs=["q"],
            observed_by_output={"q": [1.0, 2.0]},
            cost_transform=word,
        )
        .evaluate(simulated)
        .total
        for word in ("identity", "log", "inverse")
    }
    assert costs["identity"] == pytest.approx(math.sqrt(2.5))
    assert costs["log"] == pytest.approx(math.log10(math.sqrt(2.5) + 1e-6))
    assert costs["inverse"] == pytest.approx(-1.0 / (math.sqrt(2.5) + 1e-6))


def test_the_engine_traits_name_the_search_space_a_stopping_rule_needs() -> None:
    from hydromodpy.calibration.optim.optimizer import EngineTraits

    names = {field.name for field in fields(EngineTraits)}

    assert "required_search_space" in names
    assert "required_transform" not in names


# -- what a field declares ---------------------------------------------------


def test_a_field_declares_its_search_space_and_its_sampling() -> None:
    declared = Calibrable(bounds=(1e-7, 1e-2), search_space="log", sampling="log_uniform")

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")
    record = declared.to_dict()
    assert (record["search_space"], record["sampling"]) == ("log", "log_uniform")
    assert "transform" not in record and "prior" not in record
    with pytest.raises(TypeError):
        Calibrable(transform="log")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Calibrable(prior="uniform")  # type: ignore[call-arg]


def test_the_hydraulic_conductivity_declares_a_log_search() -> None:
    from hydromodpy.spatial.field.field_param_sections import FieldHomogeneousSection

    extra = FieldHomogeneousSection.model_fields["value"].json_schema_extra
    declared = extra["calibrable"]  # type: ignore[index]

    assert (declared.search_space, declared.sampling) == ("log", "log_uniform")


def test_the_documentation_catalogue_prints_the_new_words() -> None:
    from hydromodpy.spatial.field.field_param_sections import FieldHomogeneousSection
    from tools.docs import field_registry

    leaf = field_registry._leaf_info(
        "value", FieldHomogeneousSection.model_fields["value"], "flow.param.K.field.value"
    )

    assert leaf["calibrable"] == {
        "bounds": None,
        "search_space": "log",
        "sampling": "log_uniform",
        "units": None,
    }


# -- the doctor --------------------------------------------------------------

OLD_FILE = """\
[calibration]
objective = "distance_gap"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"  # a conductivity
prior = "log_uniform"

[calibration.parameters.Sy]
bounds = [0.01, 0.3]
prior = "normal"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["seepage"]
transform = "log"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["q"]
"""


def test_the_doctor_rewrites_the_three_words_and_keeps_the_comment(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(OLD_FILE, encoding="utf-8")

    changes = fix_config_file(path)

    written = path.read_text(encoding="utf-8")
    section = tomllib.loads(written)["calibration"]
    assert section["parameters"]["K"] == {
        "bounds": [1e-7, 1e-3],
        "search_space": "log",
        "sampling": "log_uniform",
    }
    assert section["parameters"]["Sy"]["sampling"] == "normal"
    assert [block.get("cost_transform") for block in section["objective_blocks"]] == ["log", None]
    assert "# a conductivity" in written
    assert not re.search(r"^(transform|prior) = ", written, flags=re.MULTILINE)
    assert len(changes) == 4
    assert fix_config_file(path) == []


def test_the_doctor_reads_a_block_whose_cost_transform_leaves_metres(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration]\n"
        "[calibration.uncertainty]\n"
        "tolerance = 0.05\n"
        "[[calibration.objective_blocks]]\n"
        'name = "network"\n'
        'metric = "distance_gap"\n'
        'uses_outputs = ["seepage"]\n'
        'transform = "log"\n',
        encoding="utf-8",
    )

    fix_config_file(path)

    document = tomllib.loads(path.read_text(encoding="utf-8"))["calibration"]
    assert document["objective_blocks"][0]["cost_transform"] == "log"
    assert document["uncertainty"] == {"cost_margin": "5%"}


def test_the_doctor_leaves_a_word_written_under_both_names(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        '[calibration.parameters.K]\nbounds = [1e-7, 1e-3]\ntransform = "log"\n'
        'search_space = "identity"\n',
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    assert changes == [
        "calibration.parameters.K.transform left: 'search_space' is given too, keep one"
    ]


# -- a sealed run ------------------------------------------------------------


def test_a_sealed_document_reads_the_three_old_words() -> None:
    doc = {
        "calibration": {
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "transform": "log", "prior": "log_uniform"}
            },
            "objective_blocks": [{"name": "q", "metric": "rmse", "transform": "inverse"}],
        }
    }

    migrate_sealed_config_doc(doc)

    assert doc["calibration"]["parameters"]["K"] == {
        "bounds": [1e-7, 1e-3],
        "search_space": "log",
        "sampling": "log_uniform",
    }
    assert doc["calibration"]["objective_blocks"][0]["cost_transform"] == "inverse"


def test_a_frozen_run_with_the_old_words_reads_back(tmp_path: Path) -> None:
    project = _project(tmp_path)
    toml = project / "project.toml"
    toml.write_text(
        PROJECT.replace(
            "[calibration.parameters.K]\nbounds = [1e-7, 1e-3]",
            '[calibration.parameters.K]\nbounds = [1e-7, 1e-3]\nsearch_space = "log"'
            '\nsampling = "log_uniform"',
        ),
        encoding="utf-8",
    )
    cfg = HydroModPyConfig.from_toml(toml)
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = re.sub(r"^search_space = ", "transform = ", frozen, flags=re.MULTILINE)
    old = re.sub(r"^sampling = ", "prior = ", old, flags=re.MULTILINE)
    old = re.sub(r"^cost_transform = ", "transform = ", old, flags=re.MULTILINE)
    assert old != frozen
    assert "search_space" not in old and "sampling" not in old
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")

    replayed = HydroModPyConfig.from_toml(sealed)

    assert replayed.calibration.parameters["K"].search_space == "log"
    assert replayed.calibration.parameters["K"].sampling == "log_uniform"
    expected = [p.model_dump(mode="json") for p in cfg.calibration.phases]
    assert [p.model_dump(mode="json") for p in replayed.calibration.phases] == expected
    assert replayed.calibration.objective_blocks == cfg.calibration.objective_blocks
