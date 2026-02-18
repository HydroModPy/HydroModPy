"""
HydroModPy configuration root.

Two domain configs:
- GeographicConfig: DEM, domain definition (outlet / shapefile / raw DEM)
- ModflowConfig: all MODFLOW NWT parameters (hydraulic, forcing, boundary, solver)

Load from TOML or construct in Python -- same validated object either way.
"""

from pathlib import Path
import tomllib

from pydantic import BaseModel, ConfigDict

from .geographic import GeographicConfig
from .modflow import ModflowConfig


class HydroModPyConfig(BaseModel):
    """Root config aggregating geographic and modflow domains."""

    model_config = ConfigDict(extra="forbid")

    geographic: GeographicConfig
    modflow: ModflowConfig = ModflowConfig()

    @classmethod
    def from_toml(cls, path: str | Path) -> "HydroModPyConfig":
        """Load from a TOML file."""
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls(**data)

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)


__all__ = ["HydroModPyConfig", "GeographicConfig", "ModflowConfig"]
