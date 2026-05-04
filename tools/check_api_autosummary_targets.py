from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DOCS = ROOT / "docs" / "readthedocs" / "source" / "api"

TARGET_PATTERN = re.compile(r"^[ \t]+~?(hydromodpy\.[A-Za-z0-9_\.]+)[ \t]*$", re.M)


def _module_file(module_name: str) -> Path | None:
    parts = module_name.split(".")
    if not parts or parts[0] != "hydromodpy":
        return None
    candidate = ROOT.joinpath(*parts)
    py_file = candidate.with_suffix(".py")
    if py_file.exists():
        return py_file
    init_file = candidate / "__init__.py"
    if init_file.exists():
        return init_file
    return None


def _symbol_exists(module_name: str, symbol_name: str) -> tuple[bool, Path | None]:
    module_file = _module_file(module_name)
    if module_file is None:
        return False, None
    text = module_file.read_text(encoding="utf-8", errors="ignore")
    patterns = (
        rf"^class\s+{re.escape(symbol_name)}\b",
        rf"^def\s+{re.escape(symbol_name)}\b",
        rf"\b{re.escape(symbol_name)}\s*=",
        rf"__all__\s*=.*\b{re.escape(symbol_name)}\b",
    )
    for pattern in patterns:
        if re.search(pattern, text, re.M | re.S):
            return True, module_file
    return False, module_file


def _resolve_target(target: str) -> tuple[str, Path | None]:
    parts = target.split(".")
    for i in range(len(parts), 1, -1):
        module_name = ".".join(parts[:i])
        module_file = _module_file(module_name)
        if module_file is None:
            continue
        if i == len(parts):
            return "module-ok", module_file
        symbol_name = parts[i]
        exists, symbol_file = _symbol_exists(module_name, symbol_name)
        if exists:
            return "symbol-ok", symbol_file
        return "symbol-missing", symbol_file
    if len(parts) > 1:
        module_name = parts[0]
        module_file = _module_file(module_name)
        if module_file is not None:
            symbol_name = parts[1]
            exists, symbol_file = _symbol_exists(module_name, symbol_name)
            if exists:
                return "symbol-ok", symbol_file
            return "symbol-missing", symbol_file
    return "module-missing", None


def main() -> int:
    failures: list[tuple[str, str, str, str]] = []
    for rst_file in sorted(API_DOCS.glob("*.rst")):
        text = rst_file.read_text(encoding="utf-8", errors="ignore")
        for target in TARGET_PATTERN.findall(text):
            status, path = _resolve_target(target)
            if status not in {"module-ok", "symbol-ok"}:
                failures.append(
                    (
                        rst_file.name,
                        target,
                        status,
                        str(path) if path is not None else "",
                    )
                )

    if not failures:
        print("All API autosummary targets resolved.")
        return 0

    print("Broken API autosummary targets:")
    for rst_name, target, status, path in failures:
        suffix = f" -> {path}" if path else ""
        print(f"- {rst_name}: {target} [{status}]{suffix}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
