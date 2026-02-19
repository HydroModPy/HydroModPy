"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is.

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
        Absolute paths are left unchanged.

        Path detection is automatic: any TOML key whose corresponding
        Pydantic field is typed as ``Path`` will be resolved relative
        to the TOML file location when its value is a non-empty,
        non-absolute string.
        """
        toml_path = Path(toml_path)
        with open(toml_path, "rb") as f:
            raw = tomllib.load(f)

        base = toml_path.parent

        # Resolve relative paths for each section based on the Pydantic
        # model field types — no hand-maintained list needed.
        _section_models = {
            "initializing": InitializingConfig,
            "geographic": GeographicConfig,
        }
        for section_name, model_cls in _section_models.items():
            section_data = raw.get(section_name, {})
            if not isinstance(section_data, dict):
                continue
            for field_name, field_info in model_cls.model_fields.items():
                # Check if the field annotation is Path (or Optional[Path]).
                annotation = field_info.annotation
                is_path = annotation is Path or (
                    getattr(annotation, "__origin__", None) is type(None)
                    or _is_optional_path(annotation)
                )
                if not is_path:
                    is_path = _is_optional_path(annotation) or annotation is Path

                if not is_path:
                    continue
                value = section_data.get(field_name)
                if isinstance(value, str) and value and not Path(value).is_absolute():
                    section_data[field_name] = str((base / value).resolve())

        return cls(
            initializing=InitializingConfig(**raw["initializing"]),
            geographic=GeographicConfig(**raw["geographic"]),
        )


def _is_optional_path(annotation) -> bool:
    """Return True if *annotation* is ``Optional[Path]`` (i.e. ``Path | None``)."""
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        import typing
        args = getattr(annotation, "__args__", ())
        if origin is typing.Union:
            return Path in args
    return annotation is Path
