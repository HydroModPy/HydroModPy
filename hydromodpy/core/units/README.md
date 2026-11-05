# core/units

This folder answers: what unit is this number in, and how is it turned into the canonical one? A bare
number is read in SI; a string such as `"0.36 m/h"` is converted. Pint loads only when needed.

## Modules, in the order a caller uses them

1. `registry.py` is the one Pint registry (`UREG`, `get_registry`) with the hydrogeological units.
2. `parse.py` and `scalar.py` parse a TOML payload or a scalar with an inline unit.
3. `length.py`, `time.py`, `hydraulic_conductivity.py`, `hydraulic_conductance.py`, `leakance.py`, `volumetric_flow.py` and `radiation.py` each convert one quantity to its SI unit (`parse_to_m`, `convert_to_seconds`, `parse_to_m_per_s`, and so on).
4. `types.py` has the annotated aliases that configs use: `Length`, `Area`, `Volume`, `Time`, `FlowRate`, `Velocity`, `HydraulicConductivity`, `SpecificStorage`, `SpecificYield`, `Dimensionless` and the fixed-unit variants.
5. `physical_bounds.py` is the table of physical bounds that validators consult (no negative K, no Sy above 1).
6. `labels.py` gives the axis label of a field name, so no figure hard-codes one.

The udunits bridge moved to `hydromodpy/results/storage/udunits.py`.

## What other layers import from it

`solver`, `spatial`, `physics`, `display`, `calibration` and `results`.

## Where to add what

- A new unit alias: `types.py`, with its canonical unit.
- A new quantity: one helper module in the style of `length.py`, then its name in `__init__.py`.
- A new physical bound: `physical_bounds.py`.

The layer rules are checked by `tests/unit/architecture/`.
