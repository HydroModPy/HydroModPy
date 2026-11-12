"""Declaration of a capability (a process the job runner serves) and its checks.

The declaration is the one source of the process description, so it refuses at
import time what no run could honor: a bad id or version, an output path that
leaves the job directory, a network host a resolver would never return.
Hosts are plain lower-case names, at most 63 characters a label and 253 in all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from hydromodpy.schema.capability import (
    MAX_HOST_LENGTH,
    NAMES_THE_JOB_DOES_NOT_PRODUCE,
    CapabilityDecl,
    OutputDecl,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# Which test module runs each served capability and reads back the hosts it reached.
EGRESS_GATES = {
    "data-request": "tests/integration/data/test_data_request_seals_a_job.py",
    "domain-build": "tests/integration/domain/test_worker.py",
}
EGRESS_GATE_NAME = "test_the_only_hosts_it_contacts_are_the_ones_it_declares"


class _Request(BaseModel):
    value: int = 0


def _output(**overrides: object) -> OutputDecl:
    fields: dict[str, object] = {
        "id": "watershed_vector",
        "title": "Delineated catchment polygons",
        "path": "outputs/watershed.gpkg",
        "media_type": "application/geopackage+sqlite3",
        "roles": ("data", "primary"),
    }
    return OutputDecl(**(fields | overrides))  # type: ignore[arg-type]


def _decl(**overrides: object) -> CapabilityDecl:
    fields: dict[str, object] = {
        "id": "demo-delineate",
        "version": "1.2.3",
        "title": "Delineate a catchment",
        "description": "Declares one artefact.",
        "keywords": ("hydrology",),
        "request_model": _Request,
        "outputs": (_output(),),
        "exceptions": (FileNotFoundError,),
    }
    return CapabilityDecl(**(fields | overrides))  # type: ignore[arg-type]


def test_major_and_outputs_of_a_declaration() -> None:
    decl = _decl()

    assert decl.major == 1
    assert decl.output_ids == ("watershed_vector",)
    assert decl.output("watershed_vector").path == "outputs/watershed.gpkg"
    with pytest.raises(KeyError):
        decl.output("flow_direction")


def test_refused_names_are_the_reserved_ones() -> None:
    # The two spellings cannot be shared in code because of an import cycle.
    from hydromodpy.schema.job.layout import JOB_MANIFEST_FILENAME, REQUEST_FILENAME

    assert {JOB_MANIFEST_FILENAME, REQUEST_FILENAME} == NAMES_THE_JOB_DOES_NOT_PRODUCE


def test_egress_gates_are_on_disk() -> None:
    # A capability without a gate would publish "network": [] and nobody would compare it
    # to what a socket did. Each gate must exist and still carry its test.
    for capability_id, relative in sorted(EGRESS_GATES.items()):
        module = REPO_ROOT / relative
        assert module.is_file(), f"{capability_id}: {relative} is not on disk"
        assert f"def {EGRESS_GATE_NAME}(" in module.read_text(encoding="utf-8")


HOSTS_A_RESOLVER_NEVER_RETURNS = [
    "https://data.geopf.fr",
    "data.geopf.fr/telechargement",
    "data.geopf.fr:443",
    "*.geopf.fr",
    "Data.Geopf.Fr",
    "data..geopf.fr",
    "data.geopf.fr.",
    "-geopf.fr",
    "  ",
]

DECL_REFUSALS = [
    pytest.param({"id": "Domain-Build"}, "kebab-case", id="id with capitals"),
    pytest.param({"id": "domain_build"}, "kebab-case", id="id with underscore"),
    pytest.param({"id": "domain build"}, "kebab-case", id="id with space"),
    pytest.param({"id": "-domain"}, "kebab-case", id="id starts with a dash"),
    pytest.param({"id": "domain-"}, "kebab-case", id="id ends with a dash"),
    pytest.param({"version": "1"}, "x.y.z", id="version of one part"),
    pytest.param({"version": "1.0"}, "x.y.z", id="version of two parts"),
    pytest.param({"version": "1.0.0a1"}, "x.y.z", id="pre-release version"),
    pytest.param({"version": "v1.0.0"}, "x.y.z", id="version with a v"),
    pytest.param({"version": ""}, "x.y.z", id="empty version"),
    pytest.param({"outputs": ()}, "no output", id="no output"),
    pytest.param(
        {"outputs": (_output(), _output(path="outputs/other.gpkg"))},
        "repeats output id",
        id="two outputs on one id",
    ),
    # Two ids on one file would make the seal list the same bytes twice.
    pytest.param(
        {"outputs": (_output(), _output(id="watershed_copy"))},
        "repeats output path",
        id="two outputs on one path",
    ),
    pytest.param({"request_model": dict}, "request model", id="request model not a model"),
    pytest.param(
        {"exceptions": (ValueError, "HMPY.E101")}, "as an exception", id="exception is a string"
    ),
    pytest.param(
        {"reaches_network": ("data.geopf.fr", "data.geopf.fr")}, "repeats host", id="host twice"
    ),
    pytest.param(
        {"reaches_network": (f"{'a' * 64}.fr",)}, "label over 63 characters", id="label too long"
    ),
    pytest.param(
        {"reaches_network": (".".join(["a" * 63] * 4),)},
        "over the 253 a name has",
        id="name too long",
    ),
    *[
        pytest.param({"reaches_network": (host,)}, "demo-delineate", id=f"host {host!r}")
        for host in HOSTS_A_RESOLVER_NEVER_RETURNS
    ],
]


@pytest.mark.parametrize(("overrides", "message"), DECL_REFUSALS)
def test_declaration_refusals(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _decl(**overrides)


OUTPUT_REFUSALS = [
    pytest.param("/etc/passwd", "output path", id="absolute path"),
    pytest.param("../outside.gpkg", "output path", id="parent folder"),
    pytest.param("outputs/../../outside.gpkg", "output path", id="parent folder inside"),
    pytest.param("outputs//watershed.gpkg", "output path", id="double slash"),
    pytest.param("", "output path", id="empty path"),
    # The seal does not exist yet and the request came from the caller.
    pytest.param("manifest.json", "does not produce", id="the seal"),
    pytest.param("request.json", "does not produce", id="the request"),
]


@pytest.mark.parametrize(("path", "message"), OUTPUT_REFUSALS)
def test_output_path_refusals(path: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _output(path=path)


def test_host_limit_is_253() -> None:
    assert len(".".join(["a" * 63] * 4)) > MAX_HOST_LENGTH
