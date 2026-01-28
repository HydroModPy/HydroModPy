# -*- coding: utf-8 -*-
"""
Created on Thu Jan  8 15:24:44 2026

@author: pelissierm
"""

from pathlib import Path
import datetime as dt

def diag_reset(diag_dir: Path, filename: str = "pyhelp_workflow_states.txt"):
    diag_dir.mkdir(parents=True, exist_ok=True)
    p = diag_dir / filename
    p.write_text("", encoding="utf-8")
    return p

def diag_line(diag_file: Path, key: str, value):
    ts = dt.datetime.now().isoformat(timespec="seconds")
    with diag_file.open("a", encoding="utf-8") as f:
        f.write(f"{ts} | {key} | {value}\n")