from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation._utils import (
    classify_class,
    is_public_module_path,
    iter_python_files,
    module_name_from_path,
    package_name_from_path,
    parse_ast,
    resolve_repository_root,
)


class CBOVisitor(ast.NodeVisitor):
    def __init__(self, internal_prefixes: set[str] | None = None) -> None:
        self.classes: list[dict[str, Any]] = []

        self.current_class: str | None = None
        self.current_dependencies: set[str] = set()

        self.imports: dict[str, str] = {}
        self.internal_prefixes = internal_prefixes or set()

    def _is_internal(self, target: str) -> bool:
        # Une import relative ("from . import x") reste toujours interne au repo.
        if target.startswith("."):
            return True
        return target.split(".")[0] in self.internal_prefixes

    def visit_Import(self, node: ast.Import) -> Any:

        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]

            self.imports[name] = alias.name

        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:

        if node.module:
            module = node.module.split(".")[0]

            for alias in node.names:
                name = alias.asname or alias.name

                self.imports[name] = module

        elif node.level:
            for alias in node.names:
                name = alias.asname or alias.name

                self.imports[name] = "." * node.level + name

        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:

        previous_class = self.current_class
        previous_dependencies = self.current_dependencies

        self.current_class = node.name
        self.current_dependencies = set()

        # Analyse uniquement le contenu de la classe
        for item in node.body:
            self.visit(item)

        # retirer la classe elle-même
        self.current_dependencies.discard(node.name)

        self.classes.append(
            {
                "class": node.name,
                "kind": classify_class(node),
                "cbo": len(self.current_dependencies),
                "dependencies": sorted(self.current_dependencies),
            }
        )

        self.current_class = previous_class
        self.current_dependencies = previous_dependencies

    def visit_Call(self, node: ast.Call) -> Any:

        if self.current_class is not None:
            # Exemple : Database()
            if isinstance(node.func, ast.Name):
                name = node.func.id

                if name in self.imports and self._is_internal(self.imports[name]):
                    self.current_dependencies.add(name)

            # Exemple : obj.save()
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    obj = node.func.value.id

                    if obj in self.imports and self._is_internal(self.imports[obj]):
                        self.current_dependencies.add(obj)

        self.generic_visit(node)


def compute_cbo(root: Path) -> dict[str, Any]:

    rows: list[dict[str, Any]] = []

    paths = list(iter_python_files(root))

    internal_prefixes = {module_name_from_path(root, path).split(".")[0] for path in paths}

    for path in paths:
        tree = parse_ast(path)

        classes = []

        if tree is not None:
            visitor = CBOVisitor(internal_prefixes)

            visitor.visit(tree)

            classes = visitor.classes

        rows.append(
            {
                "module": module_name_from_path(root, path),
                "package": package_name_from_path(root, path),
                "public": is_public_module_path(path),
                "path": str(path),
                "classes": classes,
            }
        )


    _annotate_afferent_coupling(rows)


    return {
        "root": str(root),
        "files": rows,
    }


def _annotate_afferent_coupling(rows: list[dict[str, Any]]) -> None:
    """Add afferent coupling (Ca) next to the existing efferent one (Ce, the "cbo" field).

    Ce counts how many other names a class depends on (outgoing). Ca counts
    the opposite direction: how many other classes in the repository depend
    on this one (incoming). A facade is expected to have a high Ce and a low
    Ca -- it exists precisely so other classes only depend on it instead of
    on everything it coordinates. A class with both Ce and Ca high is a
    stronger signal of a real coupling problem than either number alone.
    """

    all_class_names = {
        cls["class"] for file_row in rows for cls in file_row["classes"]
    }
    afferent_sources: dict[str, set[str]] = {name: set() for name in all_class_names}

    for file_row in rows:
        for cls in file_row["classes"]:
            source_name = cls["class"]
            for dependency in cls["dependencies"]:
                if dependency in afferent_sources and dependency != source_name:
                    afferent_sources[dependency].add(source_name)

    for file_row in rows:
        for cls in file_row["classes"]:
            cls["efferent_coupling"] = cls["cbo"]
            sources = afferent_sources.get(cls["class"], set())
            cls["afferent_coupling"] = len(sources)
            cls["afferent_sources"] = sorted(sources)
            denominator = cls["efferent_coupling"] + cls["afferent_coupling"]
            cls["instability"] = (
                cls["efferent_coupling"] / denominator if denominator else None
            )


def compute_package_coupling(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate class-level Ce/Ca into Martin's original package-level Ca/Ce/I.

    Martin (2002) defines, for a package P: Ce(P) = number of *distinct*
    external classes that a class inside P depends on; Ca(P) = number of
    *distinct* external classes that depend on a class inside P. This is a
    count of distinct external classes, not a sum of per-class Ce/Ca (which
    would double-count a shared external dependency/dependent across several
    classes in the same package). Coupling between two classes that are both
    inside P does not count towards either number.
    """

    class_to_package: dict[str, str] = {}
    for file_row in data.get("files", []):
        package = file_row.get("package", "")
        for cls in file_row.get("classes", []):
            class_to_package[cls["class"]] = package

    packages = sorted(set(class_to_package.values()))
    efferent_targets: dict[str, set[str]] = {package: set() for package in packages}
    afferent_sources: dict[str, set[str]] = {package: set() for package in packages}

    for file_row in data.get("files", []):
        package = file_row.get("package", "")
        for cls in file_row.get("classes", []):
            for dependency in cls.get("dependencies", []):
                dependency_package = class_to_package.get(dependency)
                if dependency_package is not None and dependency_package != package:
                    efferent_targets[package].add(dependency)
            for source in cls.get("afferent_sources", []):
                source_package = class_to_package.get(source)
                if source_package is not None and source_package != package:
                    afferent_sources[package].add(source)

    rows: list[dict[str, Any]] = []
    for package in packages:
        ce = len(efferent_targets[package])
        ca = len(afferent_sources[package])
        denominator = ce + ca
        rows.append(
            {
                "package": package,
                "efferent_coupling": ce,
                "afferent_coupling": ca,
                "instability": ce / denominator if denominator else None,
            }
        )
    return rows


def main() -> None:

    parser = argparse.ArgumentParser(description="Compute class coupling metrics (CBO)")

    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")

    parser.add_argument("--repo", type=str, default=None, help="Repository URL or path to clone")

    parser.add_argument("--branch", type=str, default=None, help="Branch to checkout")

    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")

    args = parser.parse_args()

    with resolve_repository_root(args.root, args.repo, args.branch) as root:
        result = compute_cbo(root)
        result["package_coupling"] = compute_package_coupling(result)


        output = json.dumps(
            result,
            indent=2
        )


        if args.output is None:
            print(output)

        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)

            args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
