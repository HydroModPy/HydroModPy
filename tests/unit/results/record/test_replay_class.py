"""The class of a replay: bit, deviation, or none when nothing was compared."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from hydromodpy.results.record.replay_class import ReplayDeviationError, classify_replay
from hydromodpy.results.record.values import stored_value_digests
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.schema.seal import ValueDigests


def _seal_payload(*, version: int, values: ValueDigests | None = None, solver: str = "modflow6"):
    payload = {
        "manifest_version": version,
        "sealed_at": "2026-01-01T00:00:00+00:00",
        "run": {
            "sim_id": "source-run",
            "name": "island",
            "name_stem": "island",
            "version": 1,
            "status": "completed",
            "project": "island",
            "case_id": "island",
            "rel_dir": "runs/island",
            "attempt": 1,
            "attempt_id": "att",
            "solver": solver,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        "geometry": {"mesh_engine": "regular"},
        "period": {},
        "config": {"file": "config.toml"},
        "identity": {
            "case_id": "island",
            "sim_id": "source-run",
            "attempt_id": "att",
            "hydromodpy_version": "2.0.0",
        },
        "checks": {},
        "artifacts": [],
    }
    if version == 4:
        payload["profile"] = "run"
    if values is not None:
        payload["values"] = values.model_dump(mode="json")
    return payload


def _write_run(root: Path, payload: dict, arrays: dict[str, np.ndarray] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    if arrays is not None:
        group = zarr.open_group(str(root / "fields.zarr"), mode="w")
        group.attrs["zarr_schema_version"] = ZARR_SCHEMA_VERSION
        for name, values in arrays.items():
            array = group.create_array(name, shape=values.shape, dtype="float64")
            array[:] = values
    return root


def _digests(root: Path) -> ValueDigests:
    return stored_value_digests(root)


HEADS = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)


def test_a_moved_field_is_a_deviation_with_its_two_measures(tmp_path: Path):
    moved = HEADS.copy()
    moved[0, 0] = 1.5
    source = _write_run(tmp_path / "source", _seal_payload(version=4), {"heads": HEADS})
    replay = _write_run(tmp_path / "replay", _seal_payload(version=4), {"heads": moved})
    payload = _seal_payload(version=4, values=_digests(source))
    (source / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    replay_class = classify_replay(source, replay, _digests(replay), strict=False)

    assert replay_class.class_ == "deviation"
    difference = replay_class.differs["fields/heads"]
    assert difference.max_abs == pytest.approx(0.5)
    assert difference.rel_l2 == pytest.approx(0.5 / np.linalg.norm(HEADS))
    assert difference.precision == "exact"


def test_a_v3_source_is_compared_on_its_stored_values(tmp_path: Path):
    source = _write_run(tmp_path / "source", _seal_payload(version=3), {"heads": HEADS})
    replay = _write_run(tmp_path / "replay", _seal_payload(version=4), {"heads": HEADS})

    replay_class = classify_replay(source, replay, _digests(replay), strict=False)

    assert replay_class.basis == "stored"
    assert replay_class.class_ == "bit"


def _final_state(root: Path, values: np.ndarray) -> None:
    group = zarr.open_group(str(root / "final_state"), mode="w")
    group.create_array("head", shape=values.shape, dtype="float64")[:] = values


def test_a_final_state_a_v3_source_could_not_hold_is_added_and_stays_a_bit(tmp_path: Path):
    source = _write_run(tmp_path / "source", _seal_payload(version=3), {"heads": HEADS})
    replay = _write_run(tmp_path / "replay", _seal_payload(version=4), {"heads": HEADS})
    _final_state(replay, HEADS[-1])

    replay_class = classify_replay(source, replay, _digests(replay), strict=True)

    assert replay_class.class_ == "bit"
    assert replay_class.added == ["final_state/head"]


def test_a_final_state_a_v4_source_lacks_is_a_deviation(tmp_path: Path):
    source = _write_run(tmp_path / "source", _seal_payload(version=4), {"heads": HEADS})
    payload = _seal_payload(version=4, values=_digests(source))
    (source / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    replay = _write_run(tmp_path / "replay", _seal_payload(version=4), {"heads": HEADS})
    _final_state(replay, HEADS[-1])

    replay_class = classify_replay(source, replay, _digests(replay), strict=False)

    assert replay_class.class_ == "deviation"
    assert replay_class.added == ["final_state/head"]


def test_the_flat_concentration_of_a_v3_source_is_the_one_species_of_its_replay(
    tmp_path: Path,
):
    source = _write_run(tmp_path / "source", _seal_payload(version=3), {"concentration": HEADS})
    replay = _write_run(tmp_path / "replay", _seal_payload(version=4))
    group = zarr.open_group(str(replay / "fields.zarr"), mode="a")
    group.create_group("concentration").create_array("tracer", shape=HEADS.shape, dtype="float64")[
        :
    ] = HEADS

    replay_class = classify_replay(source, replay, _digests(replay), strict=False)

    assert replay_class.class_ == "bit"
    assert replay_class.added == []
    assert replay_class.removed == []


def test_a_source_without_values_compares_nothing(tmp_path: Path):
    source = _write_run(tmp_path / "source", _seal_payload(version=3))
    replay = _write_run(tmp_path / "replay", _seal_payload(version=4))

    replay_class = classify_replay(source, replay, _digests(replay), strict=False)

    assert replay_class.basis == "none"
    assert replay_class.class_ is None
    assert replay_class.differs == {}


def test_a_strict_replay_refuses_a_deviation_before_any_seal(tmp_path: Path):
    moved = HEADS.copy()
    moved[0, 0] = 1.5
    source = _write_run(tmp_path / "source", _seal_payload(version=4), {"heads": HEADS})
    replay = _write_run(tmp_path / "replay", _seal_payload(version=4), {"heads": moved})
    payload = _seal_payload(version=4, values=_digests(source))
    (source / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReplayDeviationError, match="fields/heads") as raised:
        classify_replay(source, replay, _digests(replay), strict=True)

    assert raised.value.code == "HMPY.E900"
    assert "max |delta|" in raised.value.message
    assert "without --strict" in raised.value.message
