"""Read the simulated water table at several piezometers of a finished run.

One row per piezometer in piezometers.csv (columns id, x, y, in the project CRS).
The answer is one table, one column per piezometer, one row per time step.

Run it from the project folder:

    python read_piezometers.py                      # the last completed run
    python read_piezometers.py nancon_step4_transient
"""

import sys
from pathlib import Path

import pandas as pd

import hydromodpy as hmp

HERE = Path.cwd()
RUN = sys.argv[1] if len(sys.argv) > 1 else "@last"
VARIABLE = "watertable_depth"  # depth of the water table below the ground, m

piezometers = pd.read_csv(HERE / "piezometers.csv")

cat = hmp.open(HERE)
run = cat.latest() if RUN == "@last" else cat[RUN]

frames = [
    run.probe.series(VARIABLE, x=row.x, y=row.y, label=row.id) for row in piezometers.itertuples()
]
long = pd.concat(frames, ignore_index=True)

# One column per piezometer, in the order of the file.
wide = long.pivot(index="time", columns="point", values="value")[piezometers["id"]]
print(wide.round(2).head())

out = HERE / "share" / "piezometers.csv"
out.parent.mkdir(parents=True, exist_ok=True)
wide.to_csv(out)
print(out)
