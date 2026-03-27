"""Install local PlantUML and Graphviz toolchains for documentation builds."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from pathlib import Path
from urllib.request import urlretrieve
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "tools" / "vendor"
PLANTUML_DIR = VENDOR_DIR / "plantuml"
GRAPHVIZ_DIR = VENDOR_DIR / "graphviz"

PLANTUML_VERSION = "1.2026.2"
PLANTUML_JAR_SHA256 = "3cdce52133c424dea22425b947ae9d47f2167b0866dfcf99e714d4ea1689975c"
PLANTUML_JAR_URL = (
    f"https://github.com/plantuml/plantuml/releases/download/v{PLANTUML_VERSION}/plantuml.jar"
)
GRAPHVIZ_VERSION = "14.1.4"
GRAPHVIZ_ZIP_SHA256 = "5ae69797abe832fd212de417222410af3dd3d089d9b103c22f8f817cb071710a"
GRAPHVIZ_ZIP_URL = (
    "https://gitlab.com/api/v4/projects/4207231/packages/generic/"
    f"graphviz-releases/{GRAPHVIZ_VERSION}/"
    f"windows_10_cmake_Release_Graphviz-{GRAPHVIZ_VERSION}-win64.zip"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download or validate pinned PlantUML/Graphviz tooling for docs builds. "
            f"PlantUML {PLANTUML_VERSION} is fetched repo-local with SHA256 verification."
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and re-extract even when vendor files already exist.",
    )
    parser.add_argument(
        "--skip-graphviz",
        action="store_true",
        help="Install PlantUML only.",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_sha256(path: Path, expected_sha256: str, *, label: str) -> None:
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256.lower():
        raise RuntimeError(
            f"{label} checksum mismatch for {path}. "
            f"Expected {expected_sha256.lower()}, got {actual_sha256}."
        )


def _download(
    url: str,
    destination: Path,
    *,
    force: bool,
    expected_sha256: str,
    label: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        _verify_sha256(destination, expected_sha256, label=label)
        print(f"Keeping existing verified file: {destination}")
        return
    if destination.exists():
        destination.unlink()
    print(f"Downloading {url} -> {destination}")
    urlretrieve(url, destination)
    _verify_sha256(destination, expected_sha256, label=label)
    print(f"Verified {label} SHA256: {destination}")


def _install_plantuml(*, force: bool) -> Path:
    jar_path = PLANTUML_DIR / "plantuml.jar"
    _download(
        PLANTUML_JAR_URL,
        jar_path,
        force=force,
        expected_sha256=PLANTUML_JAR_SHA256,
        label=f"PlantUML {PLANTUML_VERSION}",
    )
    return jar_path


def _extract_graphviz(zip_path: Path, install_dir: Path, *, force: bool) -> Path:
    dot_path = install_dir / "bin" / "dot.exe"
    if dot_path.exists() and not force:
        print(f"Keeping existing Graphviz install: {install_dir}")
        return dot_path

    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        top_level = None
        for member in members:
            parts = Path(member.filename).parts
            if parts:
                top_level = parts[0]
                break
        for member in members:
            parts = Path(member.filename).parts
            if not parts:
                continue
            relative_parts = parts[1:] if top_level and parts[0] == top_level else parts
            if not relative_parts:
                continue
            target_path = install_dir.joinpath(*relative_parts)
            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return dot_path


def _install_graphviz(*, force: bool) -> Path:
    if os.name != "nt":
        system_dot = shutil.which("dot")
        if system_dot is None:
            raise RuntimeError(
                "Repo-local Graphviz bootstrap is only implemented for Windows. "
                "Install Graphviz on PATH or rerun with --skip-graphviz."
            )
        print(f"Using system Graphviz dot: {system_dot}")
        return Path(system_dot)

    zip_path = VENDOR_DIR / f"graphviz-{GRAPHVIZ_VERSION}-win64.zip"
    _download(
        GRAPHVIZ_ZIP_URL,
        zip_path,
        force=force,
        expected_sha256=GRAPHVIZ_ZIP_SHA256,
        label=f"Graphviz {GRAPHVIZ_VERSION} archive",
    )
    return _extract_graphviz(zip_path, GRAPHVIZ_DIR, force=force)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    jar_path = _install_plantuml(force=args.force)
    print(f"PlantUML jar ready: {jar_path}")

    if not args.skip_graphviz:
        dot_path = _install_graphviz(force=args.force)
        print(f"Graphviz dot ready: {dot_path}")
    else:
        dot_path = None

    print("Local docs tooling configured.")
    if dot_path is not None:
        print(f"GRAPHVIZ_DOT={dot_path}")
    print(f"Use PlantUML with: java -jar {jar_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
