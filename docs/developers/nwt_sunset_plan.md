# MODFLOW-NWT sunset plan

## Context

HydroModPy currently ships two MODFLOW flavours:

- **MODFLOW-NWT** under `hydromodpy/solver/modflow_nwt/` — legacy
  structured (DIS) solver historically used for most Brittany
  catchments.
- **MODFLOW 6** under `hydromodpy/solver/modflow6/` — modern unstructured
  (DISV) solver, strategic target for future work.

Each flavour owns a dedicated `flow_to_modflow_adapter.py`:

- `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py` — 1391 L
- `hydromodpy/solver/modflow6/flow_to_modflow_adapter.py` — 581 L

The P06 refactoring phase of the `dev-refact_v2` migration factored the
shared dispatch layer (`BoundaryKind → "RIV"/"DRN"/"GHB"/"CHD"`) into
`hydromodpy/solver/modflow_common/flow_translator.py`. The payload
builders themselves remain intentionally duplicated.

## Decision

**NWT and MF6 will NOT be mutualised further.** MODFLOW-NWT is scheduled
for removal in a future release, after the Lake (LAK) module integration
lands on the MF6 side.

## Why

- **Lake support.** MF6 ships a first-class `LAK` package with a clean
  integration path. NWT only offers a do-it-yourself approach built on
  top of DRN/GHB trickery. HydroModPy's Brittany use cases (Ploemeur,
  coastal catchments, managed lakes) push the project towards MF6.
- **Factorisation cost.** Remonting the RIV / GHB / DRN / CHD / WEL
  payload builders into `modflow_common/boundary_packages.py` would
  require non-trivial bookkeeping (DIS vs DISV cell identifiers,
  stress-period data layout, intermittency handling). The work would
  only be thrown away when NWT is retired.
- **Removal ROI.** Retiring NWT will delete the entire
  `hydromodpy/solver/modflow_nwt/` branch (~3 500 L including the 1 391 L
  adapter), the `nwt`-marked tests, and the NWT-specific CI lanes. That
  payoff dwarfs any short-term deduplication benefit.

## Timeline

| Milestone | State |
|---|---|
| v0.4 release | NWT fully supported, intentional duplication documented. |
| Lake module integration in MF6 | Unblocks Ploemeur / coastal lake workflows on MF6. |
| Post-LAK release | NWT solver branch + adapter deleted; NWT markers removed from tests; documentation migrated to MF6 only. |

## User impact

- **v0.4 and earlier:** NWT workflows keep running unchanged. The
  `nwt` pytest marker remains green.
- **After the LAK milestone:** NWT is removed in one clean breaking
  change. A migration note will be published alongside the release,
  explaining how to port an existing NWT TOML to MF6 (solver swap plus
  DIS → DISV mesh pivot; both already supported side-by-side today).

## What this means for day-to-day work

- Do **not** refactor
  `hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py`
  to share payload builders with MF6.
- New boundary-condition features should be prototyped on the MF6 side
  first. Porting to NWT is only required if a Brittany workflow on v0.4
  explicitly needs it.
- Bug fixes in the NWT adapter stay NWT-local. No cross-adapter sync is
  expected.
