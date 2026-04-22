from __future__ import annotations

import datetime as dt
from pathlib import Path


PREPROC_DIAG_FILENAME = "pyhelp_preprocessing_diagnostic.txt"
WORKFLOW_DIAG_FILENAME = "pyhelp_workflow_states.txt"


def diag_path(workdir: str | Path, filename: str = PREPROC_DIAG_FILENAME) -> Path:
    return Path(workdir) / filename


def diag_reset(workdir: str | Path, filename: str = PREPROC_DIAG_FILENAME) -> Path:
    path = diag_path(workdir, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("### Diagnostic ###", encoding="utf-8")
    return path


def diag_section(workdir: str | Path, name: str, filename: str = PREPROC_DIAG_FILENAME) -> None:
    path = diag_path(workdir, filename)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n### Site {name}")


def diag_line(workdir: str | Path, key: str, value, filename: str = PREPROC_DIAG_FILENAME) -> None:
    path = diag_path(workdir, filename)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n{key}: {value}")


def diag_reset_wf(diag_dir: Path, filename: str = WORKFLOW_DIAG_FILENAME) -> Path:
    diag_dir.mkdir(parents=True, exist_ok=True)
    p = diag_dir / filename
    p.write_text("", encoding="utf-8")
    return p


def diag_line_wf(diag_file: Path, key: str, value) -> None:
    ts = dt.datetime.now().isoformat(timespec="seconds")
    with diag_file.open("a", encoding="utf-8") as f:
        f.write(f"{ts} | {key} | {value}\n")
