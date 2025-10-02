# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Created on Wed Jun 11 20:18:07 2025

@author: mathi
"""
"""
help_example_cli.py – Runs help_example.py in a given workdir

- Ensures required input files are present (grid, climate CSVs, observed river flow)
- Calls help_example.py using subprocess
- Prints the location of the resulting daily CSV output
"""

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path
import subprocess, sys, textwrap

p = argparse.ArgumentParser(prog="help_example_cli")
p.add_argument("--workdir", required=True, help="Dossier de travail temporaire")
p.add_argument("--grid_csv", required=True)
p.add_argument("--precip", required=True)
p.add_argument("--tair", required=True)
p.add_argument("--solrad", required=True)
args = p.parse_args()

workdir = Path(os.environ.get("PYHELP_WORKDIR", args.workdir)).expanduser()
workdir.mkdir(parents=True, exist_ok=True)

obs_csv = workdir.parents[2] / "obs_yearly_river_flow_urse.csv"

if not obs_csv.exists():
    raise FileNotFoundError(f"observation flow file not found: {obs_csv}")
    #with open(obs_csv, "w", newline="") as f:
        #csv.writer(f).writerow(["year", "flow"])

# help_example.py execution
help_example_path = Path(
    os.environ.get("PYHELP_HELP_EXAMPLE",
                   Path(__file__).with_name("help_example.py"))
).resolve()

subprocess.check_call(
    [sys.executable, str(help_example_path),
     "--workdir", str(workdir)]
)

daily_src = workdir / "help_example_daily_mean.csv"

print("PyHELP simulation over.")
print(f"[INFO] File created : {daily_src}")



