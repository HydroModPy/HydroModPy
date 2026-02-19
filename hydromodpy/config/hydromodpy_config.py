"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is.

Usage::

    from hydromodpy.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml("examples/01S_short/config.toml")
    cfg.initializing.catch_name
    cfg.geographic.dem_path
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel

from hydromodpy.watershed.initializing_config import InitializingConfig
from hydromodpy.watershed.geographic_config import GeographicConfig


# Path-type fields per TOML section that need relative-path resolution.
_PATH_FIELDS: dict[str, list[str]] = {
    "initializing": ["out_dir_path"],
    "geographic":   ["dem_path", "from_dem", "from_shp", "bottom_path", "reg_fold"],
}


class HydroModPyConfig(BaseModel):
    """Top-level configuration for HydroModPy."""

    initializing: InitializingConfig
    geographic: GeographicConfig

    @classmethod
    def from_toml(cls, toml_path: "Path | str") -> "HydroModPyConfig":
        """Load and validate configuration from a TOML file.

        Relative paths are resolved against the TOML file's directory.
        Absolute paths are left unchanged.
        """
        toml_path = Path(toml_path)
        with open(toml_path, "rb") as f:
            raw = tomllib.load(f)

        base = toml_path.parent
        for section, keys in _PATH_FIELDS.items():
            section_data = raw.get(section, {})
            for key in keys:
                if section_data.get(key):
                    p = Path(section_data[key])
                    if not p.is_absolute():
                        section_data[key] = str((base / p).resolve())

        return cls(
            initializing=InitializingConfig(**raw["initializing"]),
            geographic=GeographicConfig(**raw["geographic"]),
        )
