"""The minimal files of the parameter reference are built from the registry and validated."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from tools.docs import field_registry, minimal_files


def _leaf(path: str, **kw) -> dict:
    return {"path": path, "name": path.rsplit(".", 1)[-1], "kind": "leaf", **kw}


def test_a_required_key_takes_its_example_then_its_default_then_its_first_value() -> None:
    nodes = {
        "": {"children": ["a", "u"]},
        "a": {
            "kind": "table",
            "name": "a",
            "required": True,
            "children": ["a.x", "a.y", "a.z", "a.w", "a.o"],
        },
        "a.x": _leaf("a.x", required=True, examples=['"dem.tif"'], default=None),
        "a.y": _leaf("a.y", required=True, default="3"),
        "a.z": _leaf("a.z", required=True, literal=["simulation", "overview"]),
        "a.w": _leaf("a.w", required=True),
        "a.o": _leaf("a.o", required=False, default="1"),
        "u": {
            "kind": "union",
            "name": "u",
            "required": False,
            "discriminator": "kind",
            "variants_detail": [{"value": "one"}, {"value": "two"}],
            "children": ["u.kind", "u.p", "u.q"],
        },
        "u.kind": _leaf("u.kind", default='"two"', literal=["one", "two"], variants=["one", "two"]),
        "u.p": _leaf("u.p", required=True, default="1", variants=["one"]),
        "u.q": _leaf("u.q", required=True, default="2", variants=["two"]),
    }
    builder = minimal_files.Builder(nodes)
    doc = builder.file("u")
    assert doc["a"] == {"x": "dem.tif", "y": 3, "z": "simulation"}
    assert doc["u"] == {"kind": "two", "q": 2}
    assert builder.missing == ["a.w"]


def test_the_three_required_sections_make_a_valid_file(tmp_path: Path) -> None:
    """The smallest file the grammar page names: workflow, workspace, geographic."""
    path = tmp_path / "minimal.toml"
    path.write_text(
        '[workflow]\nmode = "simulation"\n\n[workspace]\nproject_root = "."\n\n'
        '[geographic.catchment]\ncatch_def = "dem"\ndem_init_path = "dem.tif"\n'
    )
    HydroModPyConfig.from_toml(path)


@pytest.fixture(scope="module")
def built() -> dict:
    payload, _ = field_registry.build_payload("test")
    return minimal_files.build(payload["nodes"])


def test_every_section_gets_a_file_or_the_reason_it_has_none(built: dict) -> None:
    assert {"workflow", "workspace", "geographic", "flow", "calibration"} <= set(built)
    for item in built.values():
        tomllib.loads(item["toml"])
        assert item["error"] is None or item["error"].strip()


def test_every_file_shown_as_valid_passes_the_models(built: dict, tmp_path: Path) -> None:
    for section, item in built.items():
        if item["error"] is not None:
            continue
        path = tmp_path / f"{section}.toml"
        path.write_text(item["toml"])
        HydroModPyConfig.from_toml(path)
