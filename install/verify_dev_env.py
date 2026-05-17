from __future__ import annotations

import argparse
import json
import os
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

CORE_MODULES = (
    "duckdb",
    "zarr",
    "sqlalchemy",
    "xugrid",
)

DOC_MODULES = (
    "nbsphinx",
    "myst_parser",
    "sphinx_gallery",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx_togglebutton",
    "sphinx_polyversion",
    "sphinxcontrib.autodoc_pydantic",
)

TEST_MODULES = (
    "coverage",
    "jsonschema",
    "pytest",
    "pytest_cov",
    "pytest_timeout",
    "xdist",
    "yaml",
)


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _file_url_to_path(url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None

    path_text = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc != "localhost":
        path_text = f"//{parsed.netloc}{path_text}"
    if os.name == "nt" and len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
        path_text = path_text[1:]
    return Path(path_text)


def editable_root_from_distribution(
    distribution: metadata.Distribution,
) -> Path | None:
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    dir_info = payload.get("dir_info")
    if not isinstance(dir_info, dict) or not dir_info.get("editable"):
        return None

    url = payload.get("url")
    if not isinstance(url, str):
        return None
    path = _file_url_to_path(url)
    return None if path is None else _resolve(path)


def missing_modules(module_names: tuple[str, ...]) -> list[str]:
    return [module_name for module_name in module_names if find_spec(module_name) is None]


def collect_issues(
    *,
    dist_name: str,
    expected_editable_root: Path | None,
    require_docs: bool,
    require_tests: bool = False,
) -> tuple[str | None, Path | None, list[str]]:
    issues: list[str] = []
    version: str | None = None
    editable_root: Path | None = None

    try:
        distribution = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        issues.append(
            f"{dist_name!r} is not installed as a distribution in this environment. "
            "A source checkout import can mask this when the current directory is the repository root."
        )
        distribution = None
    else:
        version = distribution.version
        if expected_editable_root is not None:
            editable_root = editable_root_from_distribution(distribution)
            if editable_root is None:
                issues.append(
                    f"{dist_name!r} is installed, but not as an editable checkout with "
                    "PEP 660 direct_url metadata."
                )
            elif editable_root != expected_editable_root:
                issues.append(
                    f"{dist_name!r} is editable, but points to {editable_root} instead of "
                    f"the expected repository root {expected_editable_root}."
                )

    missing_core = missing_modules(CORE_MODULES)
    if missing_core:
        issues.append(f"Missing core runtime modules: {', '.join(missing_core)}.")

    if require_docs:
        missing_docs = missing_modules(DOC_MODULES)
        if missing_docs:
            issues.append(f"Missing docs modules: {', '.join(missing_docs)}.")

    if require_tests:
        missing_tests = missing_modules(TEST_MODULES)
        if missing_tests:
            issues.append(f"Missing test modules: {', '.join(missing_tests)}.")

    return version, editable_root, issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that a HydroModPy developer environment is fully installed."
    )
    parser.add_argument("--dist-name", default="hydromodpy")
    parser.add_argument("--expected-editable-root", default=None)
    parser.add_argument("--require-docs", action="store_true")
    parser.add_argument("--require-tests", action="store_true")
    args = parser.parse_args(argv)

    expected_root = (
        _resolve(Path(args.expected_editable_root).expanduser())
        if args.expected_editable_root
        else None
    )

    version, editable_root, issues = collect_issues(
        dist_name=args.dist_name,
        expected_editable_root=expected_root,
        require_docs=bool(args.require_docs),
        require_tests=bool(args.require_tests),
    )

    if issues:
        print("HydroModPy developer environment verification failed:")
        for issue in issues:
            print(f"  - {issue}")
        print("")
        print("Recreate or repair the environment with:")
        extras = []
        if args.require_docs:
            extras.append("docs")
        if args.require_tests:
            extras.append("test")
        if extras:
            print(f'  pip install -e ".[{",".join(extras)}]"')
        else:
            print("  pip install -e .")
        return 1

    detail = f"{args.dist_name} {version or '?'}"
    if editable_root is not None:
        detail += f" (editable root: {editable_root})"
    print(f"Verified {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
