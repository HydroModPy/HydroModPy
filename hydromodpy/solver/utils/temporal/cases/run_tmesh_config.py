"""Pydantic config for temporal-mesh demo cases."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.toml_io.paths import get_nested_section, resolve_path
from hydromodpy.solver.utils.temporal.tmesh_config import TMeshConfig


class TMeshCaseScenarioConfig(TMeshConfig):
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


class TMeshCasesConfig(HydroModelBase):
    """Collection of temporal-mesh scenarios loaded from one TOML file."""

    model_config = ConfigDict(extra="forbid")

    scenarios: list[TMeshCaseScenarioConfig] = Field(default_factory=list)
    output_summary_json: Path | None = None
    output_figures_dir: Path | None = None

    @field_validator("output_summary_json", "output_figures_dir", mode="before")
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
    ) -> TMeshCasesConfig:
        path = Path(config_path).expanduser().resolve()
        payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        section_cfg = dict(get_nested_section(payload, section))
        base = path.parent

        if section_cfg.get("output_summary_json") is not None:
            section_cfg["output_summary_json"] = resolve_path(
                section_cfg["output_summary_json"],
                base,
            )
        if section_cfg.get("output_figures_dir") is not None:
            section_cfg["output_figures_dir"] = resolve_path(
                section_cfg["output_figures_dir"],
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
                    item["chron_path"] = resolve_path(item["chron_path"], base)
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
