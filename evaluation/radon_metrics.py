from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation._utils import (
    is_public_module_path,
    iter_python_files,
    module_name_from_path,
    package_name_from_path,
    parse_ast,
    resolve_repository_root,
)


try:
    from radon.complexity import cc_visit
    from radon.metrics import h_visit, mi_visit

except ImportError as exc:
    cc_visit = None
    h_visit = None
    mi_visit = None
    RADON_ERROR = exc

else:
    RADON_ERROR = None



def _halstead_to_jsonable(value: Any) -> Any:
    """
    Recursively turn radon's nested Halstead namedtuples into plain dicts
    so fields like "volume" stay addressable by name after JSON round-trip
    (otherwise a namedtuple serializes as an anonymous list of numbers).
    """

    if hasattr(value, "_asdict"):
        return {key: _halstead_to_jsonable(item) for key, item in value._asdict().items()}

    if isinstance(value, (list, tuple)):
        return [_halstead_to_jsonable(item) for item in value]

    return value


def safe_halstead(text: str) -> dict[str, Any] | None:
    """
    Convert Halstead metrics into JSON serializable data.
    Compatible with different Radon versions.
    """

    if h_visit is None:
        return None

    try:
        result = h_visit(text)

        if hasattr(result, "_asdict"):
            return _halstead_to_jsonable(result)

        return {
            "value": str(result)
        }

    except Exception as exc:
        return {
            "error": str(exc)
        }



def safe_complexity(text: str) -> list[dict[str, Any]]:
    """
    Calculate cyclomatic complexity safely.
    """

    if cc_visit is None:
        return []

    try:
        blocks = cc_visit(text)

        return [
            {
                "name": block.name,
                "complexity": block.complexity,
                "lineno": block.lineno,
                "col_offset": getattr(
                    block,
                    "col_offset",
                    None
                ),
            }
            for block in blocks
        ]

    except Exception as exc:

        return [
            {
                "error": str(exc)
            }
        ]



def safe_maintainability(text: str) -> float | None:
    """
    Calculate Maintainability Index safely.
    """

    if mi_visit is None:
        return None

    try:
        return mi_visit(
            text,
            False
        )

    except Exception:
        return None



def compute_radon_metrics(root: Path) -> dict[str, Any]:

    metrics: list[dict[str, Any]] = []


    for path in iter_python_files(root):

        try:

            text = path.read_text(
                encoding="utf-8",
                errors="ignore"
            )

        except Exception as exc:

            metrics.append(
                {
                    "path": str(path),
                    "error": str(exc)
                }
            )

            continue



        tree = parse_ast(path)


        metrics.append(
            {
                "module": module_name_from_path(
                    root,
                    path
                ),

                "package": package_name_from_path(root, path),

                "public": is_public_module_path(path),

                "path": str(path),

                "syntax_ok": tree is not None,

                "complexity": safe_complexity(
                    text
                ),

                "maintainability_index":
                    safe_maintainability(
                        text
                    ),

                "halstead":
                    safe_halstead(
                        text
                    ),
            }
        )


    return {
        "root": str(root),
        "files": metrics,
    }



def main() -> None:

    parser = argparse.ArgumentParser(
        description="Compute radon metrics for a repository"
    )


    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root"
    )


    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repository URL or path to clone"
    )


    parser.add_argument(
        "--branch",
        type=str,
        default=None,
        help="Branch to checkout"
    )


    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file"
    )


    args = parser.parse_args()



    if cc_visit is None:

        raise SystemExit(
            f"radon is required: {RADON_ERROR}"
        )



    with resolve_repository_root(
        args.root,
        args.repo,
        args.branch
    ) as root:


        result = compute_radon_metrics(root)


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