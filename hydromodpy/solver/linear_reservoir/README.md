# Linear reservoir backend

A global flow model. One cell takes the whole catchment, and the solve reads the `Model` and its own options table and nothing else. It is the smallest backend of the solver port of `solver/base`, and the port tests run on it like on the others.

## What it receives and returns

`build` receives the frozen `Model` on the one-cell mesh of the `catchment` engine and the `LinearReservoirOptions` of `[solver.linear_reservoir]`, whose time constant reads a bare number of days or a string with its unit. The state is the depth of water on the cell. One piece of constant rate advances by the closed form `tau * r + (s - tau * r) * exp(-dur / tau)`, never by a substep, so the mass of the run closes to the arithmetic of one exponential. The extractor writes one discharge and one reservoir storage per period at the station of the whole catchment, and the budget rows of recharge, drain and storage at the domain zone.

## What it declares

`name = "linear_reservoir"`, `process_type = "flow"`, `accepted_meshes = {"catchment"}`, `geometry = "cells"`, `category = "lumped"`, `writes = ("discharge", "reservoir_storage", "budgets")`, `supports = {"recharge", "steady_start"}`, no `native_step`, an empty `mutable` and no `requires`. The calibration of a site walks its time constant in the log space.

## How it registers and what it refuses

It is the built-in path `flow_linear_reservoir` of `_BUILTIN_PATHS` in `solver/base/registry.py`, with its extractor under the same key. A `[mesh]` with no engine line meets it, and a mesh of more than one cell is refused. A file that asks for a trait outside `supports` is refused when it is read. `tests/ports/test_solver.py` holds it to the port.
