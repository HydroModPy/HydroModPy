"""A renamed key loads with a warning, the doctor rewrites it, and a sealed run reads it.

The frame is tested with a table of its own, patched in, so it holds whatever
keys are renamed today: ``RENAMED_KEYS`` is what each rename adds a row to.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.calibration.config import renamed_to
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config import config_migration as migration
from hydromodpy.config.config_migration import (
    KeyRename,
    fix_config_file,
    migrate_config_doc_on_load,
    migrate_sealed_config_doc,
)
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document

PROJECT = """\
[site]
name = "nancon"
gauge = "NANCON"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "DEM_armorican_massif.tif"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["hydrography", "hydrometry"]

[[data.hydrography.sources]]
source = "custom"
path = "nancon_stream_network.gpkg"

[[data.hydrometry.sources]]
source = "custom"
path = "hydrometry"
station_ids = ["NANCON"]

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = 1
step_unit = "month"

[flow]
param_list = ["K", "Sy"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.05

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
"""

# Old spellings that exist nowhere in the models: each one is a stand-in rename.
SINCE = "2.3.0"
SEED = KeyRename("calibration", "seed_before", "seed", since=SINCE)
PHASE = KeyRename("calibration.phases[*]", "description_before", "description", since=SINCE)
PROTOCOL = KeyRename("calibration.protocol", "steady_window_before", "steady_window", since=SINCE)
PARAMETER = KeyRename("calibration.parameters.{*}", "bounds_before", "bounds", since=SINCE)


def _only(monkeypatch: pytest.MonkeyPatch, *rules: KeyRename) -> None:
    monkeypatch.setattr(migration, "RENAMED_KEYS", rules)


def _project(root: Path) -> Path:
    for relative in (
        "data/dem/DEM_armorican_massif.tif",
        "data/hydrography/nancon_stream_network.gpkg",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(b"x")
    (root / "data" / "hydrometry").mkdir(parents=True)
    project = root / "projects" / "nancon"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT, encoding="utf-8")
    return project


def test_the_message_names_the_new_key_and_the_doctor() -> None:
    text = renamed_to("max_trials", "the evaluations the search may run")

    assert text == (
        "renamed to 'max_trials' (the evaluations the search may run); "
        "hmp doctor --fix-config <file> rewrites it"
    )


def test_the_doctor_renames_a_key_of_a_section_a_phase_a_protocol_and_a_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _only(monkeypatch, SEED, PHASE, PROTOCOL, PARAMETER)
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration]\n"
        "seed_before = 7  # the draw\n"
        "[calibration.protocol]\n"
        'name = "matching_hydrographic_network"\n'
        'steady_window_before = { start = "2000-01-01", end = "2000-12-31" }\n'
        "[[calibration.phases]]\n"
        'name = "a"\n'
        'description_before = "first"\n'
        "[[calibration.phases]]\n"
        'name = "b"\n'
        'description_before = "second"\n'
        "[calibration.parameters.K]\n"
        "bounds_before = [1e-6, 1e-3]\n"
        "[calibration.parameters.Sy]\n"
        "bounds = [0.01, 0.3]\n",
        encoding="utf-8",
    )

    changes = fix_config_file(path)

    written = path.read_text(encoding="utf-8")
    document = tomllib.loads(written)
    assert document["calibration"]["seed"] == 7
    assert "# the draw" in written
    assert document["calibration"]["protocol"]["steady_window"]["start"] == "2000-01-01"
    assert [p["description"] for p in document["calibration"]["phases"]] == ["first", "second"]
    assert document["calibration"]["parameters"]["K"]["bounds"] == [1e-6, 1e-3]
    assert "_before" not in written
    assert len(changes) == 5
    assert fix_config_file(path) == []


def test_the_doctor_leaves_a_key_given_under_both_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _only(monkeypatch, SEED)
    path = tmp_path / "calibration.toml"
    path.write_text("[calibration]\nseed_before = 7\nseed = 8\n", encoding="utf-8")

    changes = fix_config_file(path)

    assert changes == ["calibration.seed_before left: 'seed' is given too, keep one"]
    assert tomllib.loads(path.read_text(encoding="utf-8"))["calibration"] == {
        "seed_before": 7,
        "seed": 8,
    }


def test_a_value_the_doctor_cannot_carry_over_stays_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(value, doc):
        raise migration._CannotRewrite("no unit to write")

    _only(monkeypatch, KeyRename("calibration", "seed_before", "seed", convert=refuse, since=SINCE))
    path = tmp_path / "calibration.toml"
    path.write_text("[calibration]\nseed_before = 7\n", encoding="utf-8")

    assert fix_config_file(path) == ["calibration.seed_before left: no unit to write"]
    assert "seed_before = 7" in path.read_text(encoding="utf-8")


def test_a_dropped_key_is_dropped_in_a_sealed_read(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = KeyRename("calibration", "seed_before", "seed", sealed_drop=True, since=SINCE)
    _only(monkeypatch, rule)
    doc = {"calibration": {"seed_before": 7}}

    migrate_sealed_config_doc(doc)

    assert doc == {"calibration": {}}


WITH_OLD_SEED = PROJECT.replace(
    "[calibration.parameters.K]", "[calibration]\nseed_before = 7\n\n[calibration.parameters.K]"
)


def test_a_renamed_key_warns_in_a_file_and_reads_in_silence_in_a_sealed_run_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recwarn: pytest.WarningsRecorder
) -> None:
    _only(monkeypatch, SEED)
    project = _project(tmp_path)
    user_file = project / "project.toml"
    user_file.write_text(WITH_OLD_SEED, encoding="utf-8")

    with pytest.warns(ConfigKeyRenamedWarning, match="seed_before -> seed") as told:
        assert HydroModPyConfig.from_toml(user_file).calibration.seed == 7
    assert f"hmp doctor --fix-config {user_file}" in str(told[0].message)

    sealed = project / "runs" / "nancon" / "config.toml"
    sealed.parent.mkdir(parents=True)
    sealed.write_text(WITH_OLD_SEED, encoding="utf-8")
    recwarn.clear()

    assert HydroModPyConfig.from_toml(sealed).calibration.seed == 7
    assert not [w for w in recwarn if issubclass(w.category, ConfigKeyRenamedWarning)]


def test_the_end_of_the_delay_refuses_a_file_and_still_reads_a_sealed_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = KeyRename("calibration", "seed_before", "seed", since=SINCE, sealed_only=True)
    _only(monkeypatch, rule)
    project = _project(tmp_path)
    user_file = project / "project.toml"
    user_file.write_text(WITH_OLD_SEED, encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="seed_before"):
        HydroModPyConfig.from_toml(user_file)
    assert fix_config_file(user_file) == []

    sealed = project / "runs" / "nancon" / "config.toml"
    sealed.parent.mkdir(parents=True)
    sealed.write_text(WITH_OLD_SEED, encoding="utf-8")
    assert HydroModPyConfig.from_toml(sealed).calibration.seed == 7
    assert "calibration.seed_before" not in [form.old for form in migration.old_forms()]


def test_a_sealed_document_is_read_under_the_new_name_not_a_user_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _only(monkeypatch, SEED)
    project = _project(tmp_path)
    document = tomllib.loads(
        (project / "project.toml")
        .read_text(encoding="utf-8")
        .replace(
            "[calibration.parameters.K]",
            "[calibration]\nseed_before = 7\n\n[calibration.parameters.K]",
        )
    )
    document["workspace"] = {"project_root": str(project)}

    assert HydroModPyConfig.from_snapshot(document).calibration.seed == 7
    with pytest.raises(ConfigValidationError, match="seed_before"):
        HydroModPyConfig.from_dict(document, base_dir=project)


def test_a_frozen_protocol_stage_with_an_old_key_reads_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    frozen = portable_config_document(cfg, run_dir, project)
    old = frozen.replace("\ndescription = ", "\ndescription_before = ")
    assert old != frozen
    sealed = run_dir / "config.toml"
    sealed.write_text(old, encoding="utf-8")
    _only(monkeypatch, PHASE)

    replayed = HydroModPyConfig.from_toml(sealed)

    expected = [p.model_dump(mode="json") for p in cfg.calibration.phases]
    assert [p.model_dump(mode="json") for p in replayed.calibration.phases] == expected


def test_a_load_of_a_user_file_does_not_run_the_sealed_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule = KeyRename("calibration", "seed_before", "seed", sealed_drop=True, since=SINCE)
    _only(monkeypatch, rule)
    doc = {"calibration": {"seed_before": 7}}
    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(doc, source=tmp_path / "project.toml")
    assert doc == {"calibration": {"seed": 7}}

    doc = {"calibration": {"seed_before": 7}}
    migrate_config_doc_on_load(doc, source=tmp_path / "runs" / "nancon" / "config.toml")
    assert doc == {"calibration": {}}


def test_a_renamed_table_keeps_its_place_and_its_comments(tmp_path: Path) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(
        "[calibration.optimizer_kwargs]\nsigma = 0.5  # the step\n\n[calibration.protocol]\n"
        'name = "matching_hydrographic_network"\n',
        encoding="utf-8",
    )

    assert fix_config_file(path) == ["calibration.optimizer_kwargs -> method_options"]

    written = path.read_text(encoding="utf-8")
    assert "sigma = 0.5  # the step" in written
    assert written.index("[calibration.method_options]") < written.index("[calibration.protocol]")
    assert tomllib.loads(written)["calibration"]["method_options"] == {"sigma": 0.5}


def test_a_comment_survives_in_a_document_the_doctor_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _only(monkeypatch, SEED)
    doc = tomlkit.parse("[calibration]\nseed_before = 7  # fixed\n")

    migration._rename_keys(doc, sealed=False)

    assert "seed = 7 # fixed" in tomlkit.dumps(doc)
