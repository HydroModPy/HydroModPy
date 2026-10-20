"""The effective copy of a TOML file: its overlays, ``--set`` and ``HMP_SET_*`` applied.

``hmp run`` and ``hmp calibrate`` take ``--overlay`` and ``--set``. When one of
them (or an ``HMP_SET_*`` variable) changes the document, the command runs a
temporary copy written beside the file the user named, so relative paths keep
resolving the same way.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io.overrides import (
    ENV_PATH_SEPARATOR,
    ENV_SET_PREFIX,
    env_overrides,
    env_set_names,
    parse_override_value,
    set_overrides,
)


def add_override_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``--overlay`` and ``--set``, the flags the effective copy applies."""
    parser.add_argument(
        "--overlay",
        action="append",
        default=[],
        type=Path,
        help="TOML overlay applied after base_config inheritance. Repeatable.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        dest="set_overrides",
        metavar="PATH=VALUE",
        help="Dotted TOML override applied after overlays, e.g. flow.param.K.field.value=2e-5.",
    )


def materialize_effective_toml(
    config_path: Path,
    *,
    args: argparse.Namespace,
) -> tuple[Path | None, dict[str, Any], dict[str, Any]]:
    """Return the source TOML or a temporary one with the overlays applied.

    The third member is what changed on top of the file, keyed by dotted
    path for ``--set`` and ``HMP_SET_*`` and under ``overlay`` for the
    overlay files, the way ``lineage.overrides`` seals it.
    """
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.core.toml_io.merge import merge_toml_payloads
    from hydromodpy.core.toml_io.writer import dumps

    overlays = [Path(path).expanduser().resolve() for path in getattr(args, "overlay", []) or []]
    set_items = list(getattr(args, "set_overrides", []) or [])
    cli_payload = set_overrides(set_items)
    env_payload = env_overrides(os.environ)

    base_payload = load_config_file(config_path, load_toml_with_base_config)
    overlay_payloads = [load_config_file(path, load_toml_with_base_config) for path in overlays]
    raw_toml = merge_toml_payloads(
        {},
        base_chain=[base_payload],
        overlays=overlay_payloads,
        cli_overrides=cli_payload,
        env_overrides=env_payload,
    )
    lineage_overrides: dict[str, Any] = {}
    for item in set_items:
        dotted_path, raw_value = item.split("=", 1)
        lineage_overrides[dotted_path.strip()] = parse_override_value(raw_value)
    for name in env_set_names(os.environ):
        # The case after the prefix is the case of the key, as env_overrides applies it.
        dotted = name[len(ENV_SET_PREFIX) :].replace(ENV_PATH_SEPARATOR, ".")
        lineage_overrides[dotted] = parse_override_value(os.environ[name])
    if overlays:
        lineage_overrides["overlay"] = [path.name for path in overlays]
    case = getattr(args, "case", None)
    calibrating = "calibration" in raw_toml
    if not (overlays or cli_payload or env_payload or (calibrating and case)):
        return None, raw_toml, lineage_overrides
    written = raw_toml
    if calibrating:
        # A calibration is named after the file the user named: say so, or the
        # session would be named after this temporary copy.
        name = str(case) if case else _own_name(config_path)
        written = {**raw_toml, "simulation": {**raw_toml.get("simulation", {}), "name": name}}

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix=f".{config_path.stem}.effective.",
        suffix=".toml",
        dir=config_path.parent,
        delete=False,
    ) as handle:
        handle.write(dumps(written))
        temp_path = Path(handle.name)
    return temp_path, raw_toml, lineage_overrides


class ConfigFileError(Exception):
    """A configuration file, or a file of its base_config chain, cannot be read."""


def _own_name(config_path: Path) -> str:
    """Return ``[simulation] name`` as the file writes it itself, else its stem.

    A name inherited through ``base_config`` never names a calibration.
    """
    import tomllib

    with config_path.open("rb") as handle:
        simulation = tomllib.load(handle).get("simulation")
    declared = simulation.get("name") if isinstance(simulation, Mapping) else None
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    return config_path.stem


def load_config_file(path: Path, loader: Any) -> dict[str, Any]:
    """Load one file with its base_config chain, naming the file at fault."""
    import tomllib

    try:
        return loader(path)
    except tomllib.TOMLDecodeError as exc:
        culprit = _first_unreadable_file(path) or path
        raise ConfigFileError(f"Invalid TOML in {culprit}: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigFileError(f"Invalid configuration file {path}: {exc}") from exc


def _first_unreadable_file(path: Path) -> Path | None:
    """Follow the base_config chain from *path* and return the first file that fails to parse."""
    import tomllib

    from hydromodpy.core.toml_io.loader import _read_toml
    from hydromodpy.core.toml_io.paths import is_declared_absolute_path

    seen: set[Path] = set()
    current: Path | None = path.resolve()
    while current is not None and current not in seen:
        seen.add(current)
        try:
            raw = _read_toml(current)
        except tomllib.TOMLDecodeError:
            return current
        except OSError:
            return None
        base = raw.get("base_config")
        if not isinstance(base, str) or not base:
            return None
        base_path = Path(base).expanduser()
        if not is_declared_absolute_path(base_path):
            base_path = current.parent / base_path
        current = base_path.resolve()
    return None


def cleanup_effective_toml(path: Path | None, *, source: Path) -> None:
    """Remove a temporary effective TOML if one was created."""
    if path is None or path == source:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def resolve_case_name(case: str | None, raw_toml: Mapping[str, Any], config_path: Path) -> str:
    """Return the name of the run: ``--case``, else ``[simulation] name``, else the TOML stem.

    The stem is the one of the file the user named, never the effective copy
    ``--set`` and ``--overlay`` write beside it.
    """
    if case:
        return str(case)
    simulation = raw_toml.get("simulation") if isinstance(raw_toml, Mapping) else None
    declared = simulation.get("name") if isinstance(simulation, Mapping) else None
    if declared:
        return str(declared)
    return config_path.stem
