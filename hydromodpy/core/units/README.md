# core/units

This folder answers: what unit is this number in, and how is it turned into the canonical one? A bare
number is read in SI; a string such as `"0.36 m/h"` is converted. Pint loads only when needed.

## Modules, in the order a caller uses them

1. `registry.py` is the one Pint registry (`UREG`, `get_registry`) with the hydrogeological units.
2. `parse.py` and `scalar.py` parse a TOML payload or a scalar with an inline unit.
3. `quantities.py` holds one table of quantities (length, time, hydraulic conductivity, hydraulic conductance, leakance, volumetric flow, radiation). Each row reads `unit: (factor to SI, aliases)`. The generic functions `normalize_unit`, `factor_to_si`, `convert_to_si`, `convert_payload_to_si` and `parse_to_si` take the quantity name first, and the named functions (`parse_to_m`, `factor_to_m3_per_s`, `convert_payload_to_m_per_s`, and so on) fix it. `SECONDS_PER_DAY` lives here. `time.py` keeps what only time has: MODFLOW ITMUNI codes, the pandas `Timedelta` alias, `timedelta_to_seconds` and the CF time axis.
4. `types.py` has the annotated aliases that configs use: `Length`, `Area`, `Volume`, `Time`, `FlowRate`, `Velocity`, `HydraulicConductivity`, `SpecificStorage`, `SpecificYield`, `Dimensionless` and the fixed-unit variants.
5. `physical_bounds.py` is the table of physical bounds that validators consult (no negative K, no Sy above 1).
6. `labels.py` gives the axis label of a field name, so no figure hard-codes one, and `format_length_from_m`.

The udunits bridge moved to `hydromodpy/results/storage/udunits.py`.

## What other layers import from it

`solver`, `spatial`, `model`, `display`, `calibration` and `results`.

## Where to add what

- A new unit alias: `types.py`, with its canonical unit.
- A new unit of an existing quantity: one row in `QUANTITIES` in `quantities.py`. The lower-cased unit is always an alias of itself, so list only the other spellings. Write its factor again in `FACTORS` of `tests/unit/core/units/test_quantities.py`, and the property tests compare every row with pint.
- A new quantity: one entry in `QUANTITIES`, its named functions at the bottom of `quantities.py`, and their names in `__init__.py`.
- A new physical bound: `physical_bounds.py`.

The layer rules are checked by `tests/unit/architecture/`.
