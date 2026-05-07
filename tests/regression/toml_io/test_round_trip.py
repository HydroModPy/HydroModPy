from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.generator import generate_toml_from_instances
from hydromodpy.core.toml_io.io import dump_toml_with_comments

_DESIGN_DRAFT_PROJECTS = {"03_groundwater_1d"}


def _example_project_tomls() -> list[Path]:
    root = Path(__file__).resolve().parents[3]
    project_root = root / "examples" / "projects"
    return [
        path
        for path in sorted(project_root.glob("*/project.toml"))
        if path.parent.name not in _DESIGN_DRAFT_PROJECTS
    ]


def _json_payload(cfg: HydroModPyConfig) -> dict:
    return cfg.model_dump(mode="json", exclude_none=True)


def _root_instances(cfg: HydroModPyConfig) -> dict[str, BaseModel]:
    instances: dict[str, BaseModel] = {}
    for name in HydroModPyConfig.model_fields:
        value = getattr(cfg, name)
        if isinstance(value, BaseModel):
            instances[name] = value
    return instances


def test_example_project_toml_round_trip_across_dumpers(tmp_path: Path) -> None:
    project_tomls = _example_project_tomls()
    assert project_tomls

    for source in project_tomls:
        cfg = HydroModPyConfig.from_toml(source)
        expected = _json_payload(cfg)

        commented_path = tmp_path / f"{source.parent.name}_commented.toml"
        dump_toml_with_comments(cfg, commented_path, profile="expert")
        commented_cfg = HydroModPyConfig.from_toml(commented_path)
        assert _json_payload(commented_cfg) == expected

        generated_path = tmp_path / f"{source.parent.name}_generated.toml"
        generate_toml_from_instances(
            _root_instances(cfg),
            output_path=generated_path,
            profile="expert",
            exclude_none=True,
        )
        generated_cfg = HydroModPyConfig.from_toml(generated_path)
        assert _json_payload(generated_cfg) == expected
