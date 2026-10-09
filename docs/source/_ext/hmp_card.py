"""Text rendering of a parameter card, with the value an example file gives it."""

from __future__ import annotations

import json
import textwrap
import tomllib
from pathlib import Path
from typing import Any


def _resolve(state: dict[str, Any], concrete: str) -> str | None:
    nodes = state["nodes"]
    if concrete in nodes:
        return concrete
    current = ""
    for seg in concrete.split("."):
        cands = nodes.get(current, {}).get("children", [])
        nxt = f"{current}.{seg}" if current else seg
        if nxt in cands:
            current = nxt
            continue
        if nodes.get(current, {}).get("kind") == "map" and cands:
            current = cands[0]
            continue
        return None
    return current or None


def _chain(path: Path) -> list[tuple[Path, dict]]:
    """Files of a base_config chain, most derived first."""
    out = []
    while path is not None:
        data = tomllib.loads(path.read_text())
        out.append((path, data))
        base = data.get("base_config")
        path = path.parent / base if base else None
    return out


def _get(data: dict, concrete: str) -> Any:
    cur: Any = data
    for seg in concrete.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return KeyError
    return cur


def _line_of(path: Path, concrete: str) -> int | None:
    table, _, key = concrete.rpartition(".")
    current = ""
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        s = line.split("#", 1)[0].strip()
        if s.startswith("["):
            current = s.strip("[]").strip()
            continue
        if current == table and s.split("=", 1)[0].strip() == key:
            return i
    return None


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return (
        json.dumps(value, ensure_ascii=False)
        if isinstance(value, (str, list, dict))
        else str(value)
    )


def render_text(
    target: str, state: dict[str, Any], config: Path | None = None, width: int = 92
) -> str:
    canon = _resolve(state, target)
    if canon is None:
        return f"unknown path: {target}"
    n = state["nodes"][canon]
    lines: list[str] = [target]
    sub = n.get("label", "").capitalize() if n.get("pseudo") else ""
    if n.get("unit") and not (n["unit"] == "-" and not n.get("numeric")):
        sub += f"   {n['unit']}"
    rng = n.get("range") or {}
    if n.get("pseudo") and "ge" in rng and "le" in rng:
        sub += f"   valid {rng['ge']:g} .. {rng['le']:g}"
    if sub.strip():
        lines.append("  " + sub.strip())
    summary = (n.get("summary") or n.get("doc") or "").replace("`", "").replace("{toml}", "")
    lines += textwrap.wrap(summary, width - 2, initial_indent="  ", subsequent_indent="  ")
    if n.get("kind") == "leaf":
        lines.append(f"  form       {n.get('form')}")
        lines.append(f"  default    {'required' if n.get('required') else n.get('default')}")
        if n.get("literal"):
            for v in n["literal"]:
                doc = n.get("value_docs", {}).get(str(v), "")
                lines.append(f"  value      {json.dumps(v)}" + (f"  {doc}" if doc else ""))
        if n.get("calibrable"):
            c = n["calibrable"]
            lines.append(f"  calibrate  {c.get('transform')}, prior {c.get('prior')}")
        if n.get("variants") and n.get("variant_field") and not n.get("is_tag"):
            lines.append(
                f"  only if    {n['variant_field']} = {' | '.join(json.dumps(v) for v in n['variants'])}"
            )
        if n.get("profile") != "user":
            lines.append(f"  profile    {n.get('profile')}")
    else:
        kids = n.get("children", [])
        if n.get("variants_detail"):
            disc = n.get("discriminator")
            lines.append(
                f"  {disc} =     "
                + " | ".join(json.dumps(v["value"]) for v in n["variants_detail"])
            )
        if kids:
            lines.append("  fields:")
            for k in kids:
                kn = state["nodes"][k]
                if kn.get("profile") != "user":
                    continue
                if kn.get("kind") == "leaf":
                    tag = "required" if kn.get("required") else kn.get("default")
                    shapes = {str(v["value"]) for v in n.get("variants_detail", [])}
                    mine = [str(v) for v in kn.get("variants", [])]
                    if mine and not kn.get("is_tag") and set(mine) != shapes:
                        tag += f" if {kn.get('variant_field')} = " + " | ".join(
                            json.dumps(v) for v in mine
                        )
                    lines.append(f"    {kn['name']:<20} {str(kn.get('form'))[:26]:<26} {tag}")
                else:
                    lines.append(
                        f"    [{kn['name']}]"
                        + " " * max(1, 23 - len(kn["name"]))
                        + (kn.get("summary") or "")[:50]
                    )
    if config is not None and config.exists():
        chain = _chain(config)
        found = False
        if n.get("kind") == "leaf":
            for path, data in chain:
                value = _get(data, target)
                if value is not KeyError:
                    line = _line_of(path, target)
                    lines.append(
                        f"  current    {_fmt(value)}   set by {path.name}"
                        + (f":{line}" if line else "")
                    )
                    found = True
                    break
            if not found:
                lines.append(
                    f"  current    default ({n.get('default')}), no file of the chain sets it"
                )
        else:
            for path, data in chain:
                value = _get(data, target)
                if isinstance(value, dict):
                    for k, v in value.items():
                        if not isinstance(v, dict):
                            line = _line_of(path, f"{target}.{k}")
                            lines.append(
                                f"  current    {k} = {_fmt(v)}   {path.name}"
                                + (f":{line}" if line else "")
                            )
                    break
    return "\n".join(lines)
