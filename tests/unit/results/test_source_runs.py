"""An earlier run named in a config (``restart_from`` or a refinement zone) resolves to a sim_id.

A bare name is its latest version. The frozen ``config.toml`` writes the sim_id instead. The
request id tells such a run by the state the new run reads from it.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.record.request_identity import request_id
from hydromodpy.results.source_runs import source_run_id
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from tests._helpers.sealed_runs import make_project, seal_run

ZONE = {"where": "watertable_depth", "below": 0.5, "cell_size": 25.0}


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "demo")


def sealed_with_fields(project, name):
    sim_id = seal_run(project, name, site=None)
    (project / "runs" / name / FIELDS_STORE_NAME).mkdir()
    return sim_id


def test_a_reference_resolves_to_the_sim_id_of_a_sealed_run(project):
    first = sealed_with_fields(project, "spinup")
    second = sealed_with_fields(project, "spinup.v2")

    assert source_run_id(project, "spinup") == second, "a bare name is the latest version"
    assert source_run_id(project, "spinup.v2") == second
    assert source_run_id(project, "runs/spinup") == first
    assert source_run_id(project, f"runs/spinup/{FIELDS_STORE_NAME}") == first
    assert source_run_id(project, str(project / "runs" / "spinup")) == first
    assert source_run_id(project, first) == first
    assert source_run_id(project, first[:10]) == first


def test_a_reference_that_names_no_sealed_run_has_no_sim_id(project):
    sealed = sealed_with_fields(project, "spinup")
    (project / "runs" / "open").mkdir()

    assert source_run_id(project, "nowhere") is None
    assert source_run_id(project, "open") is None
    assert source_run_id(project, "") is None
    assert source_run_id(project, sealed[:4]) is None, "a prefix needs eight characters"
    assert source_run_id(project, "0" * 32) is None


def test_a_configuration_without_a_project_root_is_told_as_written():
    def told(run):
        document = {"mesh": {"engine": "voronoi", "refinement_zone": [{**ZONE, "run": run}]}}
        return request_id(document, {}, edition="2.0")

    assert told("coarse") == told("coarse")
    assert told("coarse") != told("other")
