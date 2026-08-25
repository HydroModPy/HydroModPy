# Metrics reference

This document details every metric computed by the scripts in `evaluation/`:
the exact formula, what it means, how to read it, and — where relevant —
the limitations we ran into while using it on this specific codebase. For
"how do I run script X", see [README.md](README.md); this document is the
"what does the number actually mean" reference.

## Contents

- [Complexity — `radon_metrics.py`](#complexity--radon_metricspy)
- [Coupling (CBO, efferent/afferent) — `coupling.py`](#coupling-cbo-efferentafferent--couplingpy)
- [Cohesion (LCOM) — `cohesion.py`](#cohesion-lcom--cohesionpy)
- [Class `kind` classification — `_utils.py`](#class-kind-classification--_utilspy)
- [Duplication — `duplication.py`](#duplication--duplicationpy)
- [Reliability — `reliability.py`](#reliability--reliabilitypy)
- [Architecture / dependency graph — `extract_architecture.py`](#architecture--dependency-graph--extract_architecturepy)
- [Known limitations, in one place](#known-limitations-in-one-place)

---

## Complexity — `radon_metrics.py`

Three separate numbers, computed per function/method (Cyclomatic Complexity)
or per file (Maintainability Index, Halstead), via the `radon` library.

### Cyclomatic Complexity (CC)

McCabe's 1976 metric: start at 1, add 1 for every branch point (`if`,
`elif`, `for`, `while`, `and`/`or` in a condition, `except`, comprehension
`if` clauses...). It is exactly "how many independent paths through this
function".

| Score | Rank | Meaning |
|---|---|---|
| 1–5 | A | simple block |
| 6–10 | B | well structured, stable |
| 11–20 | C | moderate risk |
| 21–30 | D | more than moderate risk |
| 31–40 | E | high risk, alarming |
| 41+ | F | very high risk, error-prone |

Ranking source: `radon.complexity.cc_rank`.

**What we found using it**: this metric was the most reliable one this
session. The five files we refactored (`audit_engine.py`,
`budget.py`, `observables.py`, `visuals_payloads.py`,
`network_transient_html.py`) all had a rank-F function (43, 54, 31, 29, 27).
After Extract Method (splitting the branches into named helper functions,
without changing a single line of the branch bodies), every one of them
dropped substantially (e.g. 43 → 18), and the total complexity of the file
stayed *exactly* conserved (152 → 152) — confirming the refactor moved
logic around without adding or removing any of it.

### Maintainability Index (MI)

```
MI = min(max(0, (171 − 5.2·ln(V) − 0.23·G − 16.2·ln(L) + 50·sin(√(2.46·radians(C)))) × 100 / 171), 100)
```

- `V` — Halstead Volume (see below), of the whole file.
- `G` — total Cyclomatic Complexity of the file (sum across all functions).
- `L` — LLOC (logical lines of code) of the file.
- `C` — percentage of comment lines, **including multi-line strings /
  docstrings** (`raw.comments + raw.multi`, relative to SLOC, ×100).

Rank: **A** if MI > 19, **B** if 9 < MI ≤ 19, **C** if MI ≤ 9 (`radon.metrics.mi_rank`).
Source: `radon.metrics.mi_compute` / `mi_parameters`.

**What we found using it — an important caveat**: MI penalizes total
**LOC** on a log scale, so a large file can never reach a high MI
regardless of how well it is organized — the metric conflates "big" with
"unmaintainable". Worse, we measured directly that **Extract Method can
make the file-level MI score go down slightly even when it strictly
improves the code**: splitting one 43-CC function into four smaller ones
kept total complexity exactly flat (152 → 152, since decision points were
only moved, not added), but added a handful of new `def ...` lines and
short one-line docstrings without adding comments in proportion — and
because docstrings count as "comments" in the `C` term above, the comment
*ratio* dropped slightly, which (through the `sin` term) nudged MI down by
a fraction of a point. **The function-level Cyclomatic Complexity is the
number to trust when judging a specific refactor; file-level MI is better
read as a rough, holistic signal and is not reliable move-by-move.**

### Halstead metrics

Derived from counting distinct/total operators and operands in the code:

- `n1`, `n2` — number of distinct operators / operands.
- `N1`, `N2` — total operators / operands.
- Vocabulary `n = n1 + n2`, Length `N = N1 + N2`.
- **Volume** `V = N × log2(n)` — the number this repo's MI formula consumes.
- Difficulty, Effort, Time, Bugs — derived from Volume/vocabulary; not
  currently surfaced by our charts, but present in `radon.json`/`radon.csv`
  per file (`halstead.total.{h1,h2,n1,n2,vocabulary,length,volume,difficulty,effort,time,bugs}`).

`radon_metrics.py`'s `safe_halstead()` recursively converts radon's nested
`HalsteadReport`/`Halstead` namedtuples to plain dicts before serializing —
without that conversion, a namedtuple serializes to JSON as an anonymous
list of 12 numbers, silently losing the field names (this was a real bug we
found and fixed this session: `compare_repositories.py`'s Halstead average
was reading `halstead["volume"]` directly and always got `None`, because
the real path is `halstead["total"]["volume"]`).

---

## Coupling (CBO, efferent/afferent) — `coupling.py`

**Efferent coupling (Ce)** — the historic `cbo` field. For each class,
walk its method bodies and collect every `Name()` call or `obj.method()`
call where the name resolves (via that file's imports) to something
*internal to the repository* (external/stdlib imports such as `numpy` or
`pandas` are excluded — see below). `Ce = len(that set)`.

**Afferent coupling (Ca)** — the reverse direction, computed in a second
pass over the whole repository once every class's Ce is known: for class
`X`, `Ca` = how many *other* classes list `X` in their own dependency set.

Both numbers are exported per class: `efferent_coupling`, `afferent_coupling`,
`afferent_sources` (the actual list of calling classes), plus the original
`cbo`/`dependencies` fields kept for backward compatibility.

**Why both directions matter**: a class that legitimately coordinates many
collaborators (a Facade/orchestrator) is *expected* to have a high Ce — that
is the whole point of the pattern, it exists so that other code doesn't
have to depend on everything it depends on. Such a class should have a
**low** Ca (few things call it directly; it's the endpoint, not a hub).
A class with **both** Ce and Ca high is the stronger signal: many things
call it *and* it depends on many things — a real central-point-of-failure,
not just a facade doing its job. This is the reasoning behind the
`coupling_afferent_vs_efferent.png` chart.

**Internal vs external dependencies**: `compute_cbo()` first scans every
file in the target root to build the set of top-level package names that
exist in-tree (`internal_prefixes`), then only counts a call as coupling if
the imported name's top-level segment is in that set (or the import is
relative, `from . import x`, which is always internal). This was a fix made
this session — before it, calling `np.mean()` or `xr.open_dataset()` was
counted exactly like calling an internal class, so any file using
numpy/xarray/pandas heavily got an inflated CBO that had nothing to do with
real architectural coupling.

**What we found using it**: on `hydromodpy`, three classes with high raw
CBO (`Boussinesq` Ce=23, `Modflow6` Ce=21, `TestbedLauncher` Ce=21) looked
alarming at first. Checking Ca settled it: all three sit at Ca=0–1. Two of
them (`Boussinesq`, `Modflow6`) are also tagged `kind="facade"`/documented
in their own module docstring as a deliberate "lifecycle facade" — the high
Ce is the pattern working as intended, not a design problem. The one class
that stood out on *both* axes was `SimulationCatalog` (Ce=9, Ca=5) — a
legitimate "worth a look" hub, unlike the other three.

---

## Cohesion (LCOM) — `cohesion.py`

LCOM1-style calculation. For a class with methods `m1..mn`, look at the set
of `self.x` attributes each method touches. For every pair of methods,
count it as **disjoint** if the two methods' attribute sets don't overlap,
or **shared** if they do.

```
LCOM = disjoint_pairs / (disjoint_pairs + shared_pairs)
```

`0` = every pair of methods shares state (maximally cohesive); `1` = no
pair shares anything (methods are behaviorally unrelated, bundled in the
same class for no state-sharing reason).

**`None` handling** — this is the metric we changed the most this session.
`lcom()` returns `None` (not a possibly-misleading `0.0`) whenever:

- the class has fewer than 2 methods (nothing to compare pairwise), **or**
- `kind != "business-logic"` (see classification below) — a dataclass,
  Pydantic model, `Protocol`, `Mixin`, or thin facade is *allowed* to bundle
  independent members by construction; LCOM does not mean the same thing
  for them as it does for a hand-written business-logic class.

**What we found using it**: of 705 classes on `hydromodpy`, 201 originally
showed LCOM > 0.8 ("low cohesion"). After excluding everything that wasn't
`kind="business-logic"`, only 65 remained as plausible candidates — and
spot-checking those by hand, essentially all of them turned out to be
*more* facades/adapters/mixins that our name-based heuristics hadn't
caught yet (e.g. `GeologyDataIO`, docstring: *"Concrete `GeologyDataSource`
backed by..."*, 4 independent delegating methods by design). We did not
find a single confirmed real cohesion problem on this codebase after
checking the actual code — see
[Known limitations](#known-limitations-in-one-place).

---

## Class `kind` classification — `_utils.py`

`classify_class()` (used by both `coupling.py` and `cohesion.py`) inspects
a class's AST and returns one of:

| `kind` | Detected as |
|---|---|
| `dataclass` | `@dataclass` decorator |
| `model` | inherits `BaseModel` or `NamedTuple` |
| `protocol` | inherits `Protocol`, **or** every method body is a trivial stub (`...`, `pass`, docstring only, or a bare `raise`) |
| `mixin` | class name ends with `Mixin` |
| `facade` | every method except `__init__`/`__post_init__` is *only* a single delegating statement (`return other_call(...)` or `other_call(...)`), local `import`/`from ... import` lines tolerated before it |
| `business-logic` | anything else (the default) |

This exists because a raw CBO or LCOM number means something different
depending on which of these a class is — see the caveats in the coupling
and cohesion sections above. **Always read `kind` before ranking a class
as a "worst offender."**

---

## Duplication — `duplication.py`

Neither CBO nor LCOM can see this: two functions/methods implementing
nearly identical logic score fine on both. `duplication.py` hashes a
*normalized* signature of every function/method body (skipping ones with
fewer than `--min-statements`, default 5, to avoid noise from trivial
one-liners):

1. Parse the function body into a synthetic module (its statements only).
2. Rename every local variable and parameter to a positional placeholder
   (`_v0`, `_v1`, ...) — consistently within that one function — via an
   `ast.NodeTransformer`. `self`/`cls` and dunder names are left untouched.
3. `ast.unparse()` the result — this also normalizes formatting/whitespace
   differences for free.
4. SHA-256 the resulting text; group functions sharing a hash.

Two functions differing only by variable names, argument names, or
formatting hash identically and are reported as one group. Groups of size
1 (no duplicate found) are dropped.

**What this does *not* catch**: whole-function matching only — a
duplicated 10-line block sitting inside two otherwise-different 40-line
functions will not be detected (unlike SonarQube's clone detector, which
can match partial blocks). See
[Known limitations](#known-limitations-in-one-place).

**What we found using it**: on `hydromodpy`, the `__getattr__` lazy-import
shim is duplicated identically 16 times across different `__init__.py`
files; `_resolve_zarr_path` and `_get_nested_section` 4 times each;
`_jsonable` 3 times across the Boussinesq diagnostics modules. All
concrete, actionable extraction candidates that CBO/LCOM never surfaced.

---

## Reliability — `reliability.py`

This is **not** a from-scratch bug detector — re-deriving SonarQube's
proprietary rule engine (years of refinement across languages) from
scratch would just produce a worse version of an existing, mature tool.
Instead, `reliability.py` runs `ruff check <root> --output-format json`
**without overriding** `--select`/`--ignore`, so it keeps respecting the
project's own `[tool.ruff.lint]` configuration in `pyproject.toml`
(including deliberate per-file exceptions, e.g. the `B008` tolerance for
Pydantic `Field(...)` defaults) — then filters the resulting violations,
in Python, to the two rule families that target likely-bug patterns rather
than style:

- **`F`** — pyflakes (undefined names, unused variables, redefinitions...)
- **`B`** — flake8-bugbear (mutable default arguments, loop-variable
  closures, bare `except`, and other well-known Python footguns)

### Severity and rating

A small, explicit, hand-picked set of codes is treated as `"high"` severity
(likely to actually crash or silently produce a wrong result at runtime):
`F821` (undefined name), `F823` (used before assignment), `F811`
(redefinition — can silently shadow real logic), `F706`/`F707` (control
flow errors), `B023` (closure captures a loop variable — classic
late-binding bug), `B006` (mutable default argument). Every other F/B code
is `"medium"`; anything else would be `"low"` (not currently reachable,
since only F/B codes are kept).

```
rating = "E" if high >= 5
         "D" if high > 0
         "C" if medium > 20
         "B" if medium > 0
         "A" otherwise
```

**This rating is our own simple heuristic**, only loosely in the spirit of
SonarQube's A–E — it is not a reproduction of their (undisclosed) formula.

**What we found using it**: on the whole repository, only 2 real F/B
violations (both pre-existing, both minor — a `B904` "raise without from"
and a `B007` unused loop variable) → rating B. Using `--select F,B` as a
raw CLI override instead (ignoring the project's own config) would have
falsely surfaced 6, including violations in files the project's
`per-file-ignores` deliberately exempts (`tests/`, `hydromodpy_annex/`).

---

## Architecture / dependency graph — `extract_architecture.py`

Walks every file, records per-module `internal_dependencies` /
`external_dependencies` (via the same import-resolution approach as
`coupling.py`), and can render the result as a graph.

**Aggregation** — drawing one node per *module* is unreadable past a few
dozen files (we measured this directly: the raw module graph for
`hydromodpy`, ~2500 modules, renders as an illegible hairball). Image
exports (`architecture_graph.png`, `architecture_package_graph.png`/
`architecture_package_heatmap.png` in `generate_report.py`) therefore
collapse modules to *packages* first (`aggregate_graph_to_packages()` /
`build_package_dependency_frame()`), controlled by `--package-depth`
(how many dotted segments define a "package") and a top-N node cap.
GraphML/JSON exports keep full module-level detail, since those are meant
for external tools, not direct viewing.

**Cycle detection** — `dependency_cycles_text()` computes the graph's
strongly connected components (Tarjan's algorithm via `networkx`, O(V+E));
any component with more than one node is a genuine import cycle between
those packages. This is annotated directly on `architecture_package_graph.png`
when found. We found none on `hydromodpy`.

---

## Known limitations, in one place

Metrics are indicators, not verdicts. What we learned by hand-checking this
session, so the next reader doesn't have to re-discover it:

- **MI is not reliable move-by-move** (see the Extract Method example
  above) and structurally cannot score a large-but-well-organized file
  highly. Trust function-level Cyclomatic Complexity for judging a specific
  refactor instead.
- **LCOM and raw CBO mean different things depending on `kind`.** On this
  codebase specifically, checking every "worst offender" by hand
  (`CalibrationSession`, `Modflow6`, `Boussinesq`, `TestbedLauncher`,
  `GeologyDataIO`, `Sim2MeteoFranceClient`...) turned out to be a documented,
  intentional pattern (dataclass result container, Protocol adapter, thin
  facade, mixin) every single time. **Always open the file before acting
  on a ranking** — this is not optional on a codebase this deliberately
  patterned.
- **Duplication detection is whole-function only** — no partial-block
  matching, unlike a mature clone detector.
- **`reliability.py` is not SonarQube.** It reuses two of Ruff's rule
  families as a proxy for the same idea; it does not cover security
  vulnerabilities, does not have SonarQube's breadth of bug patterns, and
  its A–E rating is our own simple heuristic, not theirs.
- **Analyzing a subfolder in isolation loses cross-boundary signal.** CBO's
  internal/external split and the package dependency graph are both
  computed from whatever `--root` you pass; pointing `--root` at a
  subfolder of a larger package (rather than the package root) can make
  genuinely-internal imports look external, and hides edges to modules
  outside that subfolder. Point `--root` at the actual package root
  whenever possible (e.g. `hydromodpy/`, not `hydromodpy/solver/`).
