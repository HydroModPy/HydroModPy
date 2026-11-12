"""The request id and the solution key of a run, in tables of pairs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import hydromodpy.results.record.request_identity as identity
from hydromodpy.model.initial.state import PriorState
from hydromodpy.results.record.request_identity import (
    REQUEST_EXCLUDED,
    RESTART_KEY,
    array_digest,
    binary_digest,
    input_role,
    prior_state_digest,
    request_id,
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
    "export": [{"variables": ["head"], "file": "head_last.tif"}],
}
INPUTS = {input_role("dem", 0): ("a" * 64, "raw"), input_role("recharge", 0): ("b" * 64, None)}
EDITION = "2.0"


def _id(document: dict[str, Any] = DOCUMENT, inputs=INPUTS, **keywords: Any) -> str:
    keywords.setdefault("edition", EDITION)
    return request_id(document, inputs, **keywords)


def test_excluded_keys() -> None:
    assert REQUEST_EXCLUDED == ("workspace", "workflow", "simulation.name")


def test_state_for_an_absent_key_is_refused() -> None:
    with pytest.raises(KeyError, match="no earlier run"):
        _id(source_states={RESTART_KEY: "7" * 64})


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
def test_prior_state_digest(other: PriorState, same: bool) -> None:
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
def test_reach_stages_in_the_digest(other: PriorState, same: bool) -> None:
    assert (
        prior_state_digest(other) == prior_state_digest(_state(HEAD, {}, reaches=REACHES))
    ) is same


def test_digest_without_reach_stages() -> None:
    # The digest of restarts of a pre-release, written out so their request_id does not move.
    state = _state(HEAD, {"l1": 5.0})
    before = hashlib.sha256()
    before.update(json.dumps(["l1"]).encode("utf-8"))
    before.update(b"\0")
    before.update(array_digest({"head": HEAD, "lake_stages": np.array([5.0])}).encode("ascii"))

    assert prior_state_digest(state) == before.hexdigest()


def _key(**changes: Any) -> str:
    keywords: dict[str, Any] = {
        "mesh_engine": {"engine": "regular", "version": "1"},
        "binaries": {},
        "code": {"model": "c1"},
        "packages": {"numpy": "1.26.4"},
    }
    keywords.update(changes)
    return solution_key(_id(), **keywords)


def test_solution_key(tmp_path: Path) -> None:
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


def test_binary_is_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "libmf6.so"
    binary.write_bytes(b"x" * 1000)
    first = binary_digest(binary)

    def no_read(path: object) -> str:
        raise AssertionError(f"{path} read again")

    monkeypatch.setattr(identity, "sha256_of", no_read)
    assert binary_digest(binary) == first
    assert binary_digest(tmp_path / "absent") is None
