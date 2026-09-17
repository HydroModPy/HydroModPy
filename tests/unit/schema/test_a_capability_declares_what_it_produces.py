"""A capability declaration refuses at import time what it could not honour.

The declaration is the single source the process description is generated
from, so a fault in it ships as a description that promises something no run
produces. Every check here fires when the declaration is built — at import of
the module that declares the capability — and not when a caller reads the
description hours later on another machine.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from hydromodpy.schema.capability import (
    MAX_HOST_LENGTH,
    NAMES_THE_JOB_DOES_NOT_PRODUCE,
    CapabilityDecl,
    OutputDecl,
)


class _Request(BaseModel):
    """The smallest thing a capability can validate against."""

    value: int = 0


def _output(**overrides: object) -> OutputDecl:
    fields: dict[str, object] = {
        "id": "watershed_vector",
        "title": "Delineated catchment polygons",
        "path": "outputs/watershed.gpkg",
        "media_type": "application/geopackage+sqlite3",
        "roles": ("data", "primary"),
    }
    fields.update(overrides)
    return OutputDecl(**fields)  # type: ignore[arg-type]


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
    fields.update(overrides)
    return CapabilityDecl(**fields)  # type: ignore[arg-type]


def test_a_declaration_names_its_major_and_its_outputs() -> None:
    decl = _decl()
    assert decl.major == 1
    assert decl.output_ids == ("watershed_vector",)
    assert decl.output("watershed_vector").path == "outputs/watershed.gpkg"


def test_an_output_that_was_not_declared_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        _decl().output("flow_direction")


@pytest.mark.parametrize(
    "capability_id",
    ["Terrain-Delineate", "terrain_delineate", "terrain delineate", "-terrain", "terrain-"],
)
def test_an_id_that_is_not_kebab_case_is_refused(capability_id: str) -> None:
    with pytest.raises(ValueError, match="kebab-case"):
        _decl(id=capability_id)


@pytest.mark.parametrize("version", ["1", "1.0", "1.0.0a1", "v1.0.0", ""])
def test_a_version_that_is_not_three_parts_is_refused(version: str) -> None:
    with pytest.raises(ValueError, match="x.y.z"):
        _decl(version=version)


def test_a_capability_without_an_output_is_refused() -> None:
    with pytest.raises(ValueError, match="no output"):
        _decl(outputs=())


def test_two_outputs_on_one_id_are_refused() -> None:
    with pytest.raises(ValueError, match="repeats output id"):
        _decl(outputs=(_output(), _output(path="outputs/other.gpkg")))


def test_two_outputs_on_one_path_are_refused() -> None:
    """Two ids on one file would make the seal list the same bytes twice."""
    with pytest.raises(ValueError, match="repeats output path"):
        _decl(outputs=(_output(), _output(id="watershed_copy")))


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../outside.gpkg", "outputs/../../outside.gpkg", "outputs//watershed.gpkg", ""],
)
def test_an_output_path_that_could_leave_the_job_directory_is_refused(path: str) -> None:
    with pytest.raises(ValueError):
        _output(path=path)


@pytest.mark.parametrize("path", ["manifest.json", "request.json"])
def test_an_output_claiming_a_file_the_job_does_not_produce_is_refused(path: str) -> None:
    """The seal does not exist yet, and the request came from the caller."""
    with pytest.raises(ValueError, match="does not produce"):
        _output(path=path)


def test_a_control_document_the_job_does_write_may_be_declared() -> None:
    """The process description lists the outcome among its outputs."""
    assert _output(id="outcome", path="outcome.json").path == "outcome.json"


def test_the_refused_names_are_the_ones_the_job_layout_reserves() -> None:
    """Pins two spellings an import cycle forbids sharing."""
    from hydromodpy.schema.job.layout import JOB_MANIFEST_FILENAME, REQUEST_FILENAME

    assert NAMES_THE_JOB_DOES_NOT_PRODUCE == {JOB_MANIFEST_FILENAME, REQUEST_FILENAME}


def test_a_request_model_that_is_not_a_model_is_refused() -> None:
    with pytest.raises(ValueError, match="request model"):
        _decl(request_model=dict)


def test_a_declared_exception_that_is_not_an_exception_is_refused() -> None:
    with pytest.raises(ValueError, match="as an exception"):
        _decl(exceptions=(ValueError, "HMPY.E101"))


def test_the_extra_members_of_an_output_cannot_be_rewritten_after_the_fact() -> None:
    """The description is generated from the declaration, possibly twice.

    A caller holding the declaration must not be able to change what the
    second generation writes.
    """
    output = _output(extra={"hmp:pointer_convention": "d8_wbt"})
    assert output.extra["hmp:pointer_convention"] == "d8_wbt"
    with pytest.raises(TypeError):
        output.extra["hmp:pointer_convention"] = "d8_esri"  # type: ignore[index]


def test_a_declaration_cannot_be_rewritten_after_the_fact() -> None:
    decl = _decl()
    with pytest.raises(AttributeError):
        decl.version = "2.0.0"  # type: ignore[misc]


def test_a_capability_that_names_no_host_reaches_nothing() -> None:
    """The default is the answer a node with no egress needs to hear."""
    assert _decl().reaches_network == ()


def test_the_declared_hosts_are_kept_in_the_order_they_were_written() -> None:
    decl = _decl(reaches_network=["hubeau.eaufrance.fr", "data.geopf.fr"])
    assert decl.reaches_network == ("hubeau.eaufrance.fr", "data.geopf.fr")


@pytest.mark.parametrize(
    "host",
    [
        "https://data.geopf.fr",
        "data.geopf.fr/telechargement",
        "data.geopf.fr:443",
        "*.geopf.fr",
        "Data.Geopf.Fr",
        "data..geopf.fr",
        "data.geopf.fr.",
        "-geopf.fr",
        "  ",
    ],
)
def test_a_host_a_resolver_would_never_hand_back_is_refused(host: str) -> None:
    """Every refusal exists so the declaration is comparable to a resolved name.

    A scheme, a path or a port makes the entry something ``getaddrinfo`` never
    sees; an uppercase spelling makes the comparison depend on case folding
    nobody declared; a wildcard is a pattern no gate in this tree matches.
    """
    with pytest.raises(ValueError, match="demo-delineate"):
        _decl(reaches_network=(host,))


def test_one_host_declared_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="repeats host"):
        _decl(reaches_network=("data.geopf.fr", "data.geopf.fr"))


def test_a_label_no_resolver_would_answer_is_refused() -> None:
    with pytest.raises(ValueError, match="label over 63 characters"):
        _decl(reaches_network=(f"{'a' * 64}.fr",))


def test_a_name_longer_than_a_name_can_be_is_refused() -> None:
    host = ".".join(["a" * 63] * 4)
    assert len(host) > MAX_HOST_LENGTH
    with pytest.raises(ValueError, match="over the 253 a name has"):
        _decl(reaches_network=(host,))


def test_an_address_a_caller_pins_instead_of_a_name_is_accepted() -> None:
    """Deliberate: the gate compares a connection to this same list.

    A capability contacting a fixed address has no name to declare, and refusing
    the literal would leave it unable to declare anything true.
    """
    assert _decl(reaches_network=("192.0.2.10",)).reaches_network == ("192.0.2.10",)
