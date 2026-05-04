from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = (
    REPO_ROOT / "tools",
    REPO_ROOT / "validation_cases",
)


def _looks_like_si_recharge_payload(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in {"mm_day_to_m_s", "_mm_day_to_m_s"}
        if isinstance(func, ast.Attribute):
            return func.attr in {"mm_day_to_m_s", "_mm_day_to_m_s"}
    if isinstance(node, ast.ListComp):
        return _looks_like_si_recharge_payload(node.elt)
    if isinstance(node, (ast.List, ast.Tuple)):
        return any(_looks_like_si_recharge_payload(item) for item in node.elts)
    if isinstance(node, ast.Name):
        name = node.id.lower()
        return "recharge" in name and name.endswith("_m_s")
    return False


def _constant_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dict_value_for_key(node: ast.Dict, key: str) -> ast.AST | None:
    for raw_key, value in zip(node.keys, node.values):
        if raw_key is not None and _constant_key(raw_key) == key:
            return value
    return None


def _has_m_per_s_units(node: ast.Dict) -> bool:
    units = _dict_value_for_key(node, "units")
    return isinstance(units, ast.Constant) and units.value == "m/s"


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        files.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(files)


def test_boussinesq_runtime_recharge_preconverted_to_si_declares_units() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            values = _dict_value_for_key(node, "values")
            if values is None or not _looks_like_si_recharge_payload(values):
                continue
            if _has_m_per_s_units(node):
                continue
            violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert not violations, (
        "Recharge payloads preconverted with mm_day_to_m_s or named *_m_s must "
        "declare units='m/s' to avoid a second Flow conversion from mm/day:\n"
        + "\n".join(violations)
    )
