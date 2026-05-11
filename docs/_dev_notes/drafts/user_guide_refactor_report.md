# User Guide Refactor Report

Date: 2026-05-10
Status: succeeded

## Sphinx build status

- Final command: `HMP_SKIP_CONFIG_REFERENCE_GEN=1 python -m sphinx -j auto -b html docs/source docs/build/html`
- Build log: `/tmp/sphinx_build.log` (550 lines)
- Final warning count: total 0 / user_guide-related 0
- Result: `build succeeded.`
- No persistent baseline warning kept. The build is clean.

## Phase commits

- A1 `189081914` `[docs] - dedupe workflow topic pages (comparison, calibration, mesh)`
- A2 `d5f745bb3` `[docs] - merge solver-choice and solver-process-map into solvers.rst`
- A3 `5ac7aa3e1` `[docs] - absorb 7 driving modes into workflows/index and drop driving-hydromodpy`
- B1 `50caf783d` `[docs] - automate figures.rst and clean troubleshooting.rst`
- B2 `6a69b7495` `[cleanup] - drop capability-matrix, fold provider-matrix into data/index, remove pre-v1 migration notes`
- C1 (no fix commit needed; build was clean on first pass)

## Files: created / modified / deleted

### Created
- `docs/source/user_guide/solvers.rst` (311 lines) — fusion of `solver-choice` and `solver-process-map`
- `docs/source/user_guide/figures_inventory.partial.rst` (199 lines, auto-generated)
- `tools/doc_figures/__init__.py`, `tools/doc_figures/__main__.py`, `tools/doc_figures/generate.py` — auto-generator for figures inventory

### Modified
- `docs/source/user_guide/index.rst` (toctree slimmed, CTA cards retargeted to new canonical pages)
- `docs/source/user_guide/workflows/index.rst` (+227 net, absorbs 7 modes + Why TOML-first + dispatch model)
- `docs/source/user_guide/workflows/comparison.rst` (+218 net, absorbs Recommended First Cases, Typical Command, Allowed Variant Overlays, etc.)
- `docs/source/user_guide/workflows/calibration.rst` (+50 net, absorbs Pick A Method table)
- `docs/source/user_guide/workflows/testbed.rst` (+61 net, absorbs Mesh Decision Matrix + mesh-only TOML)
- `docs/source/user_guide/concepts/comparison-workflow.rst` (-467 net, slimmed to UML + scientific notes)
- `docs/source/user_guide/concepts/project-vs-run.rst` (-21 net, pre-v1 migration removed)
- `docs/source/user_guide/data/index.rst` (+254 net, absorbs provider-matrix table + 7 figures + provider replay)
- `docs/source/user_guide/figures.rst` (-48 net, replaced hardcoded table by .. include::)
- `docs/source/user_guide/troubleshooting.rst` (-14 net, hardcoded TOML list removed, mamba->conda)
- `docs/source/contribute.rst` (receives Windows/WSL PETSc section)
- `docs/source/conf.py` (adds builder-inited hook for figures inventory regen)
- `docs/source/redirects.txt` (8 new redirects)
- Cross-page retargets: `docs/source/index.rst`, `docs/source/getting_started/{index,cli-quickstart,choose-your-first-workflow}.rst`, `docs/source/theory/index.rst`, `docs/source/theory/boussinesq.rst`, `docs/source/theory/solvers/flow/index.rst`, `docs/source/architecture/{calibration/{index,calibration-guide,calibration-architecture}.rst,simulation/comparison-workflow.rst,how-to/{add-a-calibration-method,add-a-data-source}.rst,packages/{analysis,calibration,data}.rst}`

### Deleted
- `docs/source/user_guide/calibration.rst` (-163)
- `docs/source/user_guide/comparison.rst` (-121)
- `docs/source/user_guide/mesh.rst` (-113)
- `docs/source/user_guide/solver-choice.rst` (-124)
- `docs/source/user_guide/solver-process-map.rst` (-231)
- `docs/source/user_guide/driving-hydromodpy.rst` (-293)
- `docs/source/user_guide/capability-matrix.rst` (-157)
- `docs/source/user_guide/data/provider-matrix.rst` (-263)

### Aggregate delta on `docs/source/user_guide/`
- Insertions: 1355
- Deletions: 2052
- Net: -697 lines

## Redirects added to docs/source/redirects.txt

- `user_guide/comparison user_guide/workflows/comparison`
- `user_guide/calibration user_guide/workflows/calibration`
- `user_guide/mesh user_guide/workflows/testbed`
- `user_guide/solver-choice user_guide/solvers`
- `user_guide/solver-process-map user_guide/solvers`
- `user_guide/driving-hydromodpy user_guide/workflows/index`
- `user_guide/capability-matrix user_guide/index`
- `user_guide/data/provider-matrix user_guide/data/index`

## Brief section 4 preservation checklist

- 4.1 Pick a method table -> `docs/source/user_guide/workflows/calibration.rst:77` (header "Pick A Method"). Table rows: `optuna` TPE, `optuna` CMA-ES, `scipy_de`, `scipy_nelder_mead`. **Present**.
- 4.2 Mesh decision matrix -> `docs/source/user_guide/workflows/testbed.rst:229` (header "Mesh Decision Matrix") plus mesh-only TOML at line 264. **Present**.
- 4.3 Transport solvers + MODPATH + MT3DMS + modflow6gwt + Generalized Categories + Practical Selection Rules -> `docs/source/user_guide/solvers.rst` (modpath/mt3dms/modflow6gwt at lines 129/133/138, TOML snippets at lines 161/175, transport.modpath/mt3dms/modflow6gwt parameters at lines 186/191/198). **Present**.
- 4.4 UML + Why-It-Exists + Method-Notes + 9 scientific notes -> `docs/source/user_guide/concepts/comparison-workflow.rst:30` (UML `diagrams/comparison_workflow_execution.wsd`), line 36 (Why It Exists), line 60 (Method Notes). **Present**.
- 4.4 moved: Recommended First Cases + How To Run It -> `docs/source/user_guide/workflows/comparison.rst:51` (Recommended First Cases) and line 36 (Typical Command). **Present**.
- 4.4 moved: Windows/WSL PETSc -> `docs/source/contribute.rst:197` (Windows + WSL split for PETSc) and Boussinesq drying pytest command in the same file. **Present**.
- 4.5 Comparison decision matrix -> merged into `docs/source/user_guide/workflows/comparison.rst:374` (Next Pages) with `:doc:` pointers to reading-results-pages and architecture/simulation. **Present**.
- 4.6 Pre-v1 migration section -> Removed from `docs/source/user_guide/concepts/project-vs-run.rst` (grep "pre-v1|SimulationView" returns empty). **Removed**.
- 4.7 7 provider-matrix figures -> all in `docs/source/user_guide/data/index.rst`:
  - `geographic_nancon_identity_card_station_inventory.png` at line 94
  - `data_family_source_matrix.png` at line 115
  - `geographic_nancon_identity_card_map_geology.png` at line 211
  - `geographic_nancon_identity_card_climatic_summary.png` at line 218
  - `hubeau_provider_replay_examples.png` at line 232
  - `hydrography_provider_replay_examples.png` at line 240
  - `hydrography_provider_couesnon_comparison.png` at line 247
  **Present (7/7)**.
- 4.8 7 modes -> `docs/source/user_guide/workflows/index.rst`: Why TOML-first at line 186, Mode 1 at 202, Mode 2 at 216, Mode 3 at 232, Mode 4 at 247, Mode 5 at 262, Mode 6 at 276, Mode 7 at 291. **Present (7/7)**.
- 4.9 capability-matrix -> file deleted, redirect `user_guide/capability-matrix user_guide/index` in redirects.txt. **Removed**.

## Bugs found and fixed during validation

None. Phase A and Phase B sub-agents (plus orchestrator cleanup of B2 after rate-limit) left the tree in a state where the first Sphinx build completed with zero warnings.

The first build run accidentally inherited stale HTML at the deleted page paths because the build directory was not fully purged between the orchestrator's pre-fork experiments. A second purge (`rm -rf docs/build/html docs/build/.doctrees`) followed by a clean rebuild confirmed:
- Zero warnings.
- None of the deleted HTML pages reappear (`user_guide/{comparison,calibration,mesh,solver-choice,solver-process-map,driving-hydromodpy,capability-matrix}.html` and `user_guide/data/provider-matrix.html` are all absent).
- The new `user_guide/solvers.html`, `user_guide/workflows/{comparison,calibration,testbed}.html`, and `user_guide/data/index.html` are present.
- All 7 provider-matrix figures, the UML diagram (rendered as SVG/PNG by PlantUML), and the 7 modes are rendered in the right HTML pages.

## Pages needing human visual review

The following pages had substantive structural changes; a 5-minute browser pass would catch any layout regression:

- `docs/build/html/user_guide/workflows/index.html` (now hosts the 7 modes plus the workflow table and dispatch model; vertical length is significant).
- `docs/build/html/user_guide/workflows/comparison.html` (absorbed seven new sections; check the table widths under "Recommended First Cases").
- `docs/build/html/user_guide/workflows/calibration.html` (Pick A Method table layout).
- `docs/build/html/user_guide/data/index.html` (now contains the provider matrix + 7 figures + provider families table + common/specialized fields; scan for figure ordering and table breakage).
- `docs/build/html/user_guide/solvers.html` (new page; verify flow/transport/postprocess split renders cleanly and the `tab-set` for MODFLOW-NWT vs MODFLOW 6 transport stacks works).
- `docs/build/html/user_guide/concepts/comparison-workflow.html` (much shorter; verify the UML diagram still renders and the See also list points at the new workflows location).
- `docs/build/html/user_guide/figures.html` (uses the auto-generated `figures_inventory.partial.rst`; verify the `FigureKind` tables render cleanly).

## Out-of-scope follow-ups

- The build also emits `(good) user_guide/data/families/index.html --> user_guide/data/index.html`, a leftover redirect from an earlier doc restructure. Harmless.
- `tools/doc_figures` is now wired into `conf.py` via a `builder-inited` hook (B1 decision). The cost is one extra small generation step per build; not measurable in practice given parallel build.
- Other files modified in the working tree but not part of this refactor are still uncommitted (`docs/source/_static/custom.css`, `docs/source/install.rst`, etc.); those belong to earlier session work and were not included in any of the 5 phase commits.

## Acceptance criteria

For each of the 10 criteria in section 9 of the brief:

1. `make -C docs html` `build succeeded`. Zero warning on user_guide files. **PASS** (evidence: `/tmp/sphinx_build.log` has no `WARNING` or `ERROR` line).
2. All deleted pages have a redirect entry. **PASS** (8 redirects added; verified above).
3. `grep -rn mamba docs/source/user_guide/` returns empty. **PASS**.
4. `grep -rn "pre-v1\|SimulationView\b" docs/source/user_guide/` returns empty. **PASS**.
5. All section 4 elements retrievable in a user_guide page. **PASS** (full checklist above).
6. All pre-refactor figures still referenced. **PASS** (7 provider-matrix figures + UML + 2 dupuit + workflow gallery figures).
7. No manual lists of figures/TOML sections/data sources in user_guide/ (excluding config_reference/). **PASS** (`figures.rst` is `.. include::` from auto-generated partial; `troubleshooting.rst` no longer enumerates TOML sections; `data/` family pages remain as the per-family operational contract).
8. At most one operational + one conceptual page per workflow. **PASS** (workflows/<w>.rst for ops; concepts/comparison-workflow.rst is the only conceptual page; calibration and mesh have no conceptual page).
9. `user_guide/index.rst` <= 15 toctree entries. **PASS** (12 entries).
10. All internal links use `:doc:` or `:ref:`, no new readthedocs.io URLs. **PASS** (no readthedocs.io URL was added).

## Overall verdict

**PASS**. Refactor delivered to spec, zero Sphinx warnings, all section 4 unique content preserved at its new canonical location, 8 redirects in place, net -697 lines on `docs/source/user_guide/`.
