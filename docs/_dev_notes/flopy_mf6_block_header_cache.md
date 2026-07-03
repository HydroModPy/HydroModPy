# FloPy MF6 block-header bookkeeping: O(nper^2) hotspot and the HydroModPy cache patch

- Date: 2026-06-11
- FloPy version analyzed: 3.10.0 (pin in `pyproject.toml`: `flopy>=3.10.0,<4`)
- Patch: `hydromodpy/solver/modflow6/flopy_header_cache.py`
- Tests: `tests/unit/solver/test_modflow6_flopy_header_cache.py`
- Purpose of this note: full record of the diagnosis, the fix, and everything
  needed to turn it into an upstream FloPy pull request.

## 1. Symptom

Profiling a 19-year daily MODFLOW 6 chronicle (project `19_cheze_reservoir`,
`project_chronicle.toml`, nper = 6940, pyinstrument, wall 22 min) showed that
FloPy spends ~5 minutes of pure Python bookkeeping around a 12.5-minute solve:

| Block | Time | Dominant frames |
|---|---|---|
| `flopy run_simulation` (mf6 binary) | 746 s | `BufferedReader.readline` (waiting on the solver process) |
| `flopy write_simulation` | 181 s | `_add_missing_block_headers` 114 s, `header_exists` |
| flopy package construction (`ModflowGwfrcha.__init__`, ...) | 125 s | `_build_repeating_header` -> `header_exists` ~105 s |

Cumulative self-time across the whole profile: `header_exists` 226 s,
`get_transient_key` 213 s. The cost grows quadratically with the number of
stress periods, so it explodes exactly on long daily chronicles.

## 2. Root cause (flopy 3.10.0 line references)

All line numbers refer to `flopy/mf6/mfpackage.py` unless stated otherwise.

1. Package construction with a `{kper: data}` dict calls
   `MFBlock._build_repeating_header` once per provided period (line 670 via
   `add_dataset`, lines 650-666).
2. `_build_repeating_header` first calls `self.header_exists(key)` (line 671).
3. `header_exists` (line 1347) linearly scans **all** existing
   `self.block_headers` and calls `MFBlockHeader.get_transient_key`
   (line 291) on each one.
4. `get_transient_key` does not read a plain attribute. It resolves the
   header scalar through the full MFData machinery:
   `data_items[i].get_data()` -> `mfdatascalar.MFScalar.get_data` ->
   `_get_storage_obj()._access_data` (`flopy/mf6/data/mfdatascalar.py:115`,
   `flopy/mf6/data/mfdatastorage.py:690`). Each call costs tens of
   microseconds, not nanoseconds.
5. The same full scan happens a second time at write time:
   `MFBlock.write` -> `_add_missing_block_headers` (line 1329) calls
   `header_exists` for every active key, and `sorted(self.block_headers)`
   (line 1323) triggers `MFBlockHeader.__lt__` (line 127), which calls
   `get_transient_key` again per comparison.

Net effect: building + writing one transient package with nper provided
periods performs ~2 x nper^2 / 2 storage-backed key resolutions. With
nper = 6940 that is ~48 million `get_data()` round trips.

Sparse emission (only change points, MF6 repeats the last PERIOD block)
already keeps STO/AUX/EVT cheap in HydroModPy, but daily recharge changes
every period, so RCHA keeps ~6940 blocks no matter what.

## 3. The official performance flags do not help

FloPy ships `lazy_io` (= `verify_data=False` + `auto_set_sizes=False`,
`flopy/mf6/mfsimbase.py:291-303`), introduced by the upstream performance PR
[modflowpy/flopy#1674](https://github.com/modflowpy/flopy/pull/1674) and
documented in the
[MF6 data tutorial](https://flopy.readthedocs.io/en/latest/Notebooks/mf6_data_tutorial08.html).
The `header_exists` / `get_transient_key` path never consults these flags.
Measured on the benchmark below: 69.1 s -> 66.4 s. Not a fix.

## 4. Why caching the key is safe

The cache relies on one invariant: **an integer transient key is
write-once**.

- The key is bound by `MFBlockHeader.build_header_variables` (line 137) at
  header creation, called only from `_build_repeating_header` (line 693).
- Setting data for an existing period finds the existing header through
  `header_exists` and never rebinds its key.
- The only key-rewrite path in flopy, `MFTransient.update_transient_key`
  (`flopy/mf6/data/mfdata.py:87`), is called from one place
  (`MFBlock.set_model_relative_path`, line 613) and only for **string FILE
  keys** (e.g. OBS `continuous FILEOUT <path>` blocks) when a model
  workspace is relocated.

The patch therefore:

- caches only integer keys (`type(key) is int or isinstance(key,
  np.integer)`; `bool` is excluded because `True` is the recursion-guard
  sentinel and a `bool` is an `int` subclass);
- never caches `None` (header created but key not bound yet);
- bypasses the cache entirely when `data_path` is passed, preserving the
  recursion-guard semantics used by `mfdatalist`/`mfdataplist`;
- wraps `build_header_variables` to drop the cached value, so even a future
  rebind path cannot serve a stale key (correct by construction, not by
  call-graph analysis).

## 5. The patch

`hydromodpy/solver/modflow6/flopy_header_cache.py`, installed idempotently at
the entry of `run_pre_processing` (`solver/modflow6/build.py`) and
`run_processing` (`solver/modflow6/run.py`):

```python
def install_flopy_header_cache() -> None:
    if getattr(MFBlockHeader.get_transient_key, _PATCH_MARKER, False):
        return

    original_get = MFBlockHeader.get_transient_key
    original_build = MFBlockHeader.build_header_variables

    def get_transient_key(self, data_path=None):
        if data_path is not None:
            return original_get(self, data_path)
        cached = getattr(self, _CACHE_ATTR, None)
        if cached is not None:
            return cached
        key = original_get(self, None)
        if type(key) is int or isinstance(key, np.integer):
            setattr(self, _CACHE_ATTR, key)
        return key

    def build_header_variables(self, *args, **kwargs):
        if hasattr(self, _CACHE_ATTR):
            delattr(self, _CACHE_ATTR)
        return original_build(self, *args, **kwargs)

    setattr(get_transient_key, _PATCH_MARKER, True)
    MFBlockHeader.get_transient_key = get_transient_key
    MFBlockHeader.build_header_variables = build_header_variables
```

`header_exists` itself is untouched: it still scans the header list, but each
step is now one attribute read. The remaining O(nper^2) attribute-compare
loop costs seconds, not minutes; replacing it with a key set would be the
structural fix (see section 8).

## 6. Benchmark

Protocol: single RCHA package, 20x20 grid, nper = 6940 daily periods (the
chronicle size), one array per period, `write_simulation` to local disk.
Python 3.13, flopy 3.10.0, Linux. Script in the appendix.

| Variant | `ModflowGwfrcha.__init__` | `write_simulation` | total |
|---|---|---|---|
| flopy 3.10.0 stock | 32.2 s | 36.9 s | 69.1 s |
| `lazy_io=True` | 32.1 s | 34.3 s | 66.4 s |
| header-key cache | 2.7 s | 5.6 s | **8.3 s** |

Output equivalence: the written workspaces (baseline vs patched) are
byte-identical except the FloPy banner timestamp comment
(`# File generated by Flopy ... at <time>`), checked with
`diff <(grep -v '^#' a) <(grep -v '^#' b)` over every file.

On the real chronicle run the construction + write block weighs ~306 s; the
mechanism the cache removes accounts for ~220 s of it, so the expected gain
is roughly 4 minutes on a 22-minute run. Re-profile to confirm.

## 7. HydroModPy integration

- Module: `hydromodpy/solver/modflow6/flopy_header_cache.py` (MF6 backend
  only; the NWT backend uses the classic `flopy.modflow` stack and is not
  affected).
- Install sites: first statement of `run_pre_processing` (covers package
  construction) and of `run_processing` (covers a write/run without a prior
  build in the same process). The install is idempotent.
- Tests (`tests/unit/solver/test_modflow6_flopy_header_cache.py`), which also
  serve as a canary if a flopy upgrade changes the patched internals:
  - idempotent install;
  - written PERIOD blocks complete and unique (1..nper exactly once);
  - data round-trip through `MFSimulation.load`;
  - `header_exists` true/false behaviour plus cache population;
  - `data_path` recursion guard preserved;
  - `build_header_variables` drops a stale cached key.

## 8. Upstream PR notes (for modflowpy/flopy)

Two acceptable shapes, by increasing ambition:

1. **Minimal (this patch, inlined):** cache the resolved key on
   `MFBlockHeader` inside `get_transient_key` and invalidate it at the top of
   `build_header_variables`. ~10 lines in `mfpackage.py`, no API change, no
   behaviour change. The benchmark above is the justification.
2. **Structural:** keep a `dict[key, MFBlockHeader]` on `MFBlock`, maintained
   in `_build_repeating_header` (line 686), header removal, and
   `set_model_relative_path` renames, making `header_exists` O(1) and
   removing the scan entirely. More invasive: `block_headers` is also rebuilt
   on load (lines 372, 842-844), so every mutation point must update the
   index.

Suggested PR framing:

- Title: "perf(mf6): cache block-header transient keys to avoid O(nper^2)
  package build/write".
- Attach the appendix script as the reproducer; report the 69 s -> 8 s table.
- Point at the two scan sites (`_build_repeating_header` line 671,
  `_add_missing_block_headers` line 1344) and the per-comparison
  `get_transient_key` in `MFBlockHeader.__lt__` (line 127).
- Note that `lazy_io` / `verify_data` / `auto_set_sizes` from
  [#1674](https://github.com/modflowpy/flopy/pull/1674) do not cover this
  path; related older report on data-scaling pain:
  [#707](https://github.com/modflowpy/flopy/issues/707).
- The write-once argument of section 4 is the correctness core of the PR
  description; `update_transient_key` (string FILE keys only) is the one
  rename path reviewers will ask about, and the `build_header_variables`
  invalidation answers it.

### Second upstream candidate: CellBudgetFile.get_data mask building

Independent finding from the budget-extraction work (HydroModPy side fixed in
`perf(extract)` by iterating `recordarray` + `get_record(idx)` once instead of
calling `get_data` per (component, timestep)).

`CellBudgetFile.get_data` builds its selection mask as
`select_indices = np.array([True] * len(self.recordarray))`
(`flopy/utils/binaryfile/__init__.py:1647` in 3.10.0): a Python list of n
booleans converted to an array, on every call. Measured at 1.7 ms per call on
a 55k-record index (19-year daily chronicle); the standard "loop get_data
over kstpkper" usage pattern paid ~85 s for that line alone.
`np.ones(len(self.recordarray), dtype=bool)` does the same in ~2 us (x800).

- One line, no behaviour change, benefits every get_data loop in the wild.
- Optional follow-ups, more invasive: skip the mask entirely when ``idx`` is
  given (it currently builds the full True array then inverts), and index
  ``(kstp, kper, text)`` once in ``_build_index`` so per-call selection stops
  being O(n_records).
- Even with these, ``get_data`` stays O(n) per call (boolean scans +
  ``np.isclose`` on totim); batch readers should still iterate
  ``recordarray`` + ``get_record`` in file order like HydroModPy now does.

## 9. Removal plan

When a flopy release ships the fix:

1. bump the `flopy` pin in `pyproject.toml`;
2. delete `hydromodpy/solver/modflow6/flopy_header_cache.py`, the two
   one-line install calls in `build.py` / `run.py`, and the test file;
3. re-profile one chronicle run to confirm nothing regressed.

## Appendix: benchmark script

```python
"""flopy RCHA header bookkeeping benchmark (nper=6940, 20x20 grid).

Usage: python bench_rcha.py [nper] [--patched] [--lazyio]
"""

import shutil
import sys
import time

import numpy as np

PATCHED = "--patched" in sys.argv
LAZY = "--lazyio" in sys.argv
NPER = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 6940

import flopy

if PATCHED:
    from flopy.mf6.mfpackage import MFBlockHeader

    _orig_get_tk = MFBlockHeader.get_transient_key

    def get_transient_key(self, data_path=None):
        if data_path is not None:
            return _orig_get_tk(self, data_path)
        cached = getattr(self, "_tk_cache", None)
        if cached is not None:
            return cached
        key = _orig_get_tk(self, None)
        if type(key) is int or isinstance(key, np.integer):
            self._tk_cache = key
        return key

    MFBlockHeader.get_transient_key = get_transient_key

ws = f"/tmp/bench_flopy_rcha_{'p' if PATCHED else 'l' if LAZY else 'b'}"
shutil.rmtree(ws, ignore_errors=True)

nrow = ncol = 20
sim = flopy.mf6.MFSimulation(sim_name="bench", sim_ws=ws, lazy_io=LAZY)
flopy.mf6.ModflowTdis(sim, nper=NPER, perioddata=[(86400.0, 1, 1.0)] * NPER)
flopy.mf6.ModflowIms(sim)
gwf = flopy.mf6.ModflowGwf(sim, modelname="m")
flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=nrow, ncol=ncol)
flopy.mf6.ModflowGwfic(gwf)
flopy.mf6.ModflowGwfnpf(gwf)

rch = {k: np.full((nrow, ncol), 1e-9 * (k + 1)) for k in range(NPER)}

t0 = time.perf_counter()
flopy.mf6.ModflowGwfrcha(gwf, recharge=rch)
t1 = time.perf_counter()
sim.write_simulation(silent=True)
t2 = time.perf_counter()
mode = "patched" if PATCHED else "lazy_io" if LAZY else "baseline"
print(f"{mode} nper={NPER} init_rcha={t1 - t0:.1f}s write_simulation={t2 - t1:.1f}s")
```
