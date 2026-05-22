"""IO helpers, dataclasses and path utilities for compact network synthesis."""

from __future__ import annotations

import csv
import json
import os
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class InfoCard:
    title: str
    body_html: str


@dataclass(frozen=True)
class GroupSection:
    group_id: str
    title: str
    intro: str


@dataclass(frozen=True)
class SimulationMeta:
    simulation_id: str
    label: str
    group: str
    purpose: str = ""
    mesh_summary: str = ""
    short_label: str = ""


@dataclass(frozen=True)
class CompactNetworkSynthesisConfig:
    comparison_root: Path
    page_path: Path
    title: str
    intro: str
    simulations: Sequence[SimulationMeta] = ()
    group_sections: Sequence[GroupSection] = ()
    contract_cards: Sequence[InfoCard] = ()
    interpretation_cards: Sequence[InfoCard] = ()
    base_config: Path | None = None
    comparison_id: str | None = None
    context_watershed_path: Path | None = None


@dataclass
class SimulationRecord:
    meta: SimulationMeta
    simulation_label: str = ""
    solver: str = ""
    mesh_mode: str = ""
    mesh_label: str = ""
    run_info: dict[str, str] = field(default_factory=dict)
    closure: dict[str, str] = field(default_factory=dict)
    release_distance: dict[str, str] | None = None
    accumulation_distance: dict[str, str] | None = None
    release_accumulation_distance: dict[str, str] | None = None
    vector_network: dict[str, str] | None = None


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name, "")
        if value:
            return value
    return ""


def _fmt_m(value: object) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(str(value).strip()):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _fmt_ratio(value: object) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(str(value).strip()):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _parse_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _row_value(row: dict[str, str] | None, name: str) -> str:
    if row is None:
        return ""
    return row.get(name, "")


def resolve_recorded_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if os.name == "nt" and text.startswith("/mnt/") and len(text) > 7 and text[5].isalpha():
        return Path(f"{text[5].upper()}:/{text[7:]}").resolve()
    if os.name != "nt" and len(text) > 2 and text[1] == ":" and text[0].isalpha():
        drive = text[0].lower()
        tail = text[2:].replace("\\", "/").lstrip("/")
        return Path(f"/mnt/{drive}/{tail}").resolve()
    return Path(text).expanduser().resolve()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json_mapping(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    return data if isinstance(data, dict) else {}


def read_toml_mapping(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    return data if isinstance(data, dict) else {}
