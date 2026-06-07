"""Check the MODFLOW 6 executable and local PRT support hints.

This is a lightweight environment check. It does not run a PRT model.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

PRT_TOKENS = ("PRT-DIS", "PRT-PRP", "GWF-PRT")


def _default_modflow6_home() -> Path | None:
    candidates = [
        Path.home() / ".local" / "opt" / "modflow6" / "mf6_latest",
        Path.home() / ".cache" / "hydromodpy" / "bin",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _run_mf6_version(executable: str) -> str:
    for flag in ("-v", "--version"):
        completed = subprocess.run(
            [executable, flag],
            check=False,
            capture_output=True,
            text=True,
        )
        output = (completed.stdout + completed.stderr).strip()
        if output:
            return output
    completed = subprocess.run(
        [executable],
        check=False,
        capture_output=True,
        text=True,
    )
    return (completed.stdout + completed.stderr).strip()


def _iter_text_files(root: Path):
    suffixes = {
        ".dfn",
        ".f90",
        ".md",
        ".rst",
        ".txt",
        ".nam",
        ".dis",
        ".disv",
        ".prp",
        ".fmi",
        ".mip",
        ".oc",
    }
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            yield path


def _scan_prt_hints(root: Path, max_files: int = 5000) -> tuple[list[Path], dict[str, bool]]:
    prt_paths: list[Path] = []
    token_hits = dict.fromkeys(PRT_TOKENS, False)
    for index, path in enumerate(_iter_text_files(root)):
        if index >= max_files:
            break
        rel = path.relative_to(root)
        if "prt" in str(rel).lower():
            prt_paths.append(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower = text.lower()
        for token in PRT_TOKENS:
            if token.lower() in lower:
                token_hits[token] = True
    return prt_paths[:40], token_hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modflow6-home",
        type=Path,
        default=None,
        help="MODFLOW 6 distribution root to scan for local PRT files.",
    )
    args = parser.parse_args()

    mf6 = shutil.which("mf6")
    print(f"mf6 executable: {mf6 or 'not found'}")
    if mf6:
        print("version output:")
        print(_run_mf6_version(mf6))

    root = args.modflow6_home or _default_modflow6_home()
    print(f"MODFLOW6_HOME scan root: {root or 'not found'}")
    if root is None or not root.exists():
        print("PRT local files: not checked")
        print("Note: set MODFLOW6_HOME or pass --modflow6-home to scan local files.")
        return 0 if mf6 else 1

    prt_paths, token_hits = _scan_prt_hints(root)
    print(f"PRT local files: {'found' if prt_paths else 'not found'}")
    for path in prt_paths[:20]:
        print(f"  {path}")
    print("PRT token scan:")
    for token, found in token_hits.items():
        print(f"  {token}: {'found' if found else 'not found'}")
    print("Note: final PRT validation should run a real PRT example.")
    return 0 if mf6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
