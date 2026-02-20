"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is.  Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml("examples/01S_short/config.toml")
    cfg.initializing.catch_name
    cfg.geographic.catch_def
    cfg.geographic.dem_init_path
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.watershed.initializing_config import InitializingConfig
from hydromodpy.watershed.geographic_config import GeographicConfig


class HydroModPyConfig(BaseModel):
    """Top-level configuration for HydroModPy."""

    initializing: InitializingConfig
    geographic: GeographicConfig

    @classmethod
    def from_toml(cls, toml_path: "Path | str") -> "HydroModPyConfig":
        """Load and validate configuration from a TOML file.

        Relative paths are resolved against the TOML file's directory.
        Absolute paths are left unchanged.  Paths starting with ``~``
        are expanded to the user's home directory.

        Path detection is automatic: any TOML key whose corresponding
        Pydantic field is typed as ``Path`` (or ``Optional[Path]``) will
        be resolved.
        """
        toml_path = Path(toml_path).resolve()
        with open(toml_path, "rb") as f:
            raw = tomllib.load(f)

        base = toml_path.parent

        _section_models = {
            "initializing": InitializingConfig,
            "geographic": GeographicConfig,
        }
        for section_name, model_cls in _section_models.items():
            section_data = raw.get(section_name, {})
            if isinstance(section_data, dict):
                _resolve_section_paths(section_data, model_cls, base)

        return cls(
            initializing=InitializingConfig(**raw["initializing"]),
            geographic=GeographicConfig(**raw["geographic"]),
        )


def _is_path_field(field_info: FieldInfo) -> bool:
    """Return True if the field is typed as ``Path`` or ``Optional[Path]``."""
    annotation = field_info.annotation
    if annotation is Path:
        return True
    return Path in getattr(annotation, "__args__", ())


def _resolve_section_paths(
    data: dict, model_cls: type[BaseModel], base: Path
) -> None:
    """Resolve relative paths and ``~`` in a config section dict (in-place)."""
    for field_name, field_info in model_cls.model_fields.items():
        if not _is_path_field(field_info):
            continue
        value = data.get(field_name)
        if isinstance(value, str) and value:
            p = Path(value).expanduser()
            if not p.is_absolute():
                p = (base / p).resolve()
            data[field_name] = str(p)
