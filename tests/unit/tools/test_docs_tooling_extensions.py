"""Small contracts of the documentation tooling: CI schedule, renamed keys, TOML diff, API pages.

Each test pins a fact that a page states and that the tool reads from the code.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from tools.docs import field_registry, legacy_keys, tests_index

ROOT = Path(__file__).resolve().parents[3]
EXT = ROOT / "docs" / "source" / "_ext"


@pytest.fixture(scope="module")
def ext_path():
    """The Sphinx extensions are modules of docs/source/_ext, not of a package."""
    sys.path.insert(0, str(EXT))
    yield
    sys.path.remove(str(EXT))


# ---------------------------------------------------------------- tests_index


def test_petsc4py_is_read_in_the_steps_of_each_job() -> None:
    job = {"steps": [{"run": "conda install petsc petsc4py"}]}
    assert tests_index.installs_petsc4py(job)
    assert not tests_index.installs_petsc4py({"steps": [{"run": "pip install -e .[test]"}]})
    assert not tests_index.installs_petsc4py({})


def test_a_workflow_with_two_jobs_marks_only_the_job_that_installs_petsc4py(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        textwrap.dedent(
            """\
            name: both
            # petsc4py is only named in this comment
            on:
              schedule:
                - cron: "30 5 * * *"
            jobs:
              plain:
                name: Nightly plain run
                steps:
                  - run: python -m pytest tests/validation -m "not petsc"
              conda:
                name: Nightly conda run
                steps:
                  - run: mamba install petsc4py
                  - run: python -m pytest tests/validation -m petsc
            """
        )
    )
    jobs = {j["job"]: j["petsc4py"] for j in tests_index.schedule(tmp_path)}
    assert jobs == {"Nightly plain run": False, "Nightly conda run": True}


# ---------------------------------------------------------------- legacy_keys


@pytest.fixture(scope="module")
def renamed_nodes() -> dict:
    payload, _gates = field_registry.build_payload("test")
    return payload["nodes"]


def test_every_rename_the_loader_still_reads_is_classified(renamed_nodes: dict) -> None:
    accepted = legacy_keys.accepted_old_names(renamed_nodes)
    assert accepted["calibration.optimizer_kwargs"] == legacy_keys.WARNS
    assert accepted["calibration.phases.optimizer_kwargs"] == legacy_keys.WARNS
    assert accepted["calibration.protocol.steady_engine_options"] == legacy_keys.WARNS
    assert accepted["export.netcdf"] == legacy_keys.MIGRATES
    assert accepted["export.artifacts"] == legacy_keys.MIGRATES


def test_a_rename_the_loader_does_not_read_is_left_out(renamed_nodes: dict) -> None:
    nodes = {
        "flow.hk": {"model": "FlowConfig", "renamed_from": ["flow.never_read_key"]},
        **renamed_nodes,
    }
    assert "flow.never_read_key" not in legacy_keys.accepted_old_names(nodes)


def test_the_old_calibration_name_loads_with_a_rename_warning() -> None:
    from hydromodpy.calibration.config import CalibPhaseDecl
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    assert CalibPhaseDecl.model_legacy_keys["optimizer_kwargs"] == "method_options"
    with pytest.warns(ConfigKeyRenamedWarning):
        CalibPhaseDecl(name="p", parameters=["K"], optimizer_kwargs={})


# ---------------------------------------------------------------- TOML diff


def test_the_diff_of_two_files_is_taken_after_the_base_config_merge(
    tmp_path: Path, ext_path: None
) -> None:
    import hmp_params

    (tmp_path / "base.toml").write_text('[simulation]\nname = "a"\n\n[flow]\nk = 1.0\n')
    (tmp_path / "child.toml").write_text('base_config = "base.toml"\n\n[simulation]\nname = "b"\n')
    diff = hmp_params.resolved_toml_diff(tmp_path / "base.toml", tmp_path / "child.toml")
    lines = diff.splitlines()
    assert lines[:2] == ["--- base", "+++ child"]
    assert '-name = "a"' in lines
    assert '+name = "b"' in lines
    assert not any("k = 1.0" in line and line[0] in "+-" for line in lines)


def test_two_files_that_resolve_alike_give_an_empty_diff(tmp_path: Path, ext_path: None) -> None:
    import hmp_params

    (tmp_path / "a.toml").write_text('[simulation]\nname = "a"\n')
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n')
    assert hmp_params.resolved_toml_diff(tmp_path / "a.toml", tmp_path / "b.toml") == ""


def test_the_staircase_diffs_resolve_on_the_real_files(ext_path: None) -> None:
    import hmp_params

    example = ROOT / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
    diff = hmp_params.resolved_toml_diff(
        example / "step1_minimal.toml", example / "step2_local_data.toml"
    )
    assert '+name = "nancon_step2_local"' in diff.splitlines()


# ---------------------------------------------------------------- API pages


def test_a_generated_page_that_nothing_produces_any_more_is_pruned(
    tmp_path: Path, ext_path: None
) -> None:
    import hmp_api

    kept = tmp_path / "Run.md"
    gone = tmp_path / "Figure.md"
    mine = tmp_path / "written-by-hand.md"
    for page in (kept, gone):
        page.write_text(f"{hmp_api.HEADER}\n\n# page\n")
    mine.write_text("# a page somebody wrote\n")
    hmp_api.prune_generated({kept}, tmp_path)
    assert kept.exists()
    assert not gone.exists()
    assert mine.exists()


def test_the_type_aliases_of_a_verb_are_spelled_out_once(ext_path: None) -> None:
    import hmp_api

    verb = {
        "returns": [{"name": "Readable", "alias": "np.ndarray | xr.DataArray"}],
        "type_aliases": [
            {"name": "ConfigLike", "alias": "str | os.PathLike[str] | HydroModPyConfig"},
            {"name": "Readable", "alias": "np.ndarray | xr.DataArray"},
        ],
    }
    html = hmp_api.type_aliases_html(verb)
    assert "ConfigLike" in html
    assert "HydroModPyConfig" in html
    assert "Readable" not in html
    assert hmp_api.type_aliases_html({"returns": [], "type_aliases": []}) == ""
