"""The analytical validation cases, as records a benchmark can loop over.

One record per ``validation_cases/analytical/<regime>/<case>/`` folder that holds a
``metadata.toml`` and a ``run_case.py``: its slug, title, regime and dimension, the
solver variants its ``[config_files]`` table declares, and the comparison function
its ``run_case`` module exposes (the one ``run_*_comparison`` callable).
"""

from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_ORDER = (
    "modflow_nwt",
    "modflow6",
    "modflow6_irregular_tri",
    "modflow6_voronoi",
    "boussinesq",
    "boussinesq_local",
)


@dataclass(frozen=True, slots=True)
class CaseRecord:
    """One analytical validation case and the function that runs its comparison."""

    slug: str
    title: str
    regime: str
    dimension: str
    solver_variants: tuple[str, ...]
    run_case_module: str
    comparison_function_name: str

    def comparison_runner(self):
        """The ``run_*_comparison`` function of the case."""
        return getattr(importlib.import_module(self.run_case_module), self.comparison_function_name)


def _title(case_dir: Path) -> str:
    readme = case_dir / "README.md"
    if readme.exists():
        for line in readme.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return case_dir.name


def _comparison_function(module_name: str) -> str:
    module = importlib.import_module(module_name)
    names = sorted(
        name
        for name, obj in vars(module).items()
        if callable(obj) and name.startswith("run_") and name.endswith("_comparison")
    )
    if len(names) != 1:
        raise RuntimeError(
            f"{module_name} must expose one run_*_comparison function, found {names}."
        )
    return names[0]


def discover_case_records(repo_root: Path | None = None) -> tuple[CaseRecord, ...]:
    """Every analytical case with a ``run_case.py``, sorted by slug."""
    root = repo_root or REPO_ROOT
    rank = {name: index for index, name in enumerate(SOLVER_ORDER)}
    records = []
    for metadata_path in sorted((root / "validation_cases" / "analytical").rglob("metadata.toml")):
        case_dir = metadata_path.parent
        if not (case_dir / "run_case.py").exists():
            continue
        metadata = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
        variants = tuple(
            sorted(metadata.get("config_files", {}), key=lambda s: (rank.get(s, 999), s))
        )
        module_name = ".".join(case_dir.relative_to(root).parts) + ".run_case"
        records.append(
            CaseRecord(
                slug=case_dir.name,
                title=_title(case_dir),
                regime=str(metadata.get("regime", "")),
                dimension=str(metadata.get("dimension", "")),
                solver_variants=variants,
                run_case_module=module_name,
                comparison_function_name=_comparison_function(module_name),
            )
        )
    return tuple(sorted(records, key=lambda r: r.slug))
