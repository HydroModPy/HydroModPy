"""Pydantic config for temporal-mesh demo cases."""

from __future__ import annotations

from collections.abc import Mapping
import importlib.util
from pathlib import Path
import sys
import tomllib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

try:
    from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfigModel
except Exception:
    module_path = Path(__file__).resolve().parents[1] / "tmesh_config.py"
    module_name = "_local_tmesh_config"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load local tmesh_config module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    TMeshConfigModel = module.TMeshConfigModel


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def _resolve_path(path_value: str | Path, base_dir: Path) -> str:
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


class TMeshCaseScenarioConfig(TMeshConfigModel):
    """One named temporal-mesh demo scenario."""

    model_config = ConfigDict(extra="forbid")

    id: str
    description: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_non_empty_id(cls, value):
        text = str(value).strip()
        if text == "":
            raise ValueError("scenario id cannot be empty")
        return text

    def to_builder_kwargs(self) -> dict[str, Any]:
        payload = self.model_dump(
            mode="python",
            exclude={"id", "description"},
            exclude_none=True,
        )
        return dict(payload)


class TMeshCasesConfig(BaseModel):
    """Collection of temporal-mesh scenarios loaded from one TOML file."""

    model_config = ConfigDict(extra="forbid")

    scenarios: list[TMeshCaseScenarioConfig] = Field(default_factory=list)
    output_summary_json: Path | None = None

    @field_validator("output_summary_json", mode="before")
    @classmethod
    def _expand_output_path(cls, value):
        if value is None:
            return None
        return Path(value).expanduser()

    @model_validator(mode="after")
    def _validate_unique_ids(self):
        if len(self.scenarios) == 0:
            raise ValueError("at least one scenario is required")
        ids = [item.id for item in self.scenarios]
        if len(set(ids)) != len(ids):
            raise ValueError("scenario ids must be unique")
        return self

    @classmethod
    def from_toml(
        cls,
        config_path: str | Path,
        *,
        section: str = "case",
    ) -> "TMeshCasesConfig":
        path = Path(config_path).expanduser().resolve()
        payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        section_cfg = dict(_get_nested_section(payload, section))
        base = path.parent

        if section_cfg.get("output_summary_json") is not None:
            section_cfg["output_summary_json"] = _resolve_path(
                section_cfg["output_summary_json"],
                base,
            )

        scenarios = section_cfg.get("scenarios")
        if isinstance(scenarios, list):
            resolved_scenarios: list[dict[str, Any]] = []
            for raw in scenarios:
                if not isinstance(raw, Mapping):
                    raise ValueError("each scenario must be a mapping")
                item = dict(raw)
                if item.get("chron_path") is not None:
                    item["chron_path"] = _resolve_path(item["chron_path"], base)
                resolved_scenarios.append(item)
            section_cfg["scenarios"] = resolved_scenarios

        return cls.model_validate(section_cfg)


def load_tmesh_cases_toml(
    config_path: str | Path,
    *,
    section: str = "case",
) -> TMeshCasesConfig:
    """Load and validate temporal-mesh case TOML."""
    path = Path(config_path).expanduser().resolve()
    try:
        return TMeshCasesConfig.from_toml(path, section=section)
    except ValidationError as exc:
        raise ValueError(f"Invalid tmesh case config in {path}: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid tmesh case config in {path}: {exc}") from exc
