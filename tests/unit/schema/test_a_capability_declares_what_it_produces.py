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

from hydromodpy.schema.capability import CapabilityDecl, OutputDecl


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
