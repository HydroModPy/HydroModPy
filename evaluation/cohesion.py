from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation._utils import (
    iter_python_files,
    module_name_from_path,
    parse_ast,
    resolve_repository_root,
)


@dataclass(slots=True)
class ClassCohesion:
    name: str
    module: str
    methods: set[str] = field(default_factory=set)
    attributes_by_method: dict[str, set[str]] = field(default_factory=dict)

    def lcom(self) -> float:
        """
        Simple LCOM calculation:
        0 = high cohesion
        1 = low cohesion
        """

        methods = list(self.attributes_by_method)

        if len(methods) < 2:
            return 0.0

        disjoint = 0
        shared = 0

        for index, left in enumerate(methods):

            left_attrs = self.attributes_by_method[left]

            for right in methods[index + 1:]:

                right_attrs = self.attributes_by_method[right]

                if left_attrs.isdisjoint(right_attrs):
                    disjoint += 1
                else:
                    shared += 1

        total = disjoint + shared

        return disjoint / total if total else 0.0



class CohesionVisitor(ast.NodeVisitor):

    def __init__(self, module: str) -> None:
        self.module = module
        self.classes: list[ClassCohesion] = []

        self.current_class: ClassCohesion | None = None
        self.current_method: str | None = None


    def visit_ClassDef(self, node: ast.ClassDef) -> Any:

        previous_class = self.current_class
        previous_method = self.current_method

        class_info = ClassCohesion(
            name=node.name,
            module=self.module
        )

        self.current_class = class_info
        self.current_method = None

        for item in node.body:
            self.visit(item)

        self.classes.append(class_info)

        self.current_class = previous_class
        self.current_method = previous_method



    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:

        if self.current_class is None:
            return

        # évite les fonctions imbriquées
        if self.current_method is not None:
            return

        self.current_class.methods.add(node.name)

        previous_method = self.current_method

        self.current_method = node.name

        self.current_class.attributes_by_method.setdefault(
            node.name,
            set()
        )

        for stmt in node.body:
            self.visit(stmt)

        self.current_method = previous_method



    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef
    ) -> Any:

        self.visit_FunctionDef(node)  # type: ignore[arg-type]



    def visit_Attribute(self, node: ast.Attribute) -> Any:

        if (
            self.current_class is not None
            and self.current_method is not None
        ):

            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "self"
            ):

                self.current_class.attributes_by_method[
                    self.current_method
                ].add(node.attr)

        self.generic_visit(node)



def compute_cohesion(root: Path) -> dict[str, Any]:

    rows: list[dict[str, Any]] = []

    for path in iter_python_files(root):

        tree = parse_ast(path)

        classes = []

        if tree is not None:

            visitor = CohesionVisitor(
                module_name_from_path(root, path)
            )

            visitor.visit(tree)

            for class_info in visitor.classes:

                classes.append(
                    {
                        "class": class_info.name,
                        "module": class_info.module,
                        "methods": sorted(class_info.methods),
                        "lcom": class_info.lcom(),
                    }
                )

        rows.append(
            {
                "path": str(path),
                "classes": classes,
            }
        )

    return {
        "root": str(root),
        "files": rows,
    }



def main() -> None:

    parser = argparse.ArgumentParser(
        description="Compute cohesion metrics for a repository"
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd()
    )

    parser.add_argument(
        "--repo",
        type=str,
        default=None
    )

    parser.add_argument(
        "--branch",
        type=str,
        default=None
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None
    )

    args = parser.parse_args()


    with resolve_repository_root(
        args.root,
        args.repo,
        args.branch
    ) as root:

        result = compute_cohesion(root)

        output = json.dumps(
            result,
            indent=2
        )

        if args.output is None:
            print(output)

        else:
            args.output.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            args.output.write_text(
                output,
                encoding="utf-8"
            )



if __name__ == "__main__":
    main()