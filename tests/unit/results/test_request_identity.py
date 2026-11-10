"""The request id and the solution key of a run, in tables of pairs."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hydromodpy.model.initial.state import PriorState
from hydromodpy.results.request_identity import (
    REQUEST_EXCLUDED,
    RESTART_KEY,
    ZONE_RUN_KEY,
    array_digest,
    binary_digest,
    input_role,
    prior_state_digest,
    request_id,
    section_of_role,
    solution_key,
)

DOCUMENT: dict[str, Any] = {
    "workspace": {"project_root": "/projects/nancon", "data_dir": "/projects/data"},
    "workflow": {"mode": "simulation", "verbosity": "quiet"},
    "simulation": {"name": "baseline", "time": {"start_datetime": "2020-01-01"}},
    "flow": {"param": {"K": {"field": {"kind": "homogeneous", "value": 1e-5}}}},
    "data": {
        "dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]},
        "recharge": {
            "sources": [
                {"source": "url", "url": "https://example.org/r.nc", "sha256": "f" * 64},
            ]
        },
    },
    "mesh": {"engine": "regular", "refinement_zone": [{"run": "spinup", "cell_size": 25}]},
}
INPUTS = {input_role("dem", 0): ("a" * 64, "raw"), input_role("recharge", 0): ("b" * 64, None)}
EDITION = "2.0"


def _changed(path: str, value: Any) -> dict[str, Any]:
    document = copy.deepcopy(DOCUMENT)
    *parents, leaf = path.split(".")
    holder: Any = document
    for part in parents:
        holder = holder[int(part)] if isinstance(holder, list) else holder.setdefault(part, {})
    holder[leaf] = value
    return document


def _id(document: dict[str, Any] = DOCUMENT, inputs=INPUTS, **keywords: Any) -> str:
    keywords.setdefault("edition", EDITION)
    return request_id(document, inputs, **keywords)


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(_changed("workspace.data_dir", "/elsewhere/data"), id="[workspace]"),
        pytest.param(_changed("workflow.verbosity", "debug"), id="[workflow]"),
        pytest.param(_changed("simulation.name", "renamed"), id="simulation.name"),
        pytest.param(_changed("flow.deliver_to", "s3://bucket/out"), id="deliver_to anywhere"),
        pytest.param(
            _changed("data.dem.sources.0.path", "/somewhere/else/dem.tif"),
            id="the path of a resolved file",
        ),
        pytest.param(
            _changed("data.recharge.sources.0.url", "https://mirror.org/r.nc"),
            id="the address of a resolved URL",
        ),
        pytest.param(
            _changed("data.recharge.sources.0.sha256", "0" * 64),
            id="the pin of a resolved URL",
        ),
    ],
)
def test_what_does_not_change_the_answer_keeps_the_request_id(document: dict[str, Any]) -> None:
    assert _id(document) == _id()


def test_the_excluded_keys_are_the_table_of_the_module() -> None:
    assert REQUEST_EXCLUDED == ("workspace", "workflow", "simulation.name", "*.deliver_to")


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(_changed("flow.param.K.field.value", 2e-5), id="a value of the model"),
        pytest.param(_changed("simulation.time.start_datetime", "2021-01-01"), id="a date"),
        pytest.param(_changed("mesh.engine", "voronoi"), id="the mesh engine"),
        pytest.param(_changed("data.dem.sources.0.source", "ign"), id="the kind of a source"),
        pytest.param(_changed("display.figures", ["map"]), id="a new section"),
    ],
)
def test_each_key_of_the_model_changes_the_request_id(document: dict[str, Any]) -> None:
    assert _id(document) != _id()


@pytest.mark.parametrize(
    ("inputs", "same"),
    [
        pytest.param(dict(INPUTS), True, id="the same bytes"),
        pytest.param({**INPUTS, input_role("dem", 0): ("c" * 64, "raw")}, False, id="other bytes"),
        pytest.param(
            {**INPUTS, input_role("dem", 0): ("a" * 64, "conditioned")}, False, id="another state"
        ),
        pytest.param({**INPUTS, "forcing:inputs/r.csv": ("d" * 64, None)}, False, id="one more"),
    ],
)
def test_the_inputs_enter_by_their_bytes_and_their_state(inputs: dict, same: bool) -> None:
    assert (_id(inputs=inputs) == _id()) is same


def test_a_path_without_a_resolved_input_stays_in_the_document() -> None:
    moved = _changed("data.dem.sources.0.path", "/somewhere/else/dem.tif")
    without = {input_role("recharge", 0): INPUTS[input_role("recharge", 0)]}

    assert _id(moved, inputs=without) != _id(inputs=without)


def test_two_copies_of_a_project_ask_alike() -> None:
    here = _changed("data.dem.sources.0.path", "/projects/nancon/inputs/dem.tif")
    there = _changed("data.dem.sources.0.path", "/copies/nancon/inputs/dem.tif")
    there["workspace"]["project_root"] = "/copies/nancon"

    assert _id(here, inputs={}) == _id(there, inputs={})


@pytest.mark.parametrize(
    ("keywords", "same"),
    [
        pytest.param({}, True, id="nothing more"),
        pytest.param({"edition": "2.1"}, False, id="another edition"),
        pytest.param({"window_state": "1" * 64}, False, id="a window state"),
    ],
)
def test_the_edition_and_the_window_state_count(keywords: dict, same: bool) -> None:
    assert (_id(**keywords) == _id()) is same


def test_an_earlier_run_enters_by_its_state_never_by_its_name() -> None:
    renamed = _changed("mesh.refinement_zone.0.run", "spinup.v2")
    zone = ZONE_RUN_KEY.format(index=0)

    first = _id(source_states={zone: "9" * 64})
    assert _id(renamed, source_states={zone: "9" * 64}) == first
    assert _id(source_states={zone: "8" * 64}) != first


def test_a_restart_enters_by_its_state() -> None:
    by_name = _changed(RESTART_KEY, "spinup_0")
    by_pin = _changed(RESTART_KEY, {"sim_id": "x" * 32, "path": "runs/spinup_0/fields.zarr"})

    assert _id(by_name, source_states={RESTART_KEY: "7" * 64}) == _id(
        by_pin, source_states={RESTART_KEY: "7" * 64}
    )


def test_a_state_for_a_key_the_document_lacks_is_refused() -> None:
    with pytest.raises(KeyError, match="no earlier run"):
        _id(source_states={RESTART_KEY: "7" * 64})


def test_the_roles_of_the_resolved_inputs_name_their_section() -> None:
    assert section_of_role(input_role("lake_levels", 3)) == "lake_levels"
    assert section_of_role("geology:inputs/geology.tif") is None


def _state(
    head: np.ndarray,
    stages: dict[str, float],
    *,
    sim_id: str = "a",
    path: str = "p",
    reaches: dict[int, float] | None = None,
):
    return PriorState(
        head=head, lake_stages=stages, path=path, sim_id=sim_id, sfr_stages=reaches or {}
    )


HEAD = np.array([[1.0, np.nan, -0.0], [2.0, 3.0, 4.0]])


@pytest.mark.parametrize(
    ("other", "same"),
    [
        pytest.param(_state(HEAD.copy(), {"l1": 5.0}, sim_id="b", path="q"), True, id="other run"),
        pytest.param(
            _state(np.where(np.isnan(HEAD), -np.nan, HEAD) + 0.0, {"l1": 5.0}),
            True,
            id="another NaN and zero sign",
        ),
        pytest.param(_state(HEAD.reshape(3, 2), {"l1": 5.0}), False, id="another shape"),
        pytest.param(_state(HEAD, {"l2": 5.0}), False, id="another lake id"),
        pytest.param(_state(HEAD, {"l1": 5.5}), False, id="another stage"),
        pytest.param(_state(HEAD * 2, {"l1": 5.0}), False, id="another head"),
        pytest.param(_state(HEAD, {"l1": 5.0}, reaches={0: 3.0}), False, id="a reach stage"),
    ],
)
def test_a_prior_state_is_hashed_by_what_a_run_reads(other: PriorState, same: bool) -> None:
    assert (prior_state_digest(other) == prior_state_digest(_state(HEAD, {"l1": 5.0}))) is same


REACHES = {0: 3.0, 1: 2.5}


@pytest.mark.parametrize(
    ("other", "same"),
    [
        pytest.param(_state(HEAD, {}, reaches={1: 2.5, 0: 3.0}), True, id="any order"),
        pytest.param(_state(HEAD, {}, reaches={0: 3.0, 2: 2.5}), False, id="another reach"),
        pytest.param(_state(HEAD, {}, reaches={0: 3.0, 1: 2.6}), False, id="another stage"),
        pytest.param(_state(HEAD, {}, reaches={0: 3.0}), False, id="one reach fewer"),
    ],
)
def test_the_reach_stages_and_their_numbers_count(other: PriorState, same: bool) -> None:
    assert (
        prior_state_digest(other) == prior_state_digest(_state(HEAD, {}, reaches=REACHES))
    ) is same


def test_a_state_without_reach_stages_keeps_the_digest_it_had() -> None:
    """The digest of 2.0 restarts, written out here, so their request_id does not move."""
    import hashlib
    import json

    from hydromodpy.results.request_identity import array_digest

    state = _state(HEAD, {"l1": 5.0})
    before = hashlib.sha256()
    before.update(json.dumps(["l1"]).encode("utf-8"))
    before.update(b"\0")
    before.update(array_digest({"head": HEAD, "lake_stages": np.array([5.0])}).encode("ascii"))

    assert prior_state_digest(state) == before.hexdigest()


def test_named_arrays_hash_alike_in_any_order_and_any_float_type() -> None:
    first = array_digest({"a": np.arange(3, dtype=np.float32), "b": [1, 2]})
    assert first == array_digest({"b": np.array([1.0, 2.0]), "a": [0.0, 1.0, 2.0]})


def _key(**changes: Any) -> str:
    keywords: dict[str, Any] = {
        "mesh_engine": {"engine": "regular", "version": "1"},
        "binaries": {},
        "code": {"model": "c1"},
        "packages": {"numpy": "2.1.0"},
    }
    keywords.update(changes)
    return solution_key(_id(), **keywords)


def test_the_solution_key_moves_with_what_computes(tmp_path: Path) -> None:
    binary = tmp_path / "mf6"
    binary.write_bytes(b"one build")
    with_binary = _key(binaries={"modflow6": binary})
    binary.write_bytes(b"another build of the binary")

    assert _key() == _key()
    assert _key(code={"model": "c2"}) != _key()
    assert _key(packages={"numpy": "2.2.0"}) != _key()
    assert _key(mesh_engine={"engine": "regular", "version": "2"}) != _key()
    assert _key(binaries={"modflow6": binary}) != with_binary
    assert _key(binaries={"modflow6": None}) == _key(binaries={"modflow6": tmp_path / "absent"})


def test_the_solution_key_never_reads_the_name() -> None:
    renamed = _changed("simulation.name", "another_name")

    assert solution_key(
        _id(renamed), mesh_engine={}, binaries={}, code={}, packages={}
    ) == solution_key(_id(), mesh_engine={}, binaries={}, code={}, packages={})


def test_a_binary_is_read_once_while_it_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hydromodpy.results.request_identity as identity

    binary = tmp_path / "libmf6.so"
    binary.write_bytes(b"x" * 1000)
    first = binary_digest(binary)

    def no_read(path: object) -> str:
        raise AssertionError(f"{path} read again")

    monkeypatch.setattr(identity, "sha256_streaming", no_read)
    assert binary_digest(binary) == first
    assert binary_digest(tmp_path / "absent") is None
