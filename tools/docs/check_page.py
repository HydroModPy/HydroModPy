"""Check documentation pages without building the site.

Usage: python -m tools.docs.check_page PAGE [PAGE ...]

For each page (Markdown or reStructuredText under docs/source):

- every ``{toml}`` or ``:toml:`` path, every ``hmp-params`` line and every
  ``hmp-resolved`` key exists in the field registry;
- every ``{doc}`` or ``:doc:`` target, every card ``:link:`` and every relative
  Markdown link points to a page that exists;
- every TOML block parses, and a block that writes a section of the file
  validates against ``HydroModPyConfig`` once merged onto ``step1_minimal.toml``
  of example 04. A block whose first line is ``# not checked: <reason>`` is
  skipped, for a block that shows a mistake on purpose;
- no French, no em dash, no wording of the mock-up.

Reads ``docs/source/_data/registry.json``, written by the last build. Exit
code 1 when a page has a problem.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import sys
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "source"
EX04 = ROOT / "examples" / "projects" / "04_streamflow_intermittence_in_transient"
SKIP_DIRS = ("_data", "_static", "_templates", "_ext")

TOML_ROLE = re.compile(r"(?:\{toml\}|:toml:)`([^`]+)`")
DOC_ROLE = re.compile(r"(?:\{doc\}|:doc:)`([^`]+)`")
CARD_LINK = re.compile(r"^\s*:link:\s*(\S+)\s*$")
MD_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(`{3,}|:{3,})\s*(\{[a-z-]+\}|[a-z]+)?\s*(.*)$")
FRENCH = re.compile(
    r"\b(le|la|les|des|une|est|pas|du|au|aux|sur|avec|pour|dans|qui|que|cette|sont|ne|par|"
    r"mais|nous|vous|ils|leur|leurs|ces|aussi|très|plus|donc)\b"
)
ACCENT = re.compile(r"[àâäçéèêëîïôöùûüÿœÀÂÇÉÈÊËÎÏÔÙÛÜ«»]")
ALLOWED_NAMES = ("Nançon", "Abhervé", "Hub'Eau", "Météo-France", "Élorn", "Gouville", "Brévilly")
BANNED = (
    "mock-up",
    "mockup",
    "maquette",
    "localhost:",
    "hmp config explain",
    "in the target",
    "In the target",
)


def docnames() -> set[str]:
    """Every page Sphinx would build, the generated ones included."""
    out = set()
    for f in SRC.rglob("*"):
        rel = f.relative_to(SRC)
        if f.suffix in (".rst", ".md") and not rel.parts[0].startswith(SKIP_DIRS):
            out.add(str(rel.with_suffix("")))
    return out


class Registry:
    def __init__(self) -> None:
        path = SRC / "_data" / "registry.json"
        if not path.exists():
            raise SystemExit(
                "docs/source/_data/registry.json is missing: build the docs once first."
            )
        data = json.loads(path.read_text())
        self.nodes: dict = data["nodes"]
        self.roots: set[str] = set(data["meta"]["roots"])

    def resolve(self, concrete: str) -> str | None:
        concrete = concrete.strip()
        if concrete in self.nodes:
            return concrete
        current = ""
        for seg in concrete.split("."):
            seg = seg.strip('"')
            for suffix in ("__append", "__delete"):
                seg = seg.removesuffix(suffix)
            cands = self.nodes.get(current, {}).get("children", [])
            nxt = f"{current}.{seg}" if current else seg
            if nxt in cands:
                current = nxt
                continue
            if self.nodes.get(current, {}).get("kind") == "map" and cands:
                current = cands[0]
                continue
            return None
        return current or None


def toml_blocks(lines: list[str], is_md: bool) -> list[tuple[int, str]]:
    """TOML code blocks of a page, with the line they start on."""
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if is_md:
            m = FENCE.match(line.strip())
            lang = (m.group(2) or "") if m else ""
            if (
                m
                and lang in ("toml", "{hmp-toml}", "{code-block}")
                and (lang != "{code-block}" or m.group(3).strip() == "toml")
            ):
                fence = m.group(1)
                body, j = [], i + 1
                while j < len(lines) and not lines[j].strip().startswith(fence):
                    body.append(lines[j])
                    j += 1
                body = [b for b in body if not re.match(r"^:[a-z-]+:", b)]
                blocks.append((i + 1, "\n".join(body)))
                i = j + 1
                continue
        elif re.match(r"^\s*\.\. code-block::\s*toml\s*$", line):
            indent = None
            body, j = [], i + 1
            while j < len(lines):
                raw = lines[j]
                if raw.strip() and indent is None:
                    if raw.lstrip().startswith(":"):
                        j += 1
                        continue
                    indent = len(raw) - len(raw.lstrip())
                if raw.strip() and indent is not None and len(raw) - len(raw.lstrip()) < indent:
                    break
                body.append(raw[indent:] if indent and len(raw) >= indent else raw.strip())
                j += 1
            blocks.append((i + 1, "\n".join(body).strip("\n")))
            i = j
            continue
        i += 1
    return blocks


STEP_FILES = sorted(p.name for p in EX04.glob("step*.toml")) + ["project.toml"]


def _short(exc: Exception, tmp: Path) -> str:
    text = " ".join(str(exc).split()).replace(str(tmp) + ": ", "").replace(str(tmp), "the block")
    return f"{type(exc).__name__}: {text[:400]}"


def validate_toml(text: str, reg: Registry) -> list[str]:
    """Problems of one TOML block: syntax, then the real loader on top of example 04.

    The block is loaded by ``HydroModPyConfig.from_toml`` on top of its own
    ``base_config`` when that file is in example 04, else on top of each file of
    the example in turn; it passes when one of them accepts it.
    """
    if text.lstrip().startswith("# not checked"):
        return []
    try:
        fragment = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [f"TOML syntax: {exc}"]
    if not any(key in reg.roots for key in fragment):
        return []
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    own = fragment.get("base_config")
    body = re.sub(r"(?m)^\s*base_config\s*=.*$", "", text)
    bases = [own] if isinstance(own, str) and (EX04 / own).exists() else STEP_FILES
    first: str | None = None
    for base in bases:
        tmp = EX04 / f".check_page_{os.getpid()}_{uuid.uuid4().hex[:8]}.toml"
        tmp.write_text(f'base_config = "{base}"\n' + body, encoding="utf-8")
        try:
            HydroModPyConfig.from_toml(tmp)
            return []
        except Exception as exc:  # noqa: BLE001 - any refusal is reported, whatever its class
            first = first or f"refused on top of {base}: {_short(exc, tmp)}"
        finally:
            tmp.unlink(missing_ok=True)
    return [first] if first else []


def check(page: Path, reg: Registry, docs: set[str]) -> list[str]:
    rel = page.resolve().relative_to(SRC)
    here = str(rel.with_suffix(""))
    base = posixpath.dirname(here)
    is_md = page.suffix == ".md"
    lines = page.read_text(encoding="utf-8").splitlines()
    problems: list[str] = []

    def where(n: int) -> str:
        return f"{rel}:{n}"

    in_code = False
    in_params = False
    titles = 0
    for n, line in enumerate(lines, start=1):
        stripped = line.strip()
        if is_md and FENCE.match(stripped):
            m = FENCE.match(stripped)
            if not in_code:
                in_code = True
                in_params = m.group(2) == "{hmp-params}"
                if (
                    m.group(2) == "{hmp-resolved}"
                    and m.group(3)
                    and reg.resolve(m.group(3)) is None
                ):
                    problems.append(f"{where(n)}: unknown key in hmp-resolved: {m.group(3)}")
            else:
                in_code = in_params = False
            continue
        if in_params and stripped and not stripped.startswith(":"):
            if reg.resolve(stripped) is None:
                problems.append(f"{where(n)}: unknown key in hmp-params: {stripped}")
            continue
        if in_code:
            continue
        if is_md and line.startswith("# "):
            titles += 1
        for m in TOML_ROLE.finditer(line):
            target = m.group(1).replace("\\|", "|").split("|")[-1]
            if reg.resolve(target) is None:
                problems.append(f"{where(n)}: unknown TOML path: {target}")
        for m in DOC_ROLE.finditer(line):
            body = m.group(1)
            mm = re.match(r"^.*?<([^<>]+)>$", body)
            target = (mm.group(1) if mm else body).split("#", 1)[0].strip()
            full = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join(base, target))
            )
            if full not in docs:
                problems.append(f"{where(n)}: link to a page that does not exist: {target}")
        cm = CARD_LINK.match(line)
        near = " ".join(lines[max(0, n - 4) : n + 3])
        if cm and ":link-type: doc" in near and not cm.group(1).startswith(("http", "#")):
            target = cm.group(1)
            full = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join(base, target))
            )
            if full not in docs and not (SRC / base / target).exists():
                problems.append(f"{where(n)}: card link to a page that does not exist: {target}")
        for m in MD_LINK.finditer(line):
            target = m.group(1)
            if target.startswith(("http", "#", "mailto:")):
                continue
            path = target.split("#", 1)[0]
            if path and not (SRC / base / path).exists():
                problems.append(f"{where(n)}: link to a file that does not exist: {target}")
        prose = re.sub(r"`[^`]*`", "", line)
        for name in ALLOWED_NAMES:
            prose = prose.replace(name, "")
        if ACCENT.search(prose) or len(FRENCH.findall(prose.lower())) >= 2:
            problems.append(f"{where(n)}: looks French: {stripped[:80]}")
        if "—" in line:
            problems.append(f"{where(n)}: em dash")
        for word in BANNED:
            if word in line:
                problems.append(f"{where(n)}: wording of the mock-up: {word}")
    for start, text in toml_blocks(lines, is_md):
        for p in validate_toml(text, reg):
            problems.append(f"{where(start)}: {p}")
    if is_md and titles != 1:
        problems.append(f"{rel}: {titles} top-level titles, expected 1")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    reg = Registry()
    docs = docnames()
    total = 0
    for arg in argv:
        page = Path(arg)
        for problem in check(page, reg, docs):
            print(problem)
            total += 1
    print(f"{total} problem(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
