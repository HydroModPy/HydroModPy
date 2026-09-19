# hydromodpy-terrain-scipy

A second implementation of the HydroModPy terrain port, shipped as its own
distribution. HydroModPy does not name it anywhere; it finds it through the
`hydromodpy.terrain.engine` entry-point group, under the name `scipy_d8`.

```bash
pip install -e terrain_scipy
```

```jsonc
// request.json of a terrain-delineate job
{"inputs": {"engine": "scipy_d8", "dem": {"path": "dem.tif"}, "outlets": [...]}}
```

```toml
# or the project TOML, which routes the whole geographic chain through it
[geographic]
terrain_engine = "scipy_d8"
```

## What it is for

The point of the port is that an implementation can be replaced without
touching a caller. A port with one implementation never proves that, and a
second implementation living in the same tree only proves half of it: it still
gets imported by a line somebody in that tree wrote. This distribution is the
other half. It is installed beside HydroModPy, discovered by entry point, and
held to the port by
`tests/contract/test_terrain_engine_contract.py`, a file of the host that runs
every assertion it owns against whatever the registry resolves and never names
this engine.

## What it computes

D8 flow routing, in three independent pieces:

- **conditioning**: Planchon & Darboux as a vectorised descending fixed point.
  Non-seed cells start at `+inf` and are lowered to
  `max(z, nextafter(min over neighbours))` until nothing moves. The one-ULP
  epsilon leaves a plateau-free surface, so no interior cell drains nowhere.
- **accumulation**: with `M` the donor matrix of the pointer, the upstream
  count is the solution of `(I - M) a = 1`. On a conditioned surface `M` is
  nilpotent, the system is permuted unit-triangular and integer, so the solve is
  exact. A pointer holding a cycle would make it singular and is refused first,
  by a strongly-connected-components pass.
- **delineation**: one breadth-first walk of the same matrix from the snapped
  outlet.

It serves `fill` conditioning over a regional extent, `cells` and `m2` units,
`none` and `ln` transforms. Anything else is refused by name, which is what the
port asks for: `breach` in particular raises `TerrainCapabilityError` rather
than answering a breach request with a fill.

It is a reference implementation. The sparse factorisation is what bounds it:
a few hundred thousand cells is comfortable, a national DEM is not.

## Why not pysheds

The campaign that produced this distribution named it
`hydromodpy-terrain-pysheds`. Measured on 2026-09-19: `pysheds` 0.5 declares
`numpy` with no upper bound and calls `np.in1d` in nine members of its grid,
including `accumulation` and `catchment`. `np.in1d` was removed in numpy 2.0,
HydroModPy requires `numpy>=2.4.4`, and pip installs the combination without a
word. Four of the eight port members cannot run. The port needs an engine, not
a library, and this one depends on nothing HydroModPy does not already require.

## Agreement with the engines HydroModPy ships

None is owed, and none is asserted. The epsilon gradient laid inside a plateau
and the tie-breaking of the steepest-descent search are this engine's own, so
two engines are entitled to different answers on a real surface. What is owed is
the port, and that is what the conformance suite measures.
