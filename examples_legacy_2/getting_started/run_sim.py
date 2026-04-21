"""Getting-started example — run the Dupuit synthetic aquifer from Python.

Run it directly::

    python examples/getting_started/run_sim.py

Or use the CLI with the same TOML::

    hmp run examples/getting_started/project.toml
"""
from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp


def main() -> None:
    here = Path(__file__).resolve().parent
    config = here / "project.toml"

    result = hmp.run(config, headless=True)
    print(f"Run finished: sim_id={result.sim_id} name={result.name}")


if __name__ == "__main__":
    main()
