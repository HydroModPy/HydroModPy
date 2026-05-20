"""IO helpers for testbed artifacts (read/write JSON, CSV, TOML)."""

from __future__ import annotations

import csv
import json
import math
import numbers
import textwrap
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io import is_declared_absolute_path

PATH_KEY_HINTS = ("path", "root", "dir", "folder", "file", "mask")
TomlDescriptionProvider = Callable[[tuple[str, ...]], str | None]


def _jsonable(value: Any) -> Any:
    """Return a JSON-serializable representation of one value."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, numbers.Real):
        number = float(value)
        if math.isfinite(number):
            return repr(number)
        raise ValueError("Cannot render non-finite numeric TOML value")
    if isinstance(value, Path):
        return json.dumps(value.as_posix())
    if isinstance(value, str):
        return json.dumps(value.replace("\\", "/"))
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    if isinstance(value, tuple):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML scalar type: {type(value).__name__}")


def _is_mapping_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def _append_toml_description(
    lines: list[str],
    *,
    path: tuple[str, ...],
    description_provider: TomlDescriptionProvider | None,
) -> None:
    if description_provider is None:
        return
    description = description_provider(path)
    if not description:
        return
    for line in textwrap.wrap(str(description), width=96):
        lines.append(f"# {line}")


def _looks_like_path_key(key: str) -> bool:
    token = str(key).strip().strip("'\"").split(".")[-1].lower()
    if token in {"anchors_file", "base_config", "base_simulation_config"}:
        return True
    return any(hint in token for hint in PATH_KEY_HINTS)


def _absolutize_relative_path_values(value: Any, *, source_dir: Path, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(child_key): _absolutize_relative_path_values(
                child_value,
                source_dir=source_dir,
                key=str(child_key),
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [
            _absolutize_relative_path_values(item, source_dir=source_dir, key=key) for item in value
        ]
    if not isinstance(value, str) or not _looks_like_path_key(key):
        return value
    if value.strip() in ("", "~") or "://" in value:
        return value
    declared_path = Path(value).expanduser()
    if is_declared_absolute_path(declared_path):
        return declared_path.as_posix()
    return (source_dir / declared_path).resolve().as_posix()


def _render_toml_mapping(
    mapping: Mapping[str, Any],
    *,
    prefix: tuple[str, ...] = (),
    description_provider: TomlDescriptionProvider | None = None,
) -> list[str]:
    lines: list[str] = []
    scalar_items: list[tuple[str, Any]] = []
    nested_items: list[tuple[str, Mapping[str, Any]]] = []
    array_items: list[tuple[str, list[Mapping[str, Any]]]] = []

    for raw_key, value in mapping.items():
        key = str(raw_key)
        if isinstance(value, Mapping):
            nested_items.append((key, value))
        elif _is_mapping_list(value):
            array_items.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        _append_toml_description(
            lines,
            path=(*prefix, key),
            description_provider=description_provider,
        )
        lines.append(f"{key} = {_toml_scalar(value)}")

    for key, value in nested_items:
        if lines and lines[-1] != "":
            lines.append("")
        section = ".".join((*prefix, key))
        _append_toml_description(
            lines,
            path=(*prefix, key),
            description_provider=description_provider,
        )
        lines.append(f"[{section}]")
        lines.extend(
            _render_toml_mapping(
                value,
                prefix=(*prefix, key),
                description_provider=description_provider,
            )
        )

    for key, items in array_items:
        section = ".".join((*prefix, key))
        for item in items:
            if lines and lines[-1] != "":
                lines.append("")
            _append_toml_description(
                lines,
                path=(*prefix, key),
                description_provider=description_provider,
            )
            lines.append(f"[[{section}]]")
            lines.extend(
                _render_toml_mapping(
                    item,
                    prefix=(*prefix, key),
                    description_provider=description_provider,
                )
            )
    return lines


def _write_toml_payload(path: Path, payload: Mapping[str, Any]) -> None:
    from hydromodpy.analysis.comparison.descriptions import (
        comparison_description_for_path,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _render_toml_mapping(
        payload,
        description_provider=comparison_description_for_path,
    )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=True, indent=2) + "\n")


def _collect_fieldnames(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key in seen:
                continue
            seen.add(key)
            fieldnames.append(key)
    return fieldnames


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(_jsonable(value), ensure_ascii=True)


def _write_csv_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _collect_fieldnames(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        if not fieldnames:
            stream.write("")
            return
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
