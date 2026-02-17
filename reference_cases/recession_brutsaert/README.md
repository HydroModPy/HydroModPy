# Recession Brutsaert Reference Case

This folder contains a compact analytical reference implementation for
groundwater recession curves, intended for development support and future
unit/non-regression tests.

## Scope

Implemented functions in `baseflow.py`:

- `compute_characteristic_time(...)`
- `simulate_baseflow(...)`
- `generate_baseflow_profile(...)`

Supported recession models:

- `solution="exponential"`
- `solution="boussinesq"`

## Inputs and Conventions

- `Q0`: initial discharge `[m^3/s]`
- `K`: hydraulic conductivity `[m/s]`
- `Sy`: specific yield `[-]`
- `b`: aquifer thickness `[m]` (required for exponential solution)
- `A`: watershed area `[m^2]`
- `L`: channel length `[m]`
- `ag`: active drainage fraction `[-]` (default `0.7`)
- `p`: linearization constant `[-]` (default `0.346`)

Time conventions:

- `t` in `simulate_baseflow` is in seconds.
- `generate_baseflow_profile` returns both seconds and days.

When one of `A` or `L` is missing, the code uses:

- `L = 1.4 * sqrt(A)`
- `A = (L / 1.4)^2`

## Source Reference (Brutsaert)

Primary scientific reference used for this analytical case:

- Brutsaert, W., and J. L. Nieber (1977),
  *Regionalized drought flow hydrographs from a mature glaciated plateau*,
  **Water Resources Research**, 13(3), 637-643.
  DOI: `10.1029/WR013i003p00637`

Local source provided for this integration:

- `C:\Users\dreuzy\Downloads\Water Resources Research - June 1977 - Brutsaert - Regionalized drought flow hydrographs from a mature glaciated plateau.pdf`

## Analytical Formulations

This implementation provides two recession laws:

- `solution="exponential"`: linear-reservoir form
- `solution="boussinesq"`: nonlinear Brutsaert-type recession

### 1) Exponential solution

Governing ODE:

```text
dQ/dt = -a Q
```

Coefficient:

```text
a = (pi^2 K p b L^2) / (Sy (ag A)^2)
```

Closed-form discharge:

```text
Q(t) = Q0 exp(-a t)
```

Characteristic time:

```text
tc = 1 / a
```

### 2) Boussinesq solution

Governing ODE:

```text
dQ/dt = -beta Q^(3/2)
```

Coefficient:

```text
beta = (4.8038 / 2) * sqrt(K) * L / (Sy (ag A)^(3/2))
```

Closed-form discharge:

```text
Q(t) = (Q0^(-1/2) + beta t)^(-2)
```

Characteristic time:

```text
tc = 1 / (beta sqrt(Q0))
```

### Geometric closure used when one descriptor is missing

```text
L = 1.4 sqrt(A)
A = (L / 1.4)^2
```

## Physical Parameter Reference

## Hydraulic Conductivity K [m/s]

Definition:

- Controls groundwater flow velocity via Darcy's law.

Typical ranges by geology:

- Clay (massive): `1e-13` to `1e-11`
- Silty clay: `1e-12` to `1e-9`
- Silt: `1e-9` to `1e-6`
- Fine sand: `1e-6` to `1e-4`
- Medium sand: `5e-6` to `5e-4`
- Coarse sand: `1e-5` to `1e-3`
- Gravel: `1e-4` to `1e-2`
- Sand-gravel mixtures: `1e-5` to `1e-2`
- Sandstone: `1e-8` to `1e-4`
- Limestone (unfractured): `1e-9` to `1e-5`
- Karst limestone: `1e-6` to `1e-2`
- Granite (unfractured): `1e-12` to `1e-9`
- Fractured granite: `1e-9` to `1e-5`
- Basalt: `1e-9` to `1e-4`
- Fractured volcanic rock: `1e-8` to `1e-3`
- Weathered rock: `1e-7` to `1e-4`

Typical watershed-scale effective range:

- `1e-6` to `1e-4` m/s

Most common modeling value:

- `1e-5` m/s

## Specific Yield Sy [-]

Definition:

- Fraction of aquifer volume that drains under gravity.
- Controls groundwater storage release.

Typical ranges by geology:

- Clay: `0.01` to `0.05`
- Silty clay: `0.03` to `0.08`
- Silt: `0.05` to `0.15`
- Fine sand: `0.10` to `0.25`
- Medium sand: `0.15` to `0.30`
- Coarse sand: `0.20` to `0.35`
- Gravel: `0.15` to `0.30`
- Sandstone: `0.05` to `0.20`
- Limestone (unfractured): `0.01` to `0.10`
- Karst limestone: `0.05` to `0.30`
- Granite (fractured): `0.01` to `0.05`
- Basalt: `0.01` to `0.10`
- Weathered rock: `0.05` to `0.20`

Typical watershed-scale effective range:

- `0.05` to `0.25`

Most common modeling value:

- `0.10` to `0.20`

## Minimal Usage

```python
from reference_cases.recession_brutsaert.baseflow import generate_baseflow_profile

t_s, t_days, q, tc = generate_baseflow_profile(
    Q0=1.0,
    K=1e-5,
    Sy=0.1,
    solution="boussinesq",
    A=10e6,
)
```
