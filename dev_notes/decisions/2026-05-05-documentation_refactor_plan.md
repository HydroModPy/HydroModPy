# Plan de refonte de la documentation

Date : 2026-05-05 (révisé 2026-05-06 après livraison Phases 0+1+2)
Statut : Phase 0 + Phase 1 (sauf étape 21) + Phase 2 livrées sur `dev-docs`. Phase 3 conditionnelle (analytics + retours).
Périmètre : dossier `docs/` de HydroModPy

Ce document consolide l'audit, les décisions et l'architecture cible pour la
documentation de HydroModPy. Il sert de guide de référence pour la refonte.

## Statut global au 2026-05-06

| Phase | Étapes | Statut | Branche | Commits |
|---|---|---|---|---|
| Phase 0 — Quick wins | 1 à 10 | ✓ livrée 2026-05-05 | `dev-docs` | `07f2f3b30` → `a0799bf69` |
| Phase 1 — Refonte structurelle | 11 à 22 | ✓ 12/12 livrée (étape 21 incluse) | `dev-docs` | `b5144869b` → `c8e8057dd` |
| Phase 2 — Enrichissement | 23 à 37 | ✓ livrée 2026-05-06 | `dev-docs` | `072b06e00` → `2f7697342` |
| Phase 3 — Optionnel/conditionnel | 38 à 45 | ⏸ non démarrée (gated sur retours) | — | — |

Build sphinx local clean : 3 warnings baseline (incrémental) / 8 sur fresh
build (5 issues codebase pré-existantes). Voir
`dev_notes/diagnostics/doc_health.md` pour le détail.

## Comment lancer la suite

### Phase 3 conditionnelle (étapes 38 à 45)

À ne lancer que si les déclencheurs sont là :

| Étape | Déclencheur attendu |
|---|---|
| 38 — WebP gallery | Mesure analytics signale bande passante saturée |
| 39 — image-comparison slider | Cas concret en attente côté mesh / solver pages |
| 40 — Algolia DocSearch | Candidature acceptée côté Algolia |
| 41 — GoatCounter + "Was this helpful?" | Décision d'activer collecte d'usage |
| 42 — difficulty + time badges | Tutoriels migrés disponibles |
| 43 — workflow GIFs | Captures réalisées hors RTD |
| 44 — Stoplight schema explorer (couche 3) | Couches 1/2/4 jugées insuffisantes par retours |
| 45 — vtk-js mesh viewer | Mention seulement, ne pas implémenter |

Quand un déclencheur tombe, ouvrir une session Claude Code sur `dev-docs` et
lancer : "exécute Phase 3 étape <N> du plan, build sphinx -j auto, commit
seul, pas de subagents".

### Workflow standard d'une étape

1. `mamba activate hmp_refact` (env Python 3.13 + extensions tier-1+tier-2)
2. Modifier sources sous `docs/source/` ou `tools/doc_config/`
3. Si édit Pydantic config : `python -m tools.doc_config` pour regénérer
   les pages `user_guide/config_reference/*.rst`
4. Build : `python -m sphinx -j auto -b html docs/source docs/build/html`
   (ou `make -C docs html` si `make` est installé)
5. Vérifier : 0 nouveau warning hors baseline
6. `git add` explicite par fichier, pas de `git add -A`
7. Commit : `[docs] - <imperative>` sans body, sans co-author
8. Mettre à jour le numéro d'étape dans la section 0.2 du plan
9. Commit du plan : `[docs] - mark phase X step Y as completed in refactor plan`

### Fichiers de référence à connaître

| Fichier | Rôle |
|---|---|
| `dev_notes/decisions/2026-05-05-documentation_refactor_plan.md` | Ce document, source de vérité |
| `dev_notes/diagnostics/doc_health.md` | Tableau de bord build / warnings / coverage |
| `docs/source/conf.py` | Config sphinx, extensions, intersphinx, OG, sitemap, favicon |
| `docs/source/_ext/hmp_directives.py` | Directives custom + roles stability |
| `tools/doc_config/` | Pipeline génération pages config_reference (couches 1/2/4) |
| `tools/doc_gallery/` | Pipeline gallery existant, ne pas modifier sans précaution |
| `CITATION.cff` | Métadonnées citation à la racine du repo |
| `.readthedocs.yaml` | Config RTD (à toucher pour étape 21) |

---

## 0. SOURCE DE VÉRITÉ : décisions consolidées et phasage

**Cette section override les sections suivantes (notamment 5, 6, 8, 9, 10, 13,
14, 15) sur tous les points où elle entre en conflit. Les sections suivantes
restent comme contexte historique et détail technique, mais les décisions
finales sont ici.**

### 0.1 Décisions actées (chat 2026-05-05)

| # | Décision | Conséquence |
|---|---|---|
| Stack | Sphinx + RTD + pydata-sphinx-theme + RST conservés | Pas de migration MyST/MkDocs/Quarto/Furo |
| Multi-version | `sphinx-polyversion` (pas `sphinx-multiversion`) | Tags + master + dev + dev-docs = versions RTD |
| Multilingue | EN-only sur RTD, FR autorisé dans `dev_notes/` uniquement | Refus toute PR de traduction publique |
| Public/interne | `docs/source/` publié, `dev_notes/` versionné non publié, hors repo pour le reste | Pas de mélange |
| Hoist | `docs/readthedocs/source/` → `docs/source/` dès Phase 0 | Évite double move git |
| Tutoriels exécutables | **Non** (pas de sphinx-gallery exécution, pas de notebook au build) | Build RTD léger, zéro mamba env solveur côté RTD |
| Codespaces / Binder | **Non** (try-it-online retiré du scope) | Aucune image Docker à maintenir |
| Notebooks legacy (12 .ipynb) | Quarantaine `docs/source/_legacy_notebooks/` avec `:orphan:` | Hors build, gardés pour migration future séparée |
| Slot `examples/` | Réservé `docs/source/examples/index.rst` annoncé "coming soon" | Réintégration future quand notebooks migrés |
| TOML-first | Recipes et getting started en TOML + CLI `hmp run`, Python full = mode dev/prototypage | Cohérent identité TOML déclaratif |
| Revue PR doc | Pas de cadence formelle, n'importe qui peut merger | Bastien seul mainteneur aujourd'hui |
| Versioning git tags | Déjà en place, on ne touche pas | Pas d'effort à prévoir |
| Redirections page-rename | Obligatoires via `sphinx-rediraffe`, fichier `redirects.txt` | Chaque rename = ligne ajoutée |
| Schema Explorer Stoplight | Reporté Phase 3 (mesure d'usage avant) | Couches 1+2+4 suffisent (autodoc-pydantic + erdantic + TOML annoté) |
| Erdantic | Par section (16 diagrammes ciblés), pas global sur 115 classes | Lisibilité |
| Composants UI niche | Tabs `sphinx-design` partout + image comparison slider sur 3-4 pages clés. vtk-js mentionné comme évolution future possible mais non implémenté | Fluide, ergonomique, sans dette React |
| Solver capability matrix | Oui | YAML + directive custom |
| Workflow flowchart Mermaid cliquable | Oui | Mermaid native |
| Geographic application map Leaflet | Oui | Visuel scientifique fort |
| TOML linter Monaco / Calibration estimator | **Non** (Phase 3 conditionnel ou jamais) | Trop niche, dette JS |
| Diagrammes existants | Mermaid prioritaire, PlantUML conservé pour UML détaillé. Audit + suppression des diagrammes legacy (`DataManagersPlanner`, `Watershed`, `pipeline/`). Carte blanche assistant | Ergonomie + maintenance basse |
| Algolia DocSearch | Candidature à déposer (Bastien remplit le formulaire). Intégration Phase 3 si accepté | Crawl crawl URL `dev` (master obsolète) |
| Analytics | GoatCounter gratuit | Pilote la doc avec data |
| Widget "Was this helpful?" | Oui Phase 3 (back-end GoatCounter) | Signal qualité par page |
| Diff PNG visuel | Oui Phase 1, avec commande `--update-baseline --reason` | Protège la gallery |
| WebP gallery | Oui Phase 3 | -40 à -60% bandwidth |
| Doc health dashboard | Oui Phase 2 (script + CI hebdo dans `dev_notes/diagnostics/doc_health.md`) | Pilote la santé éditoriale |
| Bibliographie BibTeX | Phase 1, pour papiers équipe et théorie. Extensible facile pour citer méthodes | Crédibilité scientifique |
| Cookbook | 10 recettes TOML-first Phase 2, extensible au fil des PR | Vecteur principal de code dans la doc |
| Comparaisons HydroModPy vs autres outils | **Non** (politique : pas de comparaison) | Évite controverses |
| Papers using HydroModPy | Oui avec recherche initiale Google Scholar | Crédibilité immédiate |
| Difficulty / time badges + GIFs | Phase 3 | Effort modéré, gain UX réel |
| Reproducibility lock par tutoriel | Skip (cohérent avec pas de tutoriels exécutables) | Sans objet |
| Spelling check (`sphinxcontrib-spelling`) | Skip (l'IA passera dessus en revue) | Évite faux positifs |
| Plan refonte (ce document) | Devient ADR figé daté `dev_notes/decisions/2026-05-05-documentation_refactor_plan.md` après exécution | Décisions futures = nouveaux ADR datés |
| `make livehtml` (sphinx-autobuild) | Oui Phase 0 | DX local rapide, pas de rebuild RTD |
| Slot revue PR formelle | Skip | Bastien seul aujourd'hui |
| Format commits | `[tag] - short imperative sentence` selon CLAUDE.md, **pas de mention de phase** dans les messages | Discipline existante |

### 0.2 Phasage exécutable (remplace les 36 étapes de la section 15)

#### Phase 0 — Quick wins (~5 jours, effet immédiat)

**Statut : terminée le 2026-05-05.** Build local clean (3 warnings baseline
inchangés : workflow.internals stubs hors toctree). 10 commits sur `dev-docs`,
de `07f2f3b30` à `a0799bf69`. Le hoist de `docs/readthedocs/source` vers
`docs/source` a touché 941 fichiers (renames + path updates dans tools, tests,
CI, READMEs, .gitignore, .gitleaks.toml, .readthedocs.yaml).

Commits autonomes, format `[tag] - message`, sans mention de phase :

1. `[cleanup] - drop dead build_dummy folders and out-of-scope files`
   - `git rm -r docs/_build_dummy/ docs/readthedocs/_build_dummy/`
   - `git rm -r docs/community/ docs/links/`
2. `[refactor] - hoist docs source tree to docs/source`
   - `git mv docs/readthedocs/source docs/source`
   - `git mv docs/readthedocs/Makefile docs/Makefile`
   - Update `.readthedocs.yaml` to point at `docs/source/conf.py`
   - Cleanup `docs/readthedocs/` empty wrapper
3. `[docs] - dedupe autodoc_mock_imports and add intersphinx mapping`
   - Remove second `autodoc_mock_imports` block at line 485 of `conf.py`
   - Add `sphinx.ext.intersphinx` with mappings to numpy, scipy, pandas, matplotlib, flopy
   - Drop the 30+ `nitpick_ignore_regex` entries that intersphinx now resolves
   - Set `source_suffix = [".rst", ".md"]`
4. `[docs] - widen content area and disable secondary sidebar on gallery cases`
   - Create `docs/source/_static/custom.css` with widening and table overflow rules
   - Add `custom.css` to `html_css_files`
   - Update `tools/doc_gallery/` to emit `:html_theme.sidebar_secondary.remove:` on case pages
   - Regenerate gallery
5. `[docs] - quarantine legacy notebooks under _legacy_notebooks orphan`
   - `git mv docs/source/notebooks docs/source/_legacy_notebooks`
   - Add `:orphan:` directive to each notebook (or exclude from build via `exclude_patterns`)
   - Remove from `examples.rst` toctree
6. `[docs] - reserve examples slot for future migrated notebooks`
   - Create `docs/source/examples/index.rst` with "coming soon" notice
   - Add to main toctree (visible)
7. `[docs] - add concepts in 5 minutes onboarding page`
   - Create `docs/source/getting_started/concepts_in_5_min.rst`
   - 5 concepts (Project, Run, Workflow, Catchment, Solver) with analogies, no code
   - Link from `getting_started/index.rst` as first item
8. `[docs] - move developer notes diagnostics drafts and decisions out of docs`
   - `mkdir -p dev_notes/{decisions,diagnostics,drafts,legacy}`
   - Create `dev_notes/README.md` describing each subfolder role
   - Move per section 0.3 below
9. `[docs] - clean architecture pipeline ghost and DataManagersPlanner references`
   - Edit `docs/source/architecture/index.rst` to remove `pipeline/` ghost
   - Regenerate `docs/source/architecture/data_loading/diagrams/data_definition_transfer_class.wsd` with `DataPlanner`
   - Audit other ghost references
10. `[docs] - add make livehtml target with sphinx-autobuild`
    - Add `pip install sphinx-autobuild` to dev requirements
    - Add `livehtml` target to `docs/Makefile`
    - Document in (future) `developer/contributing.rst`

#### Phase 1 — Refonte structurelle (~10-12 jours)

**Statut : 11/12 commits livrés sur `dev-docs` (étape 21 reportée).**
Build local clean, 8 warnings (3 substantifs : autosummary échoue à importer
`hydromodpy.data.variables.{hydrometry,piezometry}.discovery` et
`hydromodpy.workflow.pipelines.overview` faute de modules dépendants
manquants côté codebase ; 5 `DeprecationWarning` infrastructure Python 3.13
sur `multiprocessing/popen_fork`). Aucun introduit par les étapes 12 à 22.

11. `[docs] - switch api ref to recursive autosummary` ✓ (commit `b5144869b`)
12. `[docs] - reorganise capability gallery into 5 categories with thumbnails and All cases page` ✓
13. `[docs] - add visual drift check for gallery PNG with update-baseline command` ✓
14. `[docs] - rename scientific to theory and consolidate boussinesq notes` ✓
15. `[docs] - add bibtex bibliography and convert prose citations` ✓
16. `[docs] - consolidate user guide leaves and absorb getting_started orphans` ✓
17. `[docs] - publish stable subset of developers/ as docs/source/developer/ and dispatch architecture pages` ✓
18. `[docs] - install tier-1 sphinx extensions (mermaid, bibtex, codeautolink, autodoc-typehints, issues, rediraffe)` ✓
19. `[docs] - add redirect map for refactored pages` ✓
20. `[docs] - audit and migrate diagrams (mermaid prioritaire, plantuml UML détaillés, suppression legacy)` ✓
21. `[docs] - migrate from sphinx-multiversion to sphinx-polyversion` ✓ (commit `c8e8057dd`)
    - `sphinx_multiversion` retiré des `extensions` et de `_DOC_REQUIRED_EXTENSIONS` dans `docs/source/conf.py` ; remplacé par `sphinx_polyversion` (chargé seulement quand `POLYVERSION_DATA` est fourni par le driver)
    - `pyproject.toml [docs]` : `sphinx-multiversion` → `sphinx-polyversion>=1.0`
    - `docs/readthedocs_requirements.txt` : `sphinx-multiversion==0.2.4` → `sphinx-polyversion>=1.0`
    - `poly.py` ajouté à la racine : `DefaultDriver` + `Git` (branches `master|dev|dev-docs`, tags `v\d+\.\d+\.\d+`) + `SphinxBuilder` avec `-j auto -b html`
    - `docs/Makefile` : nouvelles cibles `polyversion` (multi-version) et `polyversion-local` (working tree only)
    - `tests/unit/test_docs_dependencies.py` et `install/verify_dev_env.py` mis à jour (le premier corrige aussi le chemin RTD requirements vers `docs/readthedocs_requirements.txt`)
    - Build sphinx local `python -m sphinx -j auto -b html` reste à 3 warnings baseline ; `python -m sphinx_polyversion poly.py -l --sequential` produit le site dans `docs/build/html/dev-docs/`. RTD continue d'utiliser ses builds par branche, sans `build.commands` custom.
22. `[docs] - enable doc linting and warnings-as-errors gate` ✓ (livré sous forme `lint` + `html-strict` opt-in pour ne pas casser `make html` tant que les 3 warnings codebase pré-existent)

#### Phase 2 — Enrichissement (~9-11 jours)

**Statut : 15/15 commits livrés sur `dev-docs`.**
Build local clean (3 warnings baseline inchangés). Tableau de progression
détaillé maintenu sous chaque étape ; aucune régression introduite par
les étapes 23 à 37.

23. `[docs] - add visual identity, CITATION.cff and how-to-cite page` ✓ (commit `072b06e00`)
    - CITATION.cff à la racine (19 auteurs, preferred-citation HESS in-preparation)
    - `docs/source/how_to_cite.rst` BibTeX/RIS/plain text avec copy-button
    - `docs/source/developer/style_guide.rst` palette, typographie, figures
24. `[docs] - add solver capability matrix, workflow flowchart and geographic application map` ✓ (commit `77e997d62`)
    - Matrice axe par axe (steady, transient, unstructured, transport, calibration, 1D/2D/3D) ajoutée en tête de `theory/solvers/solver-capability-matrix.rst`
    - Workflow flowchart mermaid cliquable (6 nœuds) sur `user_guide/workflows/index.rst`
    - `docs/source/applications.rst` registre catchments + mermaid régional, version Leaflet interactive reportée Phase 3 step 41
25. `[docs] - install tier-2 sphinx extensions (favicon, sitemap, last-updated-by-git, opengraph)` ✓ (commit `9df202cf7`)
    - sphinx-favicon, sphinx-sitemap, sphinx-last-updated-by-git, sphinxext-opengraph ajoutés à `pyproject.toml [docs]` et `_DOC_REQUIRED_EXTENSIONS`
    - Logos copiés vers `docs/source/_static/` pour résolution sphinx-favicon
    - sitemap.xml généré, balises og:* sur chaque page, footer "Last updated"
    - Aucun nouveau warning au build sphinx
26. `[docs] - add custom config-field, validation-case-summary and solver-comparison directives` ✓ (commit `be394f075`)
    - Module `docs/source/_ext/hmp_directives.py` (3 directives, ~280 LOC)
    - `config-field` traverse `HydroModPyConfig.model_fields` par dotted path, rend admonition
    - `validation-case-summary` lit `_static/capability_gallery/validation/<slug>_summary.json`
    - `solver-comparison` matrice solveur x cas avec premier `metric_lines` par cellule
    - Démo dans `theory/boussinesq.rst` (1 case summary + 1 solver-comparison sur 2 cas)
27. `[config] - complete Field descriptions for analysis and mesh_catchment` ✓ (commit `320cfa635`)
    - 5 champs requis sans description complétés dans `analysis/batch/config.py` (selection, catalog, recipes)
    - 16 champs avec default literal (sans Field()) convertis en Field(default=..., description=...) dans `zone_meshing/config.py` (RefinementFamilySettings, HotspotSettings, GridSettings, RefinementPolicy.enabled)
    - Ruff check/format passés, build sphinx clean (3 warnings baseline inchangés)
28. `[docs] - add tools/doc_config pipeline for hierarchical config reference (couches 1, 2, 4 only)` ✓ (commit `df74675ea`)
    - Pipeline `tools/doc_config/` avec `python -m tools.doc_config`
    - Génère 18 fichiers RST sous `docs/source/user_guide/config_reference/`
    - Couche 1 = `index.rst` grid card par section avec lien
    - Couche 2 = page par section (workspace, geographic, ..., calibration) avec table Fields (type, default, description)
    - Couche 4 = `complete_toml.rst` dropdowns par section avec snippet TOML annoté
    - Couche 3 (Stoplight viewer interactif) explicitement skippée selon plan v1
    - doc8 propre, build sphinx clean
29. `[docs] - add per-section erdantic ER diagrams` ✓ (commit `da3bd25c6`)
    - 16 SVG ER diagrams générés sous `docs/source/user_guide/config_reference/_diagrams/`
    - erdantic + pygraphviz installés via mamba (gcc absent du système, pip échoue)
    - Pipeline `tools/doc_config` étendu pour appeler erdantic.create + draw par section
    - Diagrammes intégrés dans page section juste après docstring
    - erdantic ajouté à pyproject.toml [docs]
30. `[docs] - cross-link config sections with gallery cases` ✓ (commit `ad24a9c40`)
    - `_scan_section_to_cases()` lit les `*_summary.json` validation et extrait préfixe section depuis dotted paths (parameter_docs)
    - Sections de pages config gagnent un bloc "Cases using this section" avec liens :doc: vers les pages cas
    - Tableau Fields désormais wrappé via textwrap pour respecter doc8 100 cols
    - doc8 exclut `config_reference/*` (slugs trop longs pour 100 cols, fichiers générés)
    - Direction inverse (gallery -> config) reportée car invasive sur tools/doc_gallery
31. `[docs] - add troubleshooting page indexed by error message` ✓ (commit `79ec11b25`)
    - `docs/source/user_guide/troubleshooting.rst` avec 14 messages couverts (config parsing, binaires solveurs, data/storage, calibration, build doc)
    - Format dropdown sphinx-design avec sections Cause/Fix
    - Lien "comment signaler une nouvelle erreur" pointe vers GitHub issues
32. `[docs] - add migration guides and api stability roles` ✓ (commit `186fbcf81`)
    - Roles `:stable:` `:experimental:` `:deprecated:` ajoutés à `_ext/hmp_directives.py` (badges colorés inline)
    - CSS palette `#15803d` (vert), `#d97706` (orange), `#b91c1c` (rouge) dans `_static/custom.css`
    - `docs/source/migration/index.rst` + `migration/v0_to_v1.rst` (mapping Watershed/master_config -> Project/HydroModPyConfig avec exemples avant/après)
    - Légende stability + section "où aller ensuite"
33. `[docs] - add cookbook with 10 TOML-first recipes` ✓ (commit `0624fee5d`)
    - `docs/source/user_guide/cookbook/index.rst` une page consolidée
    - 10 recettes : saved project, DEM+outlet, polygon, K hétérogène, Boussinesq 1D synthétique, calibration grid, comparison MF6/Boussinesq, mesh seul, batch site catalogue, export NetCDF
    - Chaque recette = TOML + `hmp run` CLI
34. `[docs] - add unified notation page and remove tools comparisons (skip per decision)` ✓ (commit `ba08e7d5f`)
    - `docs/source/theory/notation.rst` (5 sections : hydraulic state, parameters, geometry, time/calibration, conventions)
    - Mention explicite que la page de comparaison vs FloPy/ParFlow est skippée selon décision plan v1
    - Référence vers `solvers/solver-capability-matrix` comme alternative
35. `[docs] - add usage bibliography (papers using HydroModPy with seed entries)` ✓ (commit `12038e903`)
    - 5 nouvelles entrées bibtex dans `references.bib` (abherve2024headwater, abherve2025climate, floriancic2024knickpoint, lemesnil2024coastal, marti2024wetland)
    - `docs/source/usage_bibliography.rst` avec :cite: role pour chaque entrée et résumé d'utilisation
    - Lien depuis applications.rst et how_to_cite
36. `[docs] - add doc health dashboard in dev_notes` ✓ (commit `b70525e8d`)
    - `dev_notes/diagnostics/doc_health.md` (interne, pas dans la doc publique)
    - Tableaux : build health, baseline warnings, doc linting, coverage, stubs, cross-link checks
    - Procédure refresh documentée (regen doc_config + build sphinx -j auto)
37. `[docs] - revamp landing page with hero CTAs and citation block` ✓ (commit `2f7697342`)
    - Refonte `index.rst` : pitch lead + 5 status badges (license/python/version/docs/DOI shields.io) + 3 CTAs (Get started, View gallery, API reference)
    - Section "What's new" avec 3 derniers items du CHANGELOG (v0.3.3, v0.3.2, v0.3.1)
    - Bloc citation BibTeX avec copy-button, lien vers how_to_cite et CITATION.cff
    - Card grid étendu (10 cards : Installation, Quickstart, User guide, Cookbook, Case studies, Theory, Developer guide, API, Migration, Contributors)
    - CSS pour `.lead` + hover sur landing CTAs

#### Phase 3 — Optionnel et conditionnel (~6-8 jours)

À reprendre seulement si analytics GoatCounter, retours utilisateurs ou besoins identifiés le justifient.

38. `[docs] - convert gallery PNG to WebP with picture fallback`
39. `[docs] - add image comparison slider for mesh structured vs unstructured pages`
40. `[docs] - integrate algolia docsearch (after acceptance)`
41. `[docs] - add goatcounter analytics and was-this-helpful widget`
42. `[docs] - add difficulty and time badges`
43. `[docs] - capture and embed key workflow GIFs (calibration convergence, mesh refinement, CLI setup)`
44. `[docs] - add interactive schema explorer with stoplight viewer (couche 3 config)`
45. `[docs] - mention vtk-js mesh viewer as future evolution in architecture page`

### 0.3 Plan de déplacement Phase 0 étape 8 (création `dev_notes/`)

| Source | Destination |
|---|---|
| `docs/archive/BENCHMARK_PY_ANALYSIS.md` | `dev_notes/diagnostics/benchmark_py_analysis.md` |
| `docs/developers/boussinesq_petsc_headwater_100km2_diagnostic.md` | `dev_notes/diagnostics/` |
| `docs/developers/boussinesq_petsc_vs_marcais_2017.md` | `dev_notes/diagnostics/` |
| `docs/developers/documentation_illustration_audit.md` | `dev_notes/diagnostics/` |
| `docs/developers/boussinesq_linux_ci.md` | `dev_notes/diagnostics/` |
| `docs/developers/modflow6_gmsh_disv_development_perspective.md` | `dev_notes/drafts/` |
| `docs/developers/ploemeur_3d_development_perspective.md` | `dev_notes/drafts/` |
| `docs/developers/ML_ACCESS_PATTERN.md` | `dev_notes/drafts/` |
| `docs/developers/nwt_sunset_plan.md` | `dev_notes/decisions/` |
| `docs/developers/documentation_refactor_plan.md` (ce document, après Phase 0 exécutée) | `dev_notes/decisions/2026-05-05-documentation_refactor_plan.md` |
| `docs/developers/gmsh_mesh_integration_note.md` | `dev_notes/legacy/` |
| `docs/developers/Recapitulatif perlen HMP.pdf` | `dev_notes/legacy/recapitulatif_perlen_hmp.pdf` |
| `docs/examples/streamlit_app.py` | `examples/integrations/streamlit_app.py` (racine repo) avec README |

À convertir et publier dans `docs/source/developer/` (Phase 1, étape 17) :
- `architecture.md` → `architecture.rst` (matrice de couches normative)
- `design_patterns.md` → `design_patterns.rst`
- `mental_model_and_design_choices.md` → `mental_model.rst`
- `databases_and_workflows.md` + `parquet_lakehouse_architecture.md` + `parquet_lakehouse_concurrency.md` + `simulation_catalog_architecture.md` → fusion en `storage.rst`
- `schema_evolution.md` → `schema_evolution.rst`
- `CLI.md` → `cli.rst`
- `binaries.md` → `binaries.rst`
- `frontend_hooks.md` → `frontend_hooks.rst`
- `glossary.md` → `glossary.rst`
- `calibration_guide.md` → `developer/calibration_guide.rst`
- `simulation_comparison_workflow.md` → `developer/simulation_comparison_workflow.rst`
- `conda_pkg.md` → `developer/conda_pkg.rst`

À redistribuer dans `docs/source/architecture/` (Phase 1, étape 17) :
- `unified_mesh_pivot_architecture.md` → `architecture/mesh_pivot.rst`
- `gmsh_conformal_meshing.md` → `architecture/gmsh_meshing.rst`
- `boussinesq_solver_architecture.md` → `architecture/boussinesq_solver.rst`
- `modflow_contracts.md` → `architecture/modflow_contracts.rst`

### 0.4 Garde-fous critiques pour Phase 0

- **Pas de tutoriels exécutables.** Toute mention sphinx-gallery `gen_gallery` doit rester désactivée. Seul `sphinx_gallery.load_style` reste pour le CSS.
- **Pas de Codespaces / Binder.** Aucun `.binder/`, `.devcontainer/`, ni page `try_online.rst`.
- **Quarantaine notebooks, pas suppression.** `_legacy_notebooks/` reste tracké, masqué du build.
- **Slot `examples/` annoncé.** Page placeholder publique "coming soon", pas d'`:orphan:`.
- **TOML-first.** Toute page user-facing créée doit montrer un exemple TOML+CLI, pas Python direct.
- **Format commit.** `[tag] - imperative sentence`. Pas de body. Pas de co-author. Pas de mention "Phase 0", "P1", "step N", etc.
- **Branche.** Rester sur `dev-docs`. Ne pas créer de nouvelle branche, ne pas ouvrir de PR, ne pas push.

### 0.5 Action utilisateur en attente (parallèle)

Pendant que la refonte tourne, Bastien peut soumettre la candidature Algolia DocSearch :
- URL : https://docsearch.algolia.com/apply/
- Documentation URL à indiquer : `https://hydromodpy.readthedocs.io/en/dev/`
- Préciser dans Comments : doc active sur branche `dev`, `master` obsolète, ne pas crawler `master`

Réponse attendue 2 à 4 semaines. Quand acceptation reçue, intégration en Phase 3 (étape 40).

### 0.6 Mode opérationnel pour la nouvelle session Claude Code

- Modèle : Opus 4.7 (1M context). Nécessaire pour tenir le contexte multi-fichiers cohérent.
- Build local : `make livehtml` après l'étape 10 de Phase 0. Pas de cycle RTD pour l'itération.
- **Parallélisme = `-j auto` sur sphinx, PAS subagents Claude.** Toute invocation `python -m sphinx` doit passer `-j auto`. `make html` et `make livehtml` héritent du défaut `SPHINXOPTS ?= -j auto`. Lancer des subagents en parallèle pour fragmenter une étape de refactor n'est pas le sens voulu : exécuter les étapes séquentiellement sur la session principale et veiller à ce que chaque build sphinx utilise tous les cœurs.
- Ordre d'exécution : Phase 0 séquentielle (10 commits), puis Phase 1 (12 commits), puis Phase 2 et 3 selon priorité.
- Validation entre commits : `mamba activate hmp_refact && make html` doit passer sans warning nouveau.
- En cas de doute sur une décision, **cette section 0 prime sur le reste du document**.

---

## 1. Objectif du document

Fournir une référence unique et actionnable couvrant :

1. L'état actuel de la documentation (constats de l'audit).
2. Les décisions arrêtées sur la techno, l'hébergement, le thème et le format.
3. L'architecture cible (arborescence, ce qui est gardé, modifié, supprimé).
4. La réorganisation de la capability gallery.
5. Les leviers de mise en page et CSS pour améliorer la lisibilité du contenu
   scientifique dense.
6. Un plan de migration séquencé, chaque étape étant commitable indépendamment.

C'est la source de vérité pour la refonte. À mettre à jour au fil des
décisions.

---

## 2. État actuel — synthèse de l'audit

### 2.1 Pile et build

- Sphinx 7.2.6, thème `pydata-sphinx-theme==0.15.4`.
- Point d'entrée du build : `.readthedocs.yaml` -> `docs/readthedocs/source/conf.py`.
- Extensions actives : `autodoc`, `autosummary`, `autodoc_pydantic`, `myst-parser`
  (chargé mais inutilisé dans les pages utilisateur), `nbsphinx`
  (`execute="never"`), `sphinx_gallery` (style uniquement, pas de génération
  auto), `sphinx_design`, `sphinx_copybutton`, `sphinx_togglebutton`,
  `sphinx_tabs`, `sphinx_multiversion`, `plantuml` (conditionnel).
- Pas d'`intersphinx`. Remplacé par 30+ règles `nitpick_ignore_regex`.
- `autodoc_mock_imports` est défini deux fois dans `conf.py` (lignes 137 et
  485). La seconde liste écrase silencieusement la première.
- Dépendances doc déclarées à deux endroits (`pyproject.toml [docs]` et
  `docs/readthedocs/readthedocs_requirements.txt`), partiellement
  désynchronisées.

### 2.2 Inventaire des dossiers

| Chemin | Volume | Rôle | État |
|---|---|---|---|
| `docs/readthedocs/source/` | tronc Sphinx complet | source vivante | vivant |
| `docs/readthedocs/build/` | 16 Mo HTML local | artefact de build | hors git, OK |
| `docs/readthedocs/_build_dummy/` | 3 fichiers CSS/JS | rôle obscur | commité, doublon |
| `docs/_build_dummy/` | 3 fichiers identiques | rôle obscur | commité, doublon |
| `docs/developers/` | 30 fichiers, 4 Mo | notes dev | vivant, partiellement redondant |
| `docs/examples/` | 1 fichier `streamlit_app.py` | intégration externe | minimal mais récent |
| `docs/archive/` | 1 fichier `BENCHMARK_PY_ANALYSIS.md` | note diagnostic | utile, à garder |
| `docs/community/` | 1 fichier `meeting notes.txt` | notes de réunion | hors périmètre doc |
| `docs/links/` | 1 fichier `useful links.txt` | liste d'URL | redondant avec README |

### 2.3 Mode de génération par section

| Section | Mode | Coût maintenance |
|---|---|---|
| `api/` (16 pages maîtresses + ~140 stubs dans `generated/`) | hybride manuel + autosummary, pas de `:recursive:` | élevé |
| `architecture/` (9 sous-dossiers) | 100 % manuel | élevé |
| `scientific/` (~55 fichiers, équations LaTeX) | 100 % manuel | élevé |
| `user_guide/` (~70 fichiers, très granulaire) | 100 % manuel | élevé |
| `capability_gallery/cases/` (85 cas) | 100 % auto via `tools/doc_gallery/` | faible |
| `notebooks/` (12 `.ipynb`) | manuel + script `update_example_parameters.py` | très élevé, figés sur API legacy |

### 2.4 Problèmes critiques

**Bloquants :**

1. **Notebooks silencieusement faux.** Les 12 `.ipynb` importent
   `from hydromodpy.watershed import Watershed` (module supprimé) et
   utilisent l'API impérative pré-Pydantic (`BV.settings.update_hk(...)`).
   `nbsphinx_execute = "never"` masque la rupture au build. Le code
   copié-collé par un lecteur échoue immédiatement. Régénération impossible
   depuis un clone propre car `examples_legacy/` n'est pas dans le repo.
2. **API ref sans `:recursive:`.** Chaque nouveau symbole public doit être
   ajouté à la main dans une page maîtresse. Les couches `core`, `physics`,
   `analysis`, `solver.modflow6`, `solver.boussinesq` sont quasi non
   couvertes. Aucun CI ne vérifie l'exhaustivité.
3. **Diagrammes architecture obsolètes.** `architecture/index.rst` liste
   encore `|-- pipeline/` comme package existant. `data_definition_transfer_class.wsd`
   référence `DataManagersPlanner`, renommé `DataPlanner` dans le code.
   Interdit par `CLAUDE.md` (no legacy code, no ghost references).

**Structurels :**

4. **Frontières floues** entre `getting_started/`, `user_guide/`,
   `scientific/`, `architecture/`, `developers/`. Six fichiers de
   `getting_started/` sont adoptés par `user_guide/index.rst` via toctree
   relatif. Le lecteur ne peut pas mapper les sections proprement.
5. **Documentation Boussinesq fragmentée** sur six fichiers à deux niveaux
   (`scientific/solvers/`, `scientific/solvers/flow/boussinesq/`).
   Duplication partielle.
6. **Pas de bibliographie formelle.** 55+ blocs `.. math::` dans
   `scientific/` sans aucun `:cite:`, sans `.bib`. Les papiers de l'équipe
   sont listés uniquement sur la page d'accueil.
7. **`user_guide/data/` trop granulaire.** Pages feuilles de 12-13 lignes
   (`forcing/wind/sim2.rst`, `forcing/etp/sim2.rst`, etc.) qui apparaissent
   dans la nav sans rien apporter.
8. **`developers/` doublon thématique** avec `source/architecture/`. Mêmes
   sujets (calibration, mesh, solveurs, simulation) traités aux deux
   endroits sans articulation déclarée.

**Pollution :**

9. **`docs/_build_dummy/` et `docs/readthedocs/_build_dummy/`** : six
   fichiers identiques commités, sans référence dans `conf.py`. Probable
   workaround mort.
10. **`docs/community/meeting notes.txt`** et
    **`docs/links/useful links.txt`** : hors périmètre d'une doc technique
    versionnée.

---

## 3. Forces à préserver

1. **Capability gallery** (85 cas auto-générés). Zone la mieux conçue de la
   doc. Reproductibilité (commandes affichées), traçabilité (source pointers
   et hashes), fraîcheur (timestamps des batch runs). Garder la logique et les
   garanties actuelles, sans figer l'arborescence, la navigation, les templates
   ou l'UI.
2. **Qualité du contenu `scientific/`**. Vraie référence mathématique
   (Boussinesq, Dupuit, opérateur résiduel, comparaison numérique Marcais
   2017). L'identité scientifique du projet vit ici.
3. **`docs/developers/architecture.md`**. Matrice de couches 14x14 propre, à
   jour, gate CI prévue. Vraie source de vérité.
4. **`getting_started/cli-quickstart.rst`**. Neuf étapes opérationnelles, un
   nouveau venu lance un workflow en moins de 10 minutes.
5. **`index.rst` page d'accueil**. Citation IAH 2024, grille de dix cartes,
   parcours "First visit" cohérent.

---

## 4. Décisions arrêtées (session du 2026-05-05)

### 4.1 Techno

- **Sphinx** : conservé. Pas d'alternative sérieuse pour un package Python
  scientifique avec modèles Pydantic v2, notebooks, citations BibTeX et
  besoins intersphinx. MkDocs/Material est plus faible sur l'auto-doc
  Pydantic. Quarto est plus faible sur l'API ref Python. JupyterBook est
  juste Sphinx avec un autre thème.
- **ReadTheDocs** : conservé. Le dropdown multi-versions via
  `sphinx_multiversion` est l'atout décisif pour un logiciel scientifique
  citable. GitHub Pages plus Actions reste une option future si la lenteur
  de build de RTD devient gênante.
- **Thème `pydata-sphinx-theme`** : conservé. Utilisé par NumPy, SciPy,
  pandas, scikit-learn. Porte l'identité scientifique. Les limites de mise
  en page (zone de contenu étroite pour les tableaux denses) sont traitées
  via CSS, pas par un changement de thème.
- **RST** : conservé partout. Les fichiers existants restent en RST. Les
  nouveaux fichiers en RST. Migration MyST non justifiée par le churn de
  maintenance qu'elle coûterait. `myst-parser` reste chargé pour
  flexibilité future, mais aucune page `.md` n'est ajoutée dans les
  sections user-facing.

### 4.2 Conventions de rédaction

- Toutes les pages user-facing : RST, contenu en anglais. Le français est
  interdit dans le code et la doc. (La langue d'échange utilisateur-assistant
  reste le français selon `CLAUDE.md`.)
- Noms de fichiers : snake_case. Underscores, pas tirets, dans les nouveaux
  fichiers RST (les fichiers existants à tirets sont conservés pour éviter
  le churn).
- Équations LaTeX : blocs `.. math::` pour l'affichage, `:math:` pour le
  inline. Garder le style actuel.
- Cross-références : `:doc:`, `:ref:`, `:func:`, `:class:` utilisés de
  manière cohérente.
- Tableaux : `.. list-table::` préféré aux grid tables pour la
  maintenabilité.

---

## 5. Architecture cible

### 5.1 Arborescence

```
docs/
|-- source/                           # racine Sphinx unique, plus de wrapper readthedocs/
|   |-- conf.py
|   |-- index.rst
|   |
|   |-- getting_started/              # onboard < 30 min
|   |   |-- index.rst
|   |   |-- install.rst
|   |   |-- cli_quickstart.rst        # ex-getting_started/cli-quickstart.rst
|   |   `-- first_simulation.rst      # ex-simulation-walkthrough.rst
|   |
|   |-- user_guide/                   # comment utiliser
|   |   |-- index.rst
|   |   |-- concepts/                 # modes, project/run, workspace
|   |   |-- workflows/                # une page par famille de workflow
|   |   |-- data/                     # CONSOLIDER, max 2 niveaux
|   |   `-- recipes/                  # cookbook (snippets ciblés)
|   |
|   |-- tutorials/                    # sphinx-gallery sur scripts .py
|   |   |-- 01_basic_simulation.py
|   |   |-- 02_calibration.py
|   |   `-- ...                       # exécutés au build, sorties fraîches
|   |
|   |-- gallery/                      # capability gallery, RÉORGANISÉE (cf. section 6)
|   |   |-- index.rst
|   |   |-- 1_support/
|   |   |-- 2_mesh/
|   |   |-- 3_simulation/
|   |   |-- 4_validation/
|   |   `-- 5_calibration/
|   |
|   |-- theory/                       # ex-scientific/, référence scientifique
|   |   |-- index.rst
|   |   |-- foundations.rst
|   |   |-- flow_equations.rst
|   |   |-- boussinesq.rst            # UNE page consolidée
|   |   |-- modflow.rst
|   |   |-- streams_seepage.rst
|   |   |-- calibration_methods.rst
|   |   `-- references.bib            # BibTeX unique
|   |
|   |-- api/                          # 100 % auto
|   |   |-- index.rst                 # autosummary :recursive: sur hydromodpy
|   |   `-- generated/                # gitignored
|   |
|   |-- architecture/                 # vue contributeur, haut niveau
|   |   |-- index.rst                 # diagramme des 14 couches
|   |   |-- layer_matrix.rst          # généré depuis layer_matrix.yaml
|   |   |-- data_flow.rst
|   |   |-- solver_backends.rst
|   |   `-- calibration_engine.rst
|   |
|   |-- developer/                    # PUBLIÉ : contributor docs stables uniquement
|   |   |-- index.rst
|   |   |-- design_patterns.rst       # ex developers/design_patterns.md
|   |   |-- mental_model.rst          # ex developers/mental_model_and_design_choices.md
|   |   |-- storage.rst               # fusion databases_and_workflows + parquet_lakehouse_*
|   |   |-- schema_evolution.rst
|   |   |-- testing.rst               # nouveau
|   |   |-- contributing.rst          # nouveau
|   |   |-- cli.rst                   # ex developers/CLI.md
|   |   |-- binaries.rst
|   |   |-- release.rst               # nouveau
|   |   `-- frontend_hooks.rst
|   |
|   |-- changelog.rst
|   |-- _static/
|   `-- _templates/
|
|-- README.md                         # comment builder la doc
`-- _build/                           # gitignored
```

Et **hors `docs/`**, à la racine du repo, un dossier dédié aux notes
internes versionnées mais non publiées :

```
dev_notes/                            # NON PUBLIÉ, versionné dans git
|-- README.md                         # explique le rôle de chaque sous-dossier
|-- decisions/                        # ADR, plans de refonte, choix structurants
|   |-- documentation_refactor_plan.md
|   |-- nwt_sunset_plan.md
|   `-- ...
|-- diagnostics/                      # analyses ponctuelles
|   |-- benchmark_py_analysis.md      # ex docs/archive/BENCHMARK_PY_ANALYSIS.md
|   |-- boussinesq_petsc_headwater_100km2_diagnostic.md
|   |-- boussinesq_petsc_vs_marcais_2017.md
|   `-- documentation_illustration_audit.md
|-- drafts/                           # work in progress, perspectives, plans non arrêtés
|   |-- modflow6_gmsh_disv_development_perspective.md
|   |-- ploemeur_3d_development_perspective.md
|   |-- ML_ACCESS_PATTERN.md
|   `-- ...
`-- legacy/                           # historique préservé pour traçabilité
    |-- gmsh_mesh_integration_note.md
    |-- recapitulatif_perlen_hmp.pdf
    `-- ...
```

### 5.2 Trois zones distinctes (clarification critique)

`docs/` n'est pas un fourre-tout pour tout ce qui est lié à la doc. Il faut
distinguer :

| Zone | Localisation | Statut | Contenu |
|---|---|---|---|
| Doc publique | `docs/source/` | publiée sur RTD | tout ce qui est destiné aux utilisateurs et contributeurs externes |
| Notes internes | `dev_notes/` (racine du repo) | versionnée mais non publiée | drafts, diagnostics, ADR, plans, perspectives, audits |
| Hors repo | Google Drive d'équipe / wiki interne | hors git | notes de réunion, infos confidentielles, contenu éphémère |

**Critère pour publier ou non dans `docs/source/developer/`** :

- Stable + utile à un contributeur externe + référence des APIs publiques
  -> publié.
- Working draft + diagnostic ponctuel + plan ou perspective interne ->
  `dev_notes/`.
- Notes de réunion + brouillons collaboratifs + contenu éphémère -> hors
  repo entièrement.

Cette distinction est non négociable. Mélanger les trois dans `docs/` brouille
la frontière "qu'est-ce qui est public" et expose involontairement du
contenu interne.

### 5.3 Ce qui est gardé, modifié, supprimé

**Conservé comme contrat :**

- `tools/doc_gallery/` et tout le pipeline de génération. C'est le joyau de
  la doc : garder le périmètre de cas, les métriques, les commandes, les liens
  source, les hashes, les timestamps et les liens vers les configs. Le code du
  générateur, les templates, l'arborescence et l'UI peuvent être refactorés.
- `_static/capability_gallery/` (263 PNG, 108 JSON). Contenu à préserver, mais
  chemins et formats peuvent évoluer si les pages et redirects restent
  cohérents.
- `_templates/autosummary/{class,module,function}.rst`. Templates propres.
- `validation_cases/` et le lien depuis les cas gallery vers les configs
  TOML.
- `docs/developers/architecture.md`. Source normative de la matrice de
  couches. À publier dans `docs/source/developer/architecture.rst`.

**Déplacé vers `dev_notes/` (versionné, non publié) :**

- `docs/archive/BENCHMARK_PY_ANALYSIS.md` -> `dev_notes/diagnostics/`.
- `docs/developers/boussinesq_petsc_headwater_100km2_diagnostic.md` ->
  `dev_notes/diagnostics/`.
- `docs/developers/boussinesq_petsc_vs_marcais_2017.md` ->
  `dev_notes/diagnostics/`.
- `docs/developers/documentation_illustration_audit.md` ->
  `dev_notes/diagnostics/`.
- `docs/developers/modflow6_gmsh_disv_development_perspective.md` ->
  `dev_notes/drafts/`.
- `docs/developers/ploemeur_3d_development_perspective.md` ->
  `dev_notes/drafts/`.
- `docs/developers/ML_ACCESS_PATTERN.md` -> `dev_notes/drafts/`.
- `docs/developers/nwt_sunset_plan.md` -> `dev_notes/decisions/`.
- `docs/developers/gmsh_mesh_integration_note.md` -> `dev_notes/legacy/`.
- `docs/developers/Recapitulatif perlen HMP.pdf` -> `dev_notes/legacy/`.
- Le présent `documentation_refactor_plan.md` -> `dev_notes/decisions/`.

**Déplacé vers `examples/` à la racine du repo :**

- `docs/examples/streamlit_app.py` -> `examples/integrations/streamlit_app.py`
  avec un petit README.

**Publié dans `docs/source/developer/` (sous-ensemble stable de
`docs/developers/`) :**

- `architecture.md` -> `architecture.rst` (matrice de couches, normatif).
- `design_patterns.md` -> `design_patterns.rst`.
- `mental_model_and_design_choices.md` -> `mental_model.rst`.
- `databases_and_workflows.md` + `parquet_lakehouse_architecture.md` +
  `parquet_lakehouse_concurrency.md` + `simulation_catalog_architecture.md`
  -> fusionnés en `storage.rst`.
- `schema_evolution.md` -> `schema_evolution.rst`.
- `CLI.md` -> `cli.rst`.
- `binaries.md` -> `binaries.rst`.
- `frontend_hooks.md` -> `frontend_hooks.rst`.
- `glossary.md` -> `glossary.rst` (fusionné avec un nouveau glossaire
  dédié, voir section 12.2).
- `unified_mesh_pivot_architecture.md` + `gmsh_conformal_meshing.md` +
  `boussinesq_solver_architecture.md` + `modflow_contracts.md` ->
  redistribués dans `docs/source/architecture/` (vue contributeur, haut
  niveau).

**Modifié :**

- `getting_started/` : garder cinq fichiers cœur dans le toctree, déplacer
  les six orphelins vers `user_guide/concepts/`.
- `user_guide/data/` : ramener à deux niveaux maximum. Fusionner les pages
  feuilles de moins de 20 lignes dans leur parent. Supprimer les pages
  quasi-vides (`forcing/wind/sim2.rst`, `forcing/etp/sim2.rst`, etc.).
- `scientific/` -> `theory/` : renommer, consolider Boussinesq dans une
  seule page, ajouter `references.bib`.
- `api/` : passer à `autosummary :recursive:` sur le package `hydromodpy`.
  Supprimer les 16 pages maîtresses maintenues à la main, remplacer par un
  seul index.
- `architecture/` : reconstruire autour des vraies couches (`core`,
  `schema`, `physics`, `data`, `spatial`, `simulation`, `solver`,
  `calibration`, `results`, `display`, `analysis`, `workflow`, `config`,
  `_cli`). Supprimer le fantôme `pipeline/`. Corriger
  `data_definition_transfer_class.wsd` pour utiliser `DataPlanner`.
- `notebooks/` : 12 `.ipynb` figés retirés de la nav. Remplacés par 4-6
  scripts `tutorials/*.py` exécutés au build via `sphinx-gallery`.
- `developers/` : démantelé et redistribué selon le critère public/interne
  (cf. section 5.2). Sous-ensemble stable -> `docs/source/developer/`.
  Drafts/diagnostics/perspectives -> `dev_notes/`. Plus de dossier
  `developers/` dans `docs/` après la migration.

**Supprimé :**

- `docs/_build_dummy/` et `docs/readthedocs/_build_dummy/`. Six fichiers
  commités sans référence dans `conf.py`. Probable workaround mort.
  Suppression via `git rm -r`.
- `docs/community/meeting notes.txt`. À déplacer sur le Drive d'équipe,
  retirer du repo.
- `docs/links/useful links.txt`. Redondant avec le README, supprimer.
- Wrapper `docs/readthedocs/`. Remonter `source/` en `docs/source/`. Mettre
  à jour `.readthedocs.yaml`.
- Les 12 `notebooks/example_XX.ipynb`. Référencent l'API supprimée
  `Watershed`. Remplacés par les tutoriels sphinx-gallery.
- Les 16 pages maîtresses dans `api/` (`hydromodpy-config.rst`,
  `hydromodpy-data.rst`, etc.). Remplacées par autosummary recursive.

---

## 6. Réorganisation de la capability gallery

État actuel : 9 catégories, très déséquilibrées. `mesh/` à lui seul porte 29
cas (un tiers de la gallery) sur une page de 865 lignes.

| Catégorie actuelle | Cas | PNG | Lignes landing |
|---|---|---|---|
| mesh | 29 | 53 | 865 (anomalie) |
| validation | 24 | 85 | 347 |
| simulation | 7 | 17 | 140 |
| simulation_comparison | 6 | 6 | 118 |
| calibration | 5 | 73 | 138 (plus deux pages additionnelles de 183 et 252 lignes) |
| hydraulic_properties | 5 | 7 | 74 |
| geographic | 4 | 13 | 117 |
| geometry | 3 | 3 | 53 |
| code_comparison | 2 | 6 | 48 |

### 6.1 Symptômes

1. `mesh/` est obèse.
2. Trois catégories chevauchent "vue pré-solveur du bassin" :
   `geographic` (4), `geometry` (3), `hydraulic_properties` (5). Douze cas
   répartis arbitrairement.
3. Deux catégories chevauchent "comparer des solveurs" :
   `code_comparison` (2), `simulation_comparison` (6). Huit cas, frontière
   floue.
4. Trois fichiers calibration au top niveau (`calibration.rst`,
   `calibration_data_rich_no_uncertainty.rst`,
   `calibration_uncertain_less_data.rst`). Entrée confuse.
5. Naming hérité : quatre `ex12_*` plus deux `example12_*`.

### 6.2 Cible — 5 catégories, regroupement par intent conservé

```
gallery/
|-- index.rst                          # 3 intents conservés (Build / Run / Validate)
|
|-- 1_support/                         # ex-geographic + geometry + hydraulic_properties
|   |-- index.rst                      # 12 cas en 3 sections
|   |-- basin_overview/                # ex-geographic (4)
|   |-- geometry_diagnostics/          # ex-geometry (3)
|   `-- hydraulic_properties/          # ex-hydraulic_properties (5)
|
|-- 2_mesh/                            # ex-mesh, SOUS-DIVISÉ
|   |-- index.rst                      # 29 cas en 3-4 familles
|   |-- structured/                    # mesh régulier
|   |-- unstructured/                  # triangles, voronoi
|   |-- nested_refinement/             # raffinements
|   `-- geology_layers/                # extrusion verticale
|
|-- 3_simulation/                      # ex-simulation + simulation_comparison + code_comparison
|   |-- index.rst                      # 15 cas en 2 sections
|   |-- single_runs/                   # ex-simulation (7)
|   `-- comparisons/                   # ex-simulation_comparison + code_comparison (8)
|
|-- 4_validation/                      # inchangé, déjà bien sous-divisé en 8 familles
|   `-- ...                            # 24 cas
|
`-- 5_calibration/                     # 3 fichiers calibration FUSIONNÉS
    |-- index.rst                      # 5 cas, scénarios en sections internes
    `-- ...                            # data_rich, uncertain, etc. en sections, pas en pages
```

### 6.3 Effets

- 9 catégories ramenées à 5.
- `mesh/` éclaté en 4 sous-familles. La page de 865 lignes devient quatre
  pages de ~200 lignes.
- Comparaisons unifiées sous un seul mental model.
- Calibration plate : une page d'entrée, scénarios en sections internes.
- Renames `ex12_*` et `example12_*` vers une convention unique pendant le
  déplacement.

### 6.4 Modifications du générateur

Tout le travail se fait dans `tools/doc_gallery/` :

- Mettre à jour le schéma de manifest pour autoriser une structure
  catégorie/sous-famille imbriquée.
- Réécrire le générateur RST pour émettre la nouvelle arborescence.
- Corriger le bug de tronquage des descriptions (cards qui finissent par
  ":" parce que la première ligne d'un paragraphe est coupée à la première
  rupture de phrase).
- Ajouter des thumbnails `:img-top:` aux grid cards des landing pages de
  catégorie.
- Ajouter une page "All cases" triable, générée automatiquement avec
  colonnes : solveur, dimension, régime, RMSE, date du dernier run.
- Renommer les fichiers PNG de `_static/capability_gallery/` selon la
  nouvelle arborescence.

Effort : environ une journée de travail, contenu inchangé.

### 6.5 Contrat de migration gallery

La réorganisation peut déplacer, renommer et améliorer les pages, mais elle ne
doit pas appauvrir la gallery :

- Aucun cas existant n'est supprimé sans décision explicite.
- Toutes les commandes, configs TOML, source pointers, hashes, timestamps,
  métriques, figures et acceptance criteria restent accessibles.
- Les anciennes URLs de pages sont redirigées vers les nouvelles.
- Une page "All cases" permet de retrouver tous les cas après la
  réorganisation.
- Un check compare le nombre de cas, figures, JSON summaries et liens TOML
  avant/après migration.

---

## 7. Mise en page et leviers CSS

### 7.1 Pourquoi ça compte

`pydata-sphinx-theme` a une zone de contenu de ~900-1000 px par défaut. Les
pages cas de la gallery ont des tableaux denses 4 colonnes (largeurs
26-42-20-12 %) plus 4 onglets par solveur. Les tableaux débordent ou
s'enroulent mal sur un laptop standard.

Deux stratégies, utilisées ensemble :

- Élargir la zone de contenu globale.
- Retirer sélectivement les sidebars sur les pages denses.

### 7.2 Leviers, par ratio impact / effort

#### Niveau 1 — Options du thème dans `conf.py`

```python
html_theme_options = {
    "show_toc_level": 2,
    "navigation_depth": 3,
    "secondary_sidebar_items": ["page-toc", "edit-this-page"],
    "primary_sidebar_end": [],
    "use_edit_page_button": True,
    "header_links_before_dropdown": 5,
}
```

#### Niveau 2 — Métadonnées par page

Pour les pages cas de la gallery avec tableaux denses, désactiver la
sidebar droite gagne ~250 px d'horizontale :

```rst
:html_theme.sidebar_secondary.remove:

Titre du cas
============
```

Pour cacher aussi la sidebar gauche :

```rst
:html_theme.sidebar_primary.remove:
:html_theme.sidebar_secondary.remove:
```

Ces métadonnées sont non destructives et s'appliquent page par page. Le
générateur `tools/doc_gallery/` doit les émettre sur les pages cas.

#### Niveau 3 — CSS custom dans `_static/custom.css`

Le levier le plus puissant. Recettes adaptées à HydroModPy :

```css
/* Élargir la zone de contenu globalement */
.bd-container__inner,
.bd-page-width,
.bd-main .bd-content .bd-article-container {
    max-width: 1400px;
}

/* Tableaux : scroll horizontal si trop large, plutôt que casse de mise en page */
table.docutils {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
}
table.docutils.list-table {  /* garder le wrap sur list-table */
    white-space: normal;
}

/* Police plus petite dans les list-table très denses */
.gallery-params table.docutils {
    font-size: 0.85em;
}

/* Figures gallery : forcer 100% de largeur */
.bd-content .figure img,
.bd-content figure img {
    max-width: 100%;
    height: auto;
}

/* Descriptions de cards : clamp à 3 lignes, évite le bug des ":" en queue */
.sd-card-body p {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
```

Activé dans `conf.py` :

```python
html_css_files = [
    "api-reference.css",
    "uml-diagrams.css",
    "custom.css",
]
```

#### Niveau 4 — Pages full bleed

Pour les pages très visuelles (landing gallery avec hero) :

```css
.bd-content.full-bleed { max-width: none; }
.bd-content.full-bleed .bd-article {
    padding-left: 2rem;
    padding-right: 2rem;
}
```

Activé page par page via une raw HTML escape si nécessaire.

#### Niveau 5 — Refactor des pages cas denses

Chaque cas de gallery empile actuellement quatre tableaux verticalement
(Common Setup / Solver Overrides / Acceptance / Acceptance by Solver). Les
emballer dans un seul `tab-set` extérieur par solveur, avec sections
internes Setup / Overrides / Acceptance. Réduit le scroll vertical de ~50 %.

Implémentation : modifier le template RST dans `tools/doc_gallery/`.

### 7.3 Synthèse priorité / impact

| Action | Effort | Impact visuel |
|---|---|---|
| Élargir `.bd-container__inner` à 1400 px | 5 min | Élevé sur tous les tableaux |
| Ajouter `:html_theme.sidebar_secondary.remove:` aux pages cas | 1 h (générateur) | Très élevé sur la gallery |
| `overflow-x: auto` sur `table.docutils` | 5 min | Élimine les débordements |
| Refactor `tab-set` imbriqués dans pages cas | 1 jour (générateur) | -50 % scroll vertical |

Premier batch recommandé (~1h30 au total) : les trois premières lignes. Non
destructif, effet immédiat, résout 80 % du problème de tableaux serrés.

---

## 8. Autres correctifs techniques (groupés avec la migration)

1. **Déduplication de `autodoc_mock_imports`** dans `conf.py`. Supprimer la
   seconde liste statique ligne 485, garder la dynamique ligne 137.
2. **Extension de `source_suffix`** : passer à `[".rst", ".md"]` pour que
   tout fichier `.md` qui existe déjà dans `developer/` soit correctement
   indexé par Sphinx.
3. **Dépendances doc** : choisir une source unique. Garder
   `docs/readthedocs/readthedocs_requirements.txt` comme fichier canonique
   d'épinglage pour RTD. Dans `pyproject.toml [docs]`, référencer les mêmes
   versions ou supprimer la section. Retirer `sphinx-rtd-theme` des deux,
   le thème réel étant `pydata-sphinx-theme`.
4. **Configuration `intersphinx`** : activer `sphinx.ext.intersphinx`,
   configurer les mappings vers NumPy, SciPy, pandas, matplotlib, flopy.
   Supprimer la liste de 30+ `nitpick_ignore_regex` une fois les
   cross-refs résolues.
5. **Configuration `sphinx_multiversion`** : ajouter des patterns explicites
   `smv_tag_whitelist` et `smv_branch_whitelist` dans `conf.py` pour
   contrôler quelles versions apparaissent dans le dropdown.
6. **Bibliographie** : ajouter `sphinxcontrib-bibtex`, créer
   `theory/references.bib`, commencer par citer dans les pages Boussinesq
   et calibration.
7. **Gate CI pour la complétude API** : un test sous
   `tests/unit/architecture/` qui vérifie que tout symbole public de chaque
   `__init__.py` de couche est référencé dans au moins un `.rst` sous
   `api/`.

---

## 9. Outils Sphinx complémentaires

Inventaire des extensions à activer pour atteindre une doc scientifique
moderne. Triées par ratio impact/effort.

### 9.1 Tier 1 — Recommandations fortes

#### `sphinx-codeautolink`

Transforme chaque appel dans un bloc de code Python en lien cliquable vers
l'API ref. Chaque `HydroModPyConfig`, `.flow`, `.param`, `.K` devient
navigable sans annotation manuelle. Énorme gain UX sur les tutoriels et le
user_guide.

```python
extensions += ["sphinx_codeautolink"]
codeautolink_concat_default = True
codeautolink_global_preface = "import hydromodpy"
```

#### `sphinx-hoverxref`

Tooltips de prévisualisation au survol sur tous les `:doc:`, `:ref:`,
`:class:`, `:func:`. Le lecteur n'a plus à cliquer pour vérifier "c'est quoi
`DataPlanner`". Compatible nativement RTD.

```python
extensions += ["hoverxref.extension"]
hoverxref_role_types = {
    "class": "tooltip",
    "func": "tooltip",
    "ref": "modal",
    "doc": "modal",
    "cite": "tooltip",
}
hoverxref_domains = ["py"]
hoverxref_intersphinx = ["numpy", "scipy", "pandas", "matplotlib"]
```

Alternative : `sphinx-tippy` (plus joli, indépendant de RTD).

#### `sphinxcontrib-mermaid`

Diagrammes flowchart / sequence / state en JS côté client, sans Java
(contrairement à PlantUML). PlantUML reste pour les diagrammes UML
détaillés (`.wsd`), Mermaid pour le reste.

```rst
.. mermaid::

   flowchart LR
     Config --> DataPlanner --> Simulation
     Simulation --> Solver --> Results
```

#### `sphinx-jsonschema`

Rend les JSON Schema en tableaux navigables. Vous avez déjà
`hmp schema export` qui produit le schéma de `HydroModPyConfig`. Au lieu de
maintenir manuellement les tableaux de description des champs, le schéma
devient la source unique :

```rst
.. jsonschema:: ../../schema_export.json
   :pointer: /properties/flow
```

Élimine ~200 lignes de tableaux RST maintenus à la main.

#### `sphinx-autodoc-typehints`

Améliore le rendu des type hints partout sauf dans les modèles Pydantic
(déjà gérés par `autodoc-pydantic`). Pour vos fonctions et classes
non-Pydantic, les annotations deviennent lisibles avec liens
automatiques.

```python
extensions += ["sphinx_autodoc_typehints"]
typehints_fully_qualified = False
always_document_param_types = True
typehints_document_rtype = True
```

#### `sphinx-issues`

Roles `:issue:` et `:pr:` pour le changelog et les notes de version :

```python
extensions += ["sphinx_issues"]
issues_github_path = "BastienBoivin/HydroModPy"
```

```rst
- Fix Boussinesq solver convergence on irregular meshes (:pr:`342`, :issue:`318`)
```

#### `sphinxext-opengraph`

Génère les balises Open Graph pour les partages Slack, Twitter, GitHub.
Image, titre, description automatiques.

```python
extensions += ["sphinxext.opengraph"]
ogp_site_url = "https://hydromodpy.readthedocs.io/"
ogp_image = "_static/og-image.png"
ogp_use_first_image = True
```

#### `sphinx-rediraffe`

Critique pour la refonte : maintient un fichier `redirects.txt` qui mappe
les anciennes URLs vers les nouvelles. Évite que les liens cités dans des
papiers ne cassent.

```python
extensions += ["sphinxext.rediraffe"]
rediraffe_redirects = "redirects.txt"
rediraffe_branch = "master~1"
```

```
# redirects.txt
scientific/index                                      theory/index
scientific/solvers/boussinesq-mathematical-notes      theory/boussinesq
notebooks/example_01                                  tutorials/01_basic_simulation
```

#### `sphinxcontrib-bibtex`

Bibliographie BibTeX avec `:cite:` dans les pages scientifiques. Voir
section 8.6.

### 9.2 Tier 2 — Utiles selon contexte

| Extension | Utilité |
|---|---|
| `sphinx-notfound-page` | Page 404 custom multi-version aware |
| `sphinx-favicon` | Favicons multi-plateformes (Apple Touch, Android, etc.) |
| `sphinx-sitemap` | `sitemap.xml` pour SEO |
| `sphinx-paramlinks` | `:paramref:` pour cibler un argument spécifique |
| `sphinxcontrib-spelling` | Vérification orthographique en CI |
| `sphinx-version-warning` | Bandeau sur les pages de versions obsolètes |
| `sphinx-github-changelog` | Génère `changelog.rst` depuis les GitHub releases |
| `sphinx-last-updated-by-git` | Date de dernière modif par page (via git log) |
| `sphinx-prompt` | Typographie shell prompts (`$`, `>>>`, `In [1]:`) |
| `sphinxcontrib-youtube` | Embed vidéos YouTube/Vimeo facilement |
| `numpydoc` | Rendu docstrings NumPy-style (à vérifier si déjà actif) |

### 9.3 Tier 3 — À considérer plus tard

| Extension | Utilité | Verdict |
|---|---|---|
| `sphinx-toolbox` | Boîte à outils (assets, github, latex helpers, confval) | Utile mais ajoute du poids, à la carte |
| `sphinx-external-toc` | Toctree en YAML externe | Cleaner pour gros projets, mais churn de migration |
| `sphinx-comments` | Commentaires Hypothesis/utterances sur pages | Engagement communautaire, prématuré |
| `sphinx-thebe` | Code blocks live via Binder | À éviter, vous voulez justement éviter le live |
| `sphinx-revealjs` | Export slides Reveal.js | Pour conférences, ad hoc |
| `sphinx-needs` | Tracking d'exigences/specs | Overkill |
| `myst-nb` | Notebooks MyST hybrides | Hors scope, vous restez RST |
| `sphinx-charts` / `sphinxcontrib-vega` | Charts interactifs Vega-Lite | Joli mais maintenance lourde |
| `sphinx-iconify` | Icônes Iconify | `sphinx-design` couvre déjà via Octicons/FA |

### 9.4 À retirer

- **`sphinx-tabs`** : redondant avec `sphinx-design` qui propose `tab-set`
  plus moderne. Retirer après migration des rares `.. tabs::` restants vers
  `.. tab-set::`.
- **30+ règles `nitpick_ignore_regex`** : remplacées par `intersphinx`.

### 9.5 Directives custom à développer

#### `config-field` directive

Documente un champ Pydantic avec liens vers le schema, les valeurs par
défaut, les unités, et les cas gallery qui l'utilisent :

```rst
.. config-field:: flow.param.K.field_homogeneous.value
   :unit: m/s
   :default: 1e-4
   :see-also-cases: dupuit_fixed_head_1d, boussinesq_fixed_head_piecewise_k_1d
```

Implémentation : `tools/doc_gallery/sphinx_ext.py`, ~150 lignes.

#### `validation-case-summary` directive

Insère dans `theory/boussinesq.rst` un encadré listant tous les cas
validation qui testent ce solveur, avec leurs RMSE actuels :

```rst
.. validation-case-summary:: boussinesq
   :show-metrics: rmse, max_abs_error
```

Lit les JSON dans `_static/capability_gallery/validation/*_summary.json` et
rend un tableau triable avec liens vers chaque page cas. ~200 lignes.

#### `solver-comparison` directive

Génère une matrice solveur x cas gallery automatiquement :

```rst
.. solver-comparison::
   :solvers: modflow6, modflownwt, boussinesq
   :cases-pattern: cases/dupuit_*
```

---

## 10. UI/UX et identité scientifique

### 10.1 Page d'accueil

- **Hero illustration** : carte d'un bassin breton (Nançon, Vire-Sélune)
  en SVG, calme et identifiante. Remplace la grille de cards en haut.
- **Trois CTA visibles** : `[ Get started ]` `[ View gallery ]` `[ API reference ]`
- **Status badges** sous le titre : build passing, version, DOI Zenodo,
  license, conda-forge.
- **Citation block** : déjà présent, ajouter un copy-button BibTeX et un
  lien Zenodo.
- **News feed** court (3 derniers items du changelog) avec date.

### 10.2 Citation et reproductibilité

- **`CITATION.cff`** à la racine du repo. Lu nativement par GitHub qui
  affiche un bouton "Cite this repository".
- **DOI Zenodo** persistant pour le projet, plus un DOI par release.
- **Page "How to cite"** : BibTeX, RIS, plain text, tous avec
  copy-button.
- **Per-page DOI** sur les pages `theory/*` les plus structurelles, pour
  les rendre citables individuellement (Zenodo accepte les sous-DOI).
- **Page "Authors"** avec ORCID et affiliations.
- **Funding** : afficher les financements (ANR, EU, etc.) en bas de
  l'accueil.

### 10.3 Identité visuelle

- **Logo HydroModPy** vectoriel SVG dans `_static/logo.svg`. Versions
  light et dark.
- **Palette de couleurs** documentée dans `developer/style_guide.rst` :
  - Primaire : bleu eau `#1f6feb`
  - Secondaire : ocre roche `#d97706`
  - Accents : vert vegetation, gris substratum
  - Cohérente avec les figures matplotlib du package
- **Typographie** : `Inter` ou `IBM Plex Sans` pour le texte, `JetBrains
  Mono` pour le code. Téléchargeable en webfonts ou via Google Fonts.
- **Favicon multi-plateforme** via `sphinx-favicon` : SVG + PNG 16/32/192/512.
- **Open Graph image** : 1200x630 px avec logo + tagline.

### 10.4 Navigation

- **Breadcrumb** activé dans le thème.
- **Edit this page** déjà actif, conservé.
- **Last updated** date par page via `sphinx-last-updated-by-git`.
- **Page TOC** (sidebar droite) conservé, avec scroll-spy.
- **Skip-to-content** link pour a11y.
- **Recherche** : barre en haut, raccourci clavier `/`. RTD search v2 par
  défaut.
- **Version dropdown** : `sphinx_multiversion` configuré strictement
  (tags SemVer uniquement).

### 10.5 Feedback et engagement

- **"Was this helpful?"** widget en bas de chaque page. Clics tracés (par
  exemple Plausible Analytics, RGPD-friendly).
- **"Open issue about this page"** lien GitHub avec template pré-rempli
  (titre = "Doc: <page title>", body avec URL et version).
- **Contributors** : afficher les contributeurs git de chaque page (via
  `sphinx-last-updated-by-git`).

### 10.6 UI/UX avancée (composants riches)

Au-delà des bases (cards, tabs, breadcrumb), une série de composants
substantiels qui transforment l'expérience de lecture scientifique.

#### Blocs de code enrichis

- **Highlight de lignes** via `:emphasize-lines:` systématisé dans les
  tutoriels : pointe précisément la ligne qu'on commente.
- **Bouton "Run in Codespaces"** sur les snippets ciblés. URL
  `?devcontainer_path=...&editor=...&prefilled-content=<code>` qui ouvre
  un Codespace avec le snippet pré-collé.
- **Multi-langage tabs** : pour un même workflow, exposer CLI + Python +
  TOML en `tab-set` (déjà supporté par `sphinx-design`). Systématiser
  dans `user_guide/recipes/`.

#### Figures et images

- **Lightbox** sur toutes les figures : clic -> plein écran, zoom/pan, ESC
  pour fermer. JS custom ~30 lignes ou plugin léger.
- **Image comparison slider** pour les comparaisons A/B (MODFLOW 6 vs
  Boussinesq, mesh régulier vs irrégulier). Web component
  `img-comparison-slider` (~10 KB).
- **Screenshots annotés** : utiliser des SVG overlays avec markers
  numérotés et callouts en regard, pas des captures brutes.

#### Mathématiques

- **Copie LaTeX source** : activer le plugin `copy-tex` de KaTeX. Permet
  au lecteur scientifique de copier la formule rendue vers son éditeur.
- **Variables cliquables / hover** : associer chaque symbole d'équation
  à sa définition via `:term:` + tooltip CSS (ou widget MathJax custom).
  Précieux dans `theory/`.
- **Numérotation et cross-refs** : `.. math::` avec `:label:` permet
  `:eq:` partout. Systématiser dans les pages theory longues.

#### Navigation power-user

- **Quick-jump search Cmd+K** via **Algolia DocSearch** (gratuit pour
  open-source). Crawl automatique de RTD, popup centrale avec recherche
  fuzzy. C'est ce que NumPy, SciPy, pandas utilisent. Demande
  d'inscription : `docsearch.algolia.com/apply/`.
- **Keyboard shortcuts overlay** : `?` ouvre une modale listant les
  raccourcis (`/` search, `Cmd+K` quick-jump, `g h` home, `g a` API).
- **Anchor highlight** sur arrivée via deep link : la section visée
  s'illumine 2 secondes en couleur subtile. CSS pseudo-class `:target`.
- **Smooth scroll** sur les anchors (CSS `scroll-behavior: smooth`,
  respecté par `prefers-reduced-motion`).
- **Recently viewed pages** stockées en `localStorage`, affichées dans
  un widget de la sidebar gauche.

#### Métadonnées par page

- **Page fingerprint** en footer de chaque tutoriel et cas gallery :
  "Last verified 2026-04-30 against hydromodpy 1.2.0, MODFLOW 6.5.0".
  Auto-injecté par les générateurs `tools/doc_gallery/` et
  `sphinx-gallery`.
- **Reading time** en haut de page : "~5 min read", calculé depuis le
  word count. Plugin `sphinx-reading-time` ou hook custom.
- **Page status banner** : badge en haut indiquant "Stable" /
  "Experimental" / "Draft" / "Outdated". Roles `:stable:`,
  `:experimental:`, etc. (cf. section 14.2 sur API stability).
- **Prerequisites widget** : "You should know: :doc:`concepts`,
  :doc:`cli_quickstart`" en haut des pages avancées. Directive custom
  `.. prerequisites::`.

### 10.7 Composants spécifiques HydroModPy

Cinq composants interactifs qui n'existent dans aucune autre doc et
forment un différenciateur fort.

#### Solver capability matrix

Grille HTML triable montrant ce que chaque solveur supporte. Colonnes :
transient, unstructured, transport, calibration, 1D/2D/3D. Clic sur une
cellule -> page détaillée. Source : un YAML maintenu à la main, rendu en
HTML/CSS via une directive custom `.. solver-matrix::`.

#### Workflow flowchart cliquable

Sur la page de chaque workflow family, un diagramme Mermaid avec liens
sur chaque nœud (`load_data`, `build_mesh`, `solve`, `analyze`) qui
amène à la section config correspondante. Mermaid supporte les liens
nativement.

#### TOML field linter en ligne

Page "Validate your config" avec un éditeur **Monaco** (le moteur
VS Code) où l'utilisateur colle son TOML et obtient en temps réel les
erreurs de validation Pydantic. Le bundle JS charge le JSON Schema
exporté par `hmp config schema`. Validateur côté client via `Ajv`.
Effort : 2 jours. Différenciateur unique côté hydrogéo.

#### Geographic application map

Carte Leaflet sur la landing page ou `about/` avec marqueurs sur les
bassins où HydroModPy a tourné (Nançon, Vire-Sélune, Ploémeur, etc.).
Chaque marqueur ouvre une popup avec lien vers le cas gallery
correspondant. Tile OpenStreetMap (gratuit). Visuel scientifique fort.

#### Mesh viewer embarqué

`vtk-js` ou `pyvista-bokeh` pour afficher des meshes 3D directement
dans la page (rotation, zoom, slice). Utile dans `mesh_catchment/` et
`solver/modflow6/`. Bundle ~500 KB, lazy-loaded.

#### Calibration runtime estimator

Widget formulaire en JS pur : "Combien de paramètres / d'observations
/ quelle méthode" -> "Estimation 2-4h sur un laptop standard". Modèle
empirique calibré sur les benchmarks existants. Aide à dimensionner
avant de lancer.

### 10.8 Accessibilité poussée

- **High contrast toggle** dans la navbar (au-delà du dark/light).
- **Font size adjuster** (A+ A- A) pour usage en projecteur.
- **`prefers-reduced-motion`** respecté pour toutes les transitions CSS.
- **Color-blind palette check** en CI : valider que les figures
  matplotlib restent lisibles en deuteranopie/protanopie via
  `palette-blind-check` ou simulation maison.

### 10.9 Print et export

- **Print stylesheet** : `@media print` qui supprime sidebar/navbar,
  reformate les équations, utilise du noir sur blanc même en dark mode.
  Un chercheur qui imprime ou exporte en PDF obtient un document propre.
- **"Cite this page" widget** sur les pages theory : DOI, version, URL,
  auto-généré en BibTeX, RIS, plain text. Copyable.

### 10.10 Microinteractions

- **Toast notifications** discrètes en bas-droite pour les actions
  ("Copied to clipboard", "Schema exported"). Auto-dismiss 3s.
- **Loading skeletons** sur les widgets async (Schema Explorer pendant
  le chargement initial du JSON).
- **Hover animations** subtiles sur les cards (transform: translateY -2px
  + shadow accentuée).

### 10.11 Recherche et SEO

- **Sitemap.xml** via `sphinx-sitemap`.
- **Structured data JSON-LD** : injecter Schema.org `SoftwareApplication`
  + `ScholarlyArticle` sur les pages scientifiques. Améliore l'indexation
  Google Scholar.
- **Robots.txt** correct (déjà géré par RTD).
- **Canonical URLs** activées dans le thème pour éviter le contenu
  dupliqué entre versions.

---

## 11. Accessibilité et performance

### 11.1 Accessibilité (a11y)

- **Contrastes WCAG AA** vérifiés en dark mode et light mode (tester avec
  Lighthouse / axe-core).
- **Alt text obligatoire** sur toutes les figures. CI check via
  `sphinx-lint` ou hook custom qui parse les `.. figure::` sans `:alt:`.
- **Tableaux** : entêtes `<th>` corrects (déjà natif dans `.. list-table::
  :header-rows: 1`).
- **Navigation clavier** : tester chaque page au clavier seul. Le thème
  pydata est correct par défaut, vérifier les ajouts custom.
- **Police lisible** : minimum 1rem (16px), line-height 1.6.
- **Pas de couleur seule** comme porteur d'info. Toujours doubler par un
  symbole ou un texte.
- **`aria-label`** sur les boutons icon-only (copy, toggle dark mode).
- **`prefers-reduced-motion`** respecté pour les transitions CSS.

### 11.2 Performance

- **WebP** pour les PNG de gallery (réduction 40-60 % de taille). Pipeline :
  `tools/doc_gallery/` produit PNG + WebP, le RST référence le PNG, le
  HTML utilise `<picture>` avec fallback.
- **Lazy loading** : `loading="lazy"` sur toutes les `.. figure::` via
  patch de la directive ou CSS attribute selector.
- **Compression** : RTD compresse déjà via Cloudflare.
- **CDN** : Cloudflare devant RTD (déjà actif).
- **Build cache** : `sphinx-autobuild` en local pour itération rapide ;
  builds incrémentaux respectés (`make html` ne rebuild que ce qui a
  changé).
- **Time-to-first-byte** : viser < 200 ms. RTD est correct, mais les pages
  cas gallery très lourdes (4 figures + tableaux) peuvent dépasser. Lazy
  loading résout ça.

### 11.3 Mobile

- **Tester chaque page** en viewport 375px (iPhone SE) et 768px (iPad).
- **Tableaux** : scroll horizontal automatique (déjà prévu dans le CSS de
  la section 7).
- **Sidebar collapsible** : natif `pydata-sphinx-theme`.
- **Figures** : `max-width: 100%` sur toutes (déjà prévu).
- **Code blocks** : `overflow-x: auto`, ne jamais `word-wrap: break-word`
  sur du code.

### 11.4 Build

- **Build sans warnings** comme gate CI : `sphinx-build -W --keep-going`.
- **Build time** : monitorer via RTD analytics. Si > 10 min, optimiser
  (cache, parallel build via `-j auto`).
- **Linkcheck hebdomadaire** en CI : `sphinx-build -b linkcheck`. Détecte
  les liens externes cassés.

---

## 12. Qualité éditoriale et build

### 12.1 Style guide

Créer `developer/style_guide.rst` qui documente :

- **Ton** : factuel, concis, scientifique sans jargon inutile.
- **Voix** : "you" pour adresser le lecteur, "we" rare et collectif. Pas de
  "I".
- **Naming** dans les exemples : variables descriptives
  (`watershed_config`, pas `wc`), TOML keys en snake_case.
- **Abréviations** : développées à la première occurrence dans chaque
  page.
- **Conventions** : `MODFLOW 6` (espace), `MODFLOW-NWT` (tiret), `Pydantic
  v2` (minuscule v).

### 12.2 Glossaire

Créer `glossary.rst` avec directive Sphinx native :

```rst
.. glossary::

   Boussinesq
       Approximation hydrodynamique pour les écoulements en aquifère
       libre, négligeant la composante verticale de vitesse.

   Dupuit
       Hypothèse de proportionnalité du débit à la pente de la surface
       libre dans un aquifère libre.

   DRT
       :term:`Drain Return Topology` package de MODFLOW pour les
       résurgences.
```

Référençable partout via `:term:`Boussinesq``. Affichage automatique du
glossaire complet sur une page.

### 12.3 Linting

- **`sphinx-lint`** ou **`doc8`** en pre-commit hook.
- **`sphinxcontrib-spelling`** avec dictionnaire custom
  `tools/doc/spelling_wordlist.txt` contenant les termes scientifiques
  (Boussinesq, Brutsaert, Dupuit, Theis, Hantush, Marçais, etc.).
- **CI dédié doc** sur chaque PR : build + linkcheck + spelling +
  warnings-as-errors.

### 12.4 Redirections

- **`sphinx-rediraffe`** : maintenir `docs/source/redirects.txt`. Mis à
  jour à chaque déplacement de page.
- **Documenter la politique** dans `developer/style_guide.rst` : tout
  rename ou move de page doit ajouter une ligne dans `redirects.txt`.
  Pas d'exception.

### 12.5 Tests doc

- **Doctests** via `sphinx.ext.doctest` sur les snippets Python critiques
  des tutoriels et de la theory section.
- **Coverage API** : test custom dans `tests/unit/architecture/` qui
  vérifie que tout symbole public est documenté.
- **Image existence** : tout `.. figure::` pointe vers un fichier
  réellement présent (gate déjà couverte par `sphinx-build -W`).

### 12.6 Versioning et releases

- **Tags SemVer** alignés avec releases conda-forge.
- **`sphinx-multiversion`** configuré strict :

  ```python
  smv_tag_whitelist = r"^v\d+\.\d+\.\d+$"
  smv_branch_whitelist = r"^(master|dev)$"
  smv_remote_whitelist = None
  smv_released_pattern = r"^tags/v\d+\.\d+\.\d+$"
  ```

- **`sphinx-version-warning`** pour signaler aux lecteurs les versions
  obsolètes.
- **Release workflow** : tag git -> build doc -> push à RTD -> mise à jour
  Zenodo DOI.

### 12.7 Analytics

- **Plausible** ou **GoatCounter** : analytics RGPD-friendly, sans
  cookies, sans Google Analytics.
- **Métriques suivies** : top pages, recherches qui ne trouvent rien,
  taux de "Was this helpful?" négatif par page.
- **Reporting trimestriel** : identifier les pages mal notées et
  prioriser les réécritures.

---

## 13. Exposition de la configuration

Section dédiée à la documentation des paramètres de `HydroModPyConfig`. Le
volume et la profondeur de la config justifient un traitement spécifique,
distinct du user_guide et de l'API ref classique.

### 13.1 Constat sur la config

Mesures faites sur `HydroModPyConfig` au 2026-05-05 :

- **879 champs** au total (récursif)
- **115 classes Pydantic**
- **Profondeur maximale 4 niveaux**
- **16 sous-modèles racines** (`workspace`, `geographic`, `domain`, `data`,
  `flow`, `transport`, `simulation`, `solver`, `modflownwt`, `modflow6`,
  `display`, `persistence`, `analysis`, `overview`, `mesh_catchment`,
  `calibration`)
- **Couverture `Field(description=...)` : 93 %** (excellent point de départ)
- **Section `data` domine** : 316 champs sur 17 familles de données (DEM,
  geology, recharge, hubeau, brgm, etc.)
- **`mesh_catchment`** : 98 champs ; **`analysis`** : 108 champs ;
  **`simulation`** : 57 champs ; **`flow`** : 48 champs.
- **Complexité structurale** : 1 discriminator (`domain.depth_model`),
  1 Union non-trivial (`calibration.outputs.time`), 60 Literals.

Outillage déjà disponible dans le repo :

- `hmp config schema --section <name>` exporte le JSON Schema (Draft 2020-12).
- `hmp config schema --list-sections` liste les sections.
- `hmp config template --profile {user,dev,expert}` génère un TOML annoté.
- `hmp config check file.toml` valide un TOML.

Fichiers clés :
- `hydromodpy/config/hydromodpy_config.py` (racine)
- `hydromodpy/config/schema_export.py` (export Python)
- `hydromodpy/cli/commands/config_cmd.py` (wrapper CLI)

### 13.2 Pourquoi c'est dur

- `autodoc-pydantic` est excellent **par modèle individuel** mais ne sait
  pas naviguer entre 115 classes liées. Une page par classe = 115 pages
  isolées.
- `sphinx-jsonschema` produit du HTML statique flat ; coincé en Draft 4
  (Pydantic v2 émet du Draft 2020-12).
- Aucun gros projet open source n'a résolu le problème à cette échelle :
  - **FastAPI** délègue à Swagger/ReDoc (pensé OpenAPI, pas config pure).
  - **Hydra** rédige à la main (ne passe pas à 500+ champs).
  - **MNE-Python** n'a que ~60 paramètres, curation manuelle.
  - **Pydantic** lui-même utilise un flat autodoc.

### 13.3 Architecture en 4 couches

#### Couche 1 — Landing "Configuration overview"

Page d'accueil de la section config. Contenu :

- **Diagramme ER global** via `erdantic` montrant les 16 sections racines
  et leurs relations.
- **Card-grid `sphinx-design`** : une card par section avec titre, rôle,
  nombre de champs, lien.
- **Bandeau "Open Schema Explorer"** qui ouvre le viewer interactif (couche 3) en plein écran.
- **Liens rapides vers les profils TOML** : user / dev / expert (générés
  par `hmp config template`).

#### Couche 2 — Pages par section

Une page RST par sous-modèle racine. Pour `data`, une page d'index plus 17
sous-pages (une par famille de données).

Structure uniforme par page de section :

1. Vue d'ensemble (rôle, contexte).
2. Diagramme ER local du sous-modèle et ses enfants.
3. Bloc TOML d'exemple commenté (généré depuis les defaults Pydantic).
4. Field summary table (`autodoc-pydantic` avec
   `model_show_field_summary = True`).
5. Champs scalaires détaillés inline.
6. `tab-set` pour les variantes (ex. `modflow6` vs `modflownwt`, modes de
   `flow.ic.h.type`, modes de `domain.depth_model`).
7. Dropdowns `sphinx-design` pour les sections "advanced" ou
   "expert-only".
8. "Cases using this section" : liens automatiques vers les pages de la
   gallery qui exercent les champs de la section (via la directive custom
   `validation-case-summary` de la section 9.5).

#### Couche 3 — Schema Explorer interactif

Page dédiée embarquant **Stoplight JSON Schema Viewer** (composant React,
bundle ~200 KB).

- Source : `HydroModPyConfig.model_json_schema()` exporté au build vers
  `_static/hydromodpy-schema.json`.
- Features natifs : arbre repliable, recherche dans-schéma, breadcrumb,
  deep links via query string (`?path=/properties/flow/properties/param`).
- Intégration Sphinx : page `config/schema_explorer.rst` avec
  `.. raw:: html` qui charge un `<div>` + bundle JS pré-compilé dans
  `_static/schema-viewer/`.
- Bundle pré-compilé via `vite` ou `esbuild` lors du build doc, ou
  pré-buildé et commité dans `_static/`.

Alternatives écartées :
- **Redoc** : pensé OpenAPI, navigation latérale par endpoints pas adaptée
  à une config hiérarchique.
- **jsonschema2md** : statique, perd l'interactivité essentielle.
- **Atlassian json-schema-viewer** : moins maintenu que Stoplight.

#### Couche 4 — TOML reference annoté complet

Page longue avec un TOML complet de tous les champs et leurs defaults.
Tous les champs visibles, valeurs par défaut affichées, commentaires en
regard, sections collapsibles via `sphinx-design dropdown`.

Permet le copier-coller direct d'un bloc utile vers un `project.toml`
utilisateur. Page générée au build depuis les defaults Pydantic.

### 13.4 Profondeur progressive

Le critère de design clé : ne jamais imposer 879 champs au lecteur
simultanément.

| Niveau | Ce que voit l'utilisateur | Effort utilisateur |
|---|---|---|
| 1 | 16 sections + diagramme global | 0 clic |
| 2 | Page d'une section, sous-modèles directs | 1 clic |
| 3 | Détail des champs, validations, defaults | toggle / onglet |
| 4 | Chemin profond comme `data.geology.brgm_1m.layers[0].lithology` | recherche |

### 13.5 Choix techniques

- **`autodoc-pydantic`** : conservé. Configuration recommandée :

  ```python
  autodoc_pydantic_model_show_field_summary = True
  autodoc_pydantic_model_summary_list_order = "bysource"
  autodoc_pydantic_field_doc_policy = "description"
  autodoc_pydantic_field_show_constraints = True
  autodoc_pydantic_field_show_default = True
  autodoc_pydantic_model_show_json = False  # remplacé par Schema Explorer
  autodoc_pydantic_model_show_validator_summary = False  # bruit
  autodoc_pydantic_model_member_order = "groupwise"
  autodoc_pydantic_model_erdantic_figure = False  # activé seulement page Overview
  ```

- **`erdantic`** : pour les diagrammes ER. Activé case-by-case via
  `:erdantic-figure:` dans la directive `.. autopydantic_model::`.

- **Stoplight JSON Schema Viewer** : `@stoplight/json-schema-viewer` v4+.

- **Pas de `sphinx-jsonschema`** : incompatibilité Draft 4 / 2020-12 et
  rendu flat insuffisant.

### 13.6 Mode de génération

Nouveau dossier **`tools/doc_config/`**, parallèle au pattern réussi de
`tools/doc_gallery/`.

```
tools/doc_config/
|-- __main__.py                  # python -m tools.doc_config
|-- schema_dump.py               # exporte hydromodpy-schema.json
|-- page_generator.py            # génère les pages RST par section
|-- toml_annotator.py            # génère les TOML annotés
|-- erdantic_runner.py           # produit les diagrammes ER
|-- viewer_bundler.py            # compile le bundle Stoplight (vite/esbuild)
|-- check.py                     # hash-based drift detection
`-- templates/
    |-- section_index.rst.j2     # template Jinja2 par section
    |-- section_subpage.rst.j2   # template pour data/* sous-pages
    `-- schema_explorer.rst.j2   # template pour la page Schema Explorer
```

Déclenchement :
- `python -m tools.doc_config` régénère tout.
- `python -m tools.doc_config --check` détecte le drift entre code et doc
  (via hashes JSON Schema) sans rien modifier.
- `python -m tools.doc_config --section flow` régénère une seule section.

Comme pour la gallery : pages RST committées, build Sphinx ne fait que
lire les artefacts.

### 13.7 Esthétique

- **Cards `sphinx-design`** sur la landing.
- **Tables `list-table`** pour les champs (lisibles, copiables).
- **`tab-set`** pour les variantes solveur (modflow6 vs modflownwt) ou
  les modes (Literals).
- **Dropdowns** pour les sections advanced.
- **Badges typés** dans les tables, via classes CSS et icônes Octicons (déjà
  fournies par `sphinx-design`) :
  - `scalar` (int / float / str / bool)
  - `object` (BaseModel imbriqué)
  - `list` (séquence)
  - `discriminator` (Union avec discriminator)
  - `literal` (Literal d'enum)

  Implémentation : balises HTML `<span class="cfg-type cfg-type-scalar">scalar</span>`
  rendues par les templates Jinja2 du générateur, plus règles CSS dans
  `_static/custom.css` qui posent fond coloré et glyphe Octicon en
  pseudo-element `::before`.

### 13.8 Recherche

- **Sphinx natif (lunr.js, RTD search)** : couvre les descriptions
  textuelles et les exemples TOML inline.
- **Schema Explorer (Stoplight)** : couvre la recherche structurelle dans
  les chemins, types, contraintes.
- **Double porte d'entrée volontaire**. Unifier en un seul widget est
  possible mais représente un projet à part. Pas dans la première phase.

### 13.9 Subdivision de la section `data`

`data` (316 champs, 17 familles) est seule à mériter une subdivision en
sous-pages :

```
config/data/
|-- index.rst                    # vue d'ensemble + card-grid des 17 familles
|-- dem.rst                      # DemConfig
|-- geology.rst                  # GeologyConfig
|-- recharge.rst                 # RechargeConfig
|-- river_network.rst
|-- hydrography.rst
|-- piezometer.rst
|-- flow_observations.rst
|-- ...                          # une page par famille
`-- shared.rst                   # types partagés (sources, filtres)
```

Cette subdivision suit la structure du code dans `hydromodpy/data/` et
évite la page monolithique de 1000+ lignes.

### 13.10 Effort estimé

| Tâche | Jours |
|---|---|
| Architecture pages + config `autodoc-pydantic` | 1.5 |
| Script `tools/doc_config/` (générateur, schema_dump, templates) | 2.0 |
| Bundle Stoplight viewer + intégration Sphinx | 1.5 |
| Page Overview + diagrammes erdantic | 0.5 |
| TOML annotés + 17 sous-pages pour `data` | 1.5 |
| Tests rendu RTD + ajustements | 0.5 |
| **Total** | **~7.5 jours** |

Pré-requis : compléter les 7 % de `Field(description=...)` manquants
(principalement dans `analysis` et `mesh_catchment`). Effort additionnel :
1-2 jours.

---

## 14. Contenus complémentaires et processus

Section qui regroupe les contenus manquants et les processus éditoriaux à
mettre en place. Ces points complètent l'architecture cible (section 5) et
les outils (section 9) avec du contenu concret et de la gouvernance.

### 14.1 Contenus manquants à forte valeur

#### FAQ et Troubleshooting

Section dédiée que la doc actuelle n'a pas. Avec MODFLOW, conda, binaires
en lazy-download, Pydantic strict, l'écosystème accumule des gotchas qu'un
nouveau venu rencontrera. Page `getting_started/troubleshooting.rst` qui
couvre :

- "MODFLOW binary not found" -> `hmp install-binaries`
- "Validation error: extra fields not permitted" -> typo TOML
- Erreurs PETSc, GMSH, pyvista courantes
- Conflits conda/pip
- "Workspace already exists" et reprises de run

Indexée par **message d'erreur exact** pour que Google y mène
directement quand l'utilisateur copie-colle son erreur.

#### Migration guides

Pour un package en refonte (`Watershed` supprimé, `master_config`
supprimé, Pydantic v2), critique. Dossier `migration/` avec une page par
saut de version :

- `migration/v0_to_v1.rst` : mapping ancien API -> nouveau, exemples côte
  à côte avec `tab-set`.
- Liste des suppressions, renames, équivalents recommandés.
- Banner de deprecation programmatique sur les pages des anciennes APIs.

#### API stability tiers

Roles RST custom `:stable:`, `:experimental:`, `:deprecated:` qui
apparaissent en regard de chaque symbole. Le lecteur sait sur quoi
compter. Implémentation : extension Sphinx custom (~50 lignes) ou
`sphinx-toolbox`. Politique documentée dans `developer/release.rst`.

#### Try it online (Binder + Codespaces)

Page "Try without installing" et boutons sur chaque tutoriel léger.

- **Binder** : 100 % gratuit, pas de risque d'explosion côté mainteneur
  (mybinder.org absorbe). Adapté aux tutoriels courts (< 2 min, < 1.5 GB
  RAM).
- **Codespaces** : 60 h/mois gratuites par utilisateur, le visiteur paie
  son propre quota. Coût compte HydroModPy ~1-2 €/mois si on active les
  prebuilds.

Cf. discussion détaillée des modèles de coût dans la section 14.5.

#### Notation mathématique unifiée

Page `theory/notation.rst` qui définit toutes les notations utilisées
dans la theory section (h, K, S, Sy, b, R, Q, alpha, etc.) avec unités
SI. Référence centrale citée par chaque page math via `:ref:` ou
`:term:`. Évite les divergences entre chapitres.

#### Comparaisons avec d'autres outils

Page `user_guide/comparisons.rst` honnête : HydroModPy vs FloPy vs
MODFLOW-API vs ParFlow vs PFLOTRAN. Tableau couvrant :

- type de modèle (saturé/non saturé, surface/subsurface, transport)
- niveau d'abstraction (low-level wrapper vs framework)
- calibration intégrée
- langage et stack
- courbe d'apprentissage

Aide les nouveaux utilisateurs à se positionner et signale aussi ce que
HydroModPy n'a **pas** (transport 3D non saturé, couplage surface
complet, etc.).

#### Cookbook étoffé

Le plan mentionne `recipes/` dans la section 5.1 mais sans contenu.
Proposer **20-30 recettes courtes** au format uniforme :

- Problem (1 phrase)
- Code (15 lignes max)
- Output (figure ou stdout)
- See also (liens)

Liste de départ :

- Build a synthetic 1D Dupuit case in 10 lines
- Calibrate K against piezometers with CMA-ES
- Compare two solvers on a shared mesh
- Export simulation results to GeoTIFF
- Resume a checkpointed run
- Plot a head time series at a single cell
- Add a new piezometer observation station
- Switch from MODFLOW-NWT to MODFLOW 6 on the same domain
- Generate a transient simulation from steady-state initial condition
- Validate a custom recharge time series
- Sweep parameters via grid_search and pick the best
- Read DuckDB catalog directly from outside the workflow
- Save matplotlib figures with project branding
- Build an irregular triangle mesh from a polygon
- Apply a depth-dependent K parameterization
- Reuse a calibrated K field on a new climatic forcing

#### Page "Concepts en 5 minutes"

Avant `getting_started/`, une page très courte (3-4 minutes de lecture)
qui explique les 5 concepts à comprendre avant de toucher au code :
**Project**, **Run**, **Workflow**, **Catchment**, **Solver**. Sans
code, juste des analogies (un Project est comme un dossier de manip,
un Run est comme une expérience, etc.). Onboarding cognitif.

### 14.2 Marqueurs de qualité scientifique

#### Bibliographie d'usage

Page `about/papers_using_hydromodpy.rst` qui liste les publications
citant HydroModPy. Format BibTeX avec lien DOI. Mise à jour
semi-manuelle via recherche Google Scholar ou alerte Zenodo.
Crédibilité scientifique forte : un nouveau venu voit que le projet est
utilisé en production académique.

#### Reproducibility lock par tutoriel

Chaque script `tutorials/*.py` commite un
`tutorials/locks/01_basic_simulation.lock` avec l'environnement exact
(versions Python, hydromodpy, MODFLOW binaries, dépendances). Affiché
en tête de page : "Last verified with hydromodpy 1.2.0, MODFLOW 6.5.0,
Python 3.13.1". Recouvre la "page fingerprint" de la section 10.6.

#### Auto-screenshot pipeline étendu

`tools/doc_gallery/` capture déjà les figures matplotlib des
`validation_cases/`. Étendre à tous les tutoriels et recettes :
utilitaire qui intercepte chaque `plt.show()` produit par les scripts,
sauvegarde un PNG horodaté dans `_static/auto_figures/` avec hash, et
détecte un drift si la figure change entre runs.

### 14.3 Contenus visuels riches

#### Difficulty et time-to-completion badges

Sur chaque tutoriel et chaque cas gallery, deux badges visibles en
haut :

- **Difficulty** : Beginner / Intermediate / Advanced
- **Time** : "10 min" / "1 h" / "Half a day"

Implémentation : roles RST `:difficulty:` et `:time:` qui rendent en
spans CSS colorés. Aide énormément le lecteur à choisir.

#### GIFs animés courts (10-15 secondes)

Pour les workflows visuellement progressifs :

- Convergence de calibration (CMA-ES qui resserre l'ellipse)
- Raffinement de mesh autour d'une rivière
- Animation transitoire d'une nappe en réponse à une recharge step
- Setup d'un nouveau projet via CLI (asciinema)

Outils : `asciinema` pour CLI, `Gifski` ou `ffmpeg` pour matplotlib.
Trois GIFs bien placés valent dix paragraphes.

#### News feed minimal

Déjà mentionné en section 10.1. Sur la landing, 3 derniers items du
changelog avec date et lien. Donne l'impression de vie au projet.
Optionnel : flux RSS pour les utilisateurs qui veulent suivre.

### 14.4 Processus et gouvernance

#### Cadence de revue des PR doc

Définir explicitement dans `developer/contributing.rst` :

- Qui review les PR doc (mainteneur principal, ou rotation)
- SLA : 5 jours ouvrés pour une revue initiale
- Critères de merge : build sans warning, alt text, descriptions
  Pydantic, redirects ajoutés si renames
- Quand une revue scientifique est nécessaire (changements
  `theory/`)

Sans cadence explicite, le plan de refonte se dilue.

#### Politique de versioning et breaking changes

Page `developer/release.rst` qui définit :

- **SemVer strict** (MAJOR.MINOR.PATCH).
- **Période de deprecation** : 2 versions mineures avec warning Python
  avant suppression d'une API publique.
- **Redirections automatiques** : tout rename de page ajoute une ligne
  dans `redirects.txt` (cf. section 12.4). Pas d'exception.
- **Changelog format** : Keep a Changelog, sections Added / Changed /
  Deprecated / Removed / Fixed / Security.
- **Migration guide obligatoire** pour chaque saut MAJOR.

#### Doc health dashboard

Page **interne** dans `dev_notes/diagnostics/doc_health.md` régénérée
en CI hebdomadaire :

- Couverture `Field(description=...)` par module
- Alt text manquants
- Liens morts (résultat du linkcheck)
- Pages sans `last-updated` depuis > 6 mois
- Warnings Sphinx au build
- Couverture API (% des symboles publics référencés)
- Build time tendance (sur 12 dernières semaines)

Tableau de bord de la santé éditoriale, visible par l'équipe pour
prioriser le suivi.

### 14.5 Note sur le coût des plateformes "Try it online"

Synthèse du raisonnement détaillé en chat (2026-05-05) pour mémoire
durable :

| Plateforme | Coût mainteneur | Coût utilisateur | Risque explosion |
|---|---|---|---|
| Binder (mybinder.org) | 0 € quoi qu'il arrive | 0 € | Aucun (mybinder.org absorbe et rate-limite) |
| Codespaces sans prebuild | 0 € | 60 h/mois gratuites puis ~0.18 $/h | Aucun pour le mainteneur |
| Codespaces avec prebuild | ~1-2 €/mois (storage image) | identique | Plafonné, prévisible |

Codespaces n'expose **jamais** le compte HydroModPy à une facture
d'utilisateur externe : chaque visiteur consomme **son propre quota
personnel**. La seule exception est l'option "billed to org" qui est
désactivée par défaut.

Recommandation : commencer par Binder pour 4-6 tutoriels légers (effort
1 jour, coût 0 €), ajouter Codespaces dans un second temps pour les
contributeurs (effort 0.5 jour). La doc précise quels exemples sont
compatibles Binder vs lesquels nécessitent une install locale.

---

## 15. Plan de migration

Chaque étape est commitable indépendamment. Aucune ne casse RTD si appliquée
dans l'ordre.

### Étape 1 — Nettoyage (1 heure)

- `git rm -r docs/_build_dummy/ docs/readthedocs/_build_dummy/`
- `git rm -r docs/community/ docs/links/`
- Vérifier que le build RTD passe encore.
- Commit : `[cleanup] - drop dead build_dummy folders and out-of-scope files`.

### Étape 2 — Élargissement CSS (1h30)

- Créer `docs/readthedocs/source/_static/custom.css` avec les règles
  d'élargissement et l'overflow des tableaux.
- Ajouter `"custom.css"` à `html_css_files` dans `conf.py`.
- Ajouter la métadonnée `:html_theme.sidebar_secondary.remove:` aux pages
  cas de la gallery : mettre à jour `tools/doc_gallery/` pour l'émettre,
  régénérer, commiter.
- Commit : `[docs] - widen content area and disable secondary sidebar on gallery cases`.

### Étape 3 — Hygiène de `conf.py` (2 heures)

- Dédupliquer `autodoc_mock_imports`.
- Passer `source_suffix = [".rst", ".md"]`.
- Configurer `intersphinx_mapping` pour NumPy, SciPy, pandas, matplotlib,
  flopy.
- Ajouter `smv_tag_whitelist` / `smv_branch_whitelist`.
- Supprimer les 30+ lignes `nitpick_ignore_regex` qu'intersphinx résout
  désormais.
- Commit : `[docs] - clean conf.py and enable intersphinx`.

### Étape 4 — Suppression des notebooks (1 jour)

- Retirer `docs/readthedocs/source/notebooks/` du toctree de
  `examples.rst`.
- `git rm` des 12 `.ipynb` et des deux scripts de génération.
- Ajouter un placeholder minimal
  `docs/readthedocs/source/tutorials/index.rst` qui pointe vers "Coming
  soon, see capability gallery for now".
- Commit : `[docs] - remove notebooks frozen on legacy API, prepare tutorials slot`.

### Étape 5 — Bascule de l'API ref vers recursive (2 jours)

- Remplacer les 16 pages maîtresses dans `api/` par un seul `api/index.rst` :

  ```rst
  .. autosummary::
     :toctree: generated/
     :recursive:

     hydromodpy
  ```

- Vérifier que la génération couvre `core`, `physics`, `analysis`,
  `solver.modflow6`, `solver.boussinesq`.
- Ajouter le test CI sous `tests/unit/architecture/` pour la complétude
  API.
- Commit : `[docs] - switch api ref to recursive autosummary`.

### Étape 6 — Nettoyage architecture (1 jour)

- Éditer `architecture/index.rst` pour retirer la ligne fantôme
  `|-- pipeline/`.
- Régénérer `architecture/data_loading/diagrams/data_definition_transfer_class.wsd`
  pour utiliser `DataPlanner` au lieu de `DataManagersPlanner`. Passer en
  revue les autres références fantômes.
- Ajouter une note d'en-tête à `source/architecture/index.rst` et à
  `docs/developers/architecture.md` clarifiant la relation entre les deux
  (architecture.md normatif, source/architecture/ illustratif).
- Commit : `[docs] - remove pipeline ghost and align architecture diagrams with code`.

### Étape 7 — Réorganisation de la gallery (2-3 jours)

- Mettre à jour le schéma de manifest dans `tools/doc_gallery/` pour la
  structure imbriquée catégorie/sous-famille.
- Réécrire le générateur pour émettre l'arbre à 5 catégories.
- Déplacer les fichiers PNG de `_static/capability_gallery/` vers la
  nouvelle disposition.
- Corriger le bug de tronquage des descriptions de cards.
- Ajouter les thumbnails `:img-top:` aux grid cards.
- Ajouter une page "All cases" triable.
- Refactor des pages cas pour utiliser des `tab-set` imbriqués.
- Régénérer toute la gallery.
- Commit : `[docs] - reorganise capability gallery into 5 categories with thumbnails`.

### Étape 8 — Tutoriels avec sphinx-gallery (2-3 jours)

- Ajouter `sphinx_gallery.gen_gallery` aux extensions (actuellement seul le
  style est chargé).
- Configurer `sphinx_gallery_conf` pour lire depuis
  `docs/readthedocs/source/tutorials/` (scripts Python).
- Écrire 4-6 tutoriels (`01_basic_simulation.py`, `02_calibration.py`,
  etc.) utilisant l'API `HydroModPyConfig` actuelle. Chaque script doit
  tourner en moins de ~30 secondes au build.
- Ajouter une étape CI qui exécute les scripts tutoriels pour détecter le
  drift API.
- Commit : `[docs] - add sphinx-gallery tutorials replacing legacy notebooks`.

### Étape 9 — Bibliographie (1 jour)

- Ajouter `sphinxcontrib-bibtex` aux requirements doc.
- Créer `theory/references.bib` avec les papiers de l'équipe et les
  références externes clés actuellement citées en prose libre.
- Remplacer les citations en prose dans `theory/boussinesq.rst`,
  `theory/calibration_methods.rst`, `theory/modflow.rst` par des appels
  `:cite:`.
- Ajouter une page "Bibliography" rendue par la directive `bibliography`.
- Commit : `[docs] - add bibtex bibliography and convert prose citations`.

### Étape 10 — Hoist de `source/` (demi-journée)

- Déplacer `docs/readthedocs/source/` -> `docs/source/`.
- Mettre à jour `.readthedocs.yaml` pour pointer vers `docs/source/conf.py`.
- Mettre à jour `docs/readthedocs/Makefile` -> `docs/Makefile`.
- Vérifier que RTD build encore.
- Commit : `[docs] - hoist source tree to docs/source`.

### Étape 11 — Consolidation user guide (2 jours)

- Ramener `user_guide/data/` à 2 niveaux maximum.
- Fusionner les pages feuilles de moins de 20 lignes dans leur parent.
- Déplacer six fichiers orphelins `getting_started/*.rst` vers
  `user_guide/concepts/`.
- Commit : `[docs] - consolidate user guide leaves and absorb getting_started orphans`.

### Étape 12 — Consolidation theory (2 jours)

- Renommer `scientific/` en `theory/`.
- Fusionner les six fichiers Boussinesq en un seul `theory/boussinesq.rst`.
- Mettre à jour toutes les `:doc:` internes.
- Commit : `[docs] - rename scientific to theory and consolidate boussinesq`.

### Étape 13 — Démantèlement de `docs/developers/` et création de `dev_notes/` (1 jour)

Application de la séparation public/interne décrite en section 5.2.

- Créer `dev_notes/` à la racine du repo avec sous-dossiers `decisions/`,
  `diagnostics/`, `drafts/`, `legacy/` plus un `README.md` qui explique le
  rôle.
- Déplacer vers `dev_notes/diagnostics/` :
  `BENCHMARK_PY_ANALYSIS.md` (depuis `docs/archive/`),
  `boussinesq_petsc_headwater_100km2_diagnostic.md`,
  `boussinesq_petsc_vs_marcais_2017.md`,
  `documentation_illustration_audit.md`.
- Déplacer vers `dev_notes/drafts/` :
  `modflow6_gmsh_disv_development_perspective.md`,
  `ploemeur_3d_development_perspective.md`,
  `ML_ACCESS_PATTERN.md`.
- Déplacer vers `dev_notes/decisions/` :
  `nwt_sunset_plan.md`,
  `documentation_refactor_plan.md` (le présent document).
- Déplacer vers `dev_notes/legacy/` :
  `gmsh_mesh_integration_note.md`,
  `Recapitulatif perlen HMP.pdf`.
- Convertir et publier dans `docs/source/developer/` les pages stables :
  `architecture.md` -> `architecture.rst`,
  `design_patterns.md` -> `design_patterns.rst`,
  `mental_model_and_design_choices.md` -> `mental_model.rst`,
  fusion `databases_and_workflows.md` + `parquet_lakehouse_*.md` +
  `simulation_catalog_architecture.md` -> `storage.rst`,
  `schema_evolution.md` -> `schema_evolution.rst`,
  `CLI.md` -> `cli.rst`,
  `binaries.md` -> `binaries.rst`,
  `frontend_hooks.md` -> `frontend_hooks.rst`,
  `glossary.md` -> `glossary.rst`.
- Redistribuer les pages d'architecture pure
  (`unified_mesh_pivot_architecture.md`, `gmsh_conformal_meshing.md`,
  `boussinesq_solver_architecture.md`, `modflow_contracts.md`) dans
  `docs/source/architecture/`.
- Supprimer le dossier `docs/developers/` vidé.
- Déplacer `docs/examples/streamlit_app.py` vers `examples/integrations/`
  avec un petit README.
- Supprimer les dossiers vidés `docs/archive/` et `docs/examples/`.
- Mettre à jour `.gitignore` si nécessaire (s'assurer que `dev_notes/` est
  bien tracké, contrairement à `docs/_build/`).
- Vérifier qu'aucun fichier de `dev_notes/` n'est référencé par un
  toctree Sphinx (sinon warning au build).
- Commit : `[docs] - split docs/developers into published source/developer and internal dev_notes`.

### Étape 14 — Extensions Tier 1 (1 jour)

- Installer et configurer dans `conf.py` : `sphinx-codeautolink`,
  `sphinx-hoverxref`, `sphinxcontrib-mermaid`, `sphinx-jsonschema`,
  `sphinx-autodoc-typehints`, `sphinx-issues`, `sphinxext-opengraph`,
  `sphinxext-rediraffe`.
- Mettre à jour `readthedocs_requirements.txt` avec les versions épinglées.
- Créer un fichier de test (page démo) qui exerce chaque extension, pour
  valider l'install avant de l'utiliser partout.
- Commit : `[docs] - install tier-1 sphinx extensions and verify on demo page`.

### Étape 15 — Identité visuelle et citation (1 jour)

- Créer `_static/logo.svg` (light + dark).
- Créer `_static/og-image.png` (1200x630).
- Configurer `sphinx-favicon` avec SVG + PNG 16/32/192/512.
- Ajouter `CITATION.cff` à la racine du repo (lu par GitHub).
- Créer `source/about/how_to_cite.rst` avec BibTeX, RIS, plain text +
  copy-button.
- Créer `source/about/authors.rst` avec ORCID et affiliations.
- Configurer `ogp_*` dans `conf.py` pour les balises Open Graph.
- Commit : `[docs] - add visual identity, CITATION.cff and how-to-cite page`.

### Étape 16 — Redirections (demi-journée)

- Créer `docs/source/redirects.txt` listant tous les renames effectués
  par les étapes précédentes.
- Activer `sphinx-rediraffe` dans `conf.py`.
- Documenter la politique de redirection dans
  `developer/style_guide.rst`.
- Vérifier que les anciennes URLs redirigent correctement (script de test
  qui hit chaque ligne du fichier).
- Commit : `[docs] - add redirect map for refactored pages`.

### Étape 17 — Qualité éditoriale et CI (1 jour)

- Ajouter `sphinx-lint` ou `doc8` en pre-commit hook
  (`.pre-commit-config.yaml`).
- Installer `sphinxcontrib-spelling` et créer
  `tools/doc/spelling_wordlist.txt` (Boussinesq, Brutsaert, Dupuit,
  Theis, Hantush, Marçais, etc.).
- Activer `sphinx-build -W --keep-going` en gate CI.
- Ajouter une CI hebdomadaire de linkcheck.
- Créer `developer/style_guide.rst`.
- Créer `source/glossary.rst` avec directive `.. glossary::`.
- Commit : `[docs] - enable doc linting, spelling check and warnings-as-errors`.

### Étape 18 — Accessibilité et performance (1 jour)

- Conversion PNG -> WebP pour `_static/capability_gallery/` (script dans
  `tools/doc_gallery/`).
- Patch des `.. figure::` pour `<picture>` avec WebP + fallback PNG, ou
  CSS attribute selector pour `loading="lazy"`.
- Audit alt text : script qui liste les `.. figure::` sans `:alt:`.
- Test contraste WCAG AA en dark/light mode (Lighthouse, axe-core).
- Test mobile sur 3 breakpoints (375, 768, 1280).
- Commit : `[docs] - convert gallery PNG to WebP and audit accessibility`.

### Étape 19 — Extensions Tier 2 (1-2 jours)

- `sphinx-notfound-page` : page 404 custom multi-version.
- `sphinx-favicon` : déjà fait à l'étape 15.
- `sphinx-sitemap` : `sitemap.xml` pour SEO.
- `sphinx-paramlinks` : enrichir les pages theory avec `:paramref:`.
- `sphinx-version-warning` : bandeau sur versions obsolètes.
- `sphinx-github-changelog` : génère `changelog.rst` depuis releases.
- `sphinx-last-updated-by-git` : date par page.
- `sphinx-prompt` : typographie shell prompts.
- Configurer chaque extension, vérifier qu'aucune n'introduit de
  warning.
- Commit : `[docs] - install tier-2 sphinx extensions for richer UX`.

### Étape 20 — Directives custom (2 jours)

- Créer `tools/doc_gallery/sphinx_ext.py` avec :
  - Directive `config-field` (~150 lignes).
  - Directive `validation-case-summary` (~200 lignes).
  - Directive `solver-comparison` (~150 lignes).
- Tests unitaires sous `tests/unit/doc_ext/`.
- Premier usage dans `theory/boussinesq.rst` (validation-case-summary) et
  `user_guide/concepts/configuration.rst` (config-field).
- Commit : `[docs] - add custom config-field, validation-case-summary and solver-comparison directives`.

### Étape 21 — Page d'accueil et feedback (1 jour)

- Refonte `index.rst` : hero illustration, 3 CTA, status badges, news
  feed, citation block avec copy-button.
- Widget "Was this helpful?" en footer de chaque page (custom JS dans
  `_static/feedback.js`).
- Lien "Open issue about this page" en footer (template GitHub
  pré-rempli).
- Configurer Plausible Analytics (RGPD-friendly).
- Commit : `[docs] - revamp landing page with hero, CTAs and feedback widget`.

### Étape 22 — Pré-requis : compléter `Field(description=...)` (1-2 jours)

- Audit des 7 % de champs sans `description=` (concentrés dans `analysis`
  et `mesh_catchment`).
- Compléter chaque description, en respectant le style des champs
  existants (description courte, unité si applicable).
- Ajouter une règle CI qui interdit les nouveaux champs Pydantic sans
  `description=` (test custom dans `tests/unit/architecture/`).
- Commit : `[config] - complete Field descriptions for analysis and mesh_catchment`.

### Étape 23 — Pipeline `tools/doc_config/` (2 jours)

- Créer la structure de dossier décrite en section 13.6.
- Implémenter `schema_dump.py` : appelle `HydroModPyConfig.model_json_schema()`
  et écrit `_static/hydromodpy-schema.json`.
- Implémenter `page_generator.py` : pour chaque sous-modèle racine, génère
  une page RST depuis le template Jinja2.
- Implémenter `toml_annotator.py` : génère les TOML annotés avec defaults.
- Implémenter `erdantic_runner.py` : rend les diagrammes ER en SVG.
- Implémenter `check.py` : drift detection via hashes JSON.
- Tests unitaires sous `tests/unit/doc_config/`.
- Commit : `[docs] - add tools/doc_config pipeline for config reference pages`.

### Étape 24 — Schema Explorer interactif (1.5 jour)

- Créer `_static/schema-viewer/` avec un projet vite/esbuild minimal
  qui bundle `@stoplight/json-schema-viewer`.
- Pré-build le bundle (~200 KB) et commiter dans `_static/schema-viewer/`.
- Créer la page `config/schema_explorer.rst` qui charge le bundle via
  `.. raw:: html`.
- Tester le deep linking (URL query string `?path=...`).
- Commit : `[docs] - add interactive schema explorer with stoplight viewer`.

### Étape 25 — Pages config par section (1.5 jour)

- Lancer `python -m tools.doc_config` pour générer les 16 pages racines +
  17 sous-pages `data`.
- Page `config/index.rst` (Overview) avec diagramme ER global et card-grid.
- Page `config/toml_reference.rst` (TOML complet annoté).
- Vérifier le rendu RTD, ajuster les templates Jinja2 si besoin.
- Lier la section "Configuration" au toctree principal de `user_guide/`.
- Commit : `[docs] - generate hierarchical config reference pages`.

### Étape 26 — Liens config <-> gallery (0.5 jour)

- Activer la directive custom `validation-case-summary` (section 9.5)
  pour insérer dans chaque page de section config la liste des cas
  gallery qui exercent les champs.
- Régénérer les pages config via `python -m tools.doc_config`.
- Commit : `[docs] - cross-link config sections with gallery cases`.

### Étape 27 — FAQ et Troubleshooting (1 jour)

- Créer `docs/source/getting_started/troubleshooting.rst` avec les
  catégories : MODFLOW binaries, conda/pip, Pydantic validation, PETSc,
  GMSH, pyvista, workspace.
- Indexer chaque entrée par message d'erreur exact (en `code-block`
  pour que les moteurs de recherche s'en emparent).
- Lier depuis `cli_quickstart.rst` et `first_simulation.rst`.
- Commit : `[docs] - add troubleshooting page indexed by error message`.

### Étape 28 — Migration guides et API stability (2 jours)

- Créer le dossier `docs/source/migration/` avec un index.
- Écrire `migration/v0_to_v1.rst` : mapping `Watershed` -> nouveau API,
  `master_config` -> `HydroModPyConfig`, exemples avant/après.
- Implémenter les roles `:stable:`, `:experimental:`, `:deprecated:`
  via une extension Sphinx custom dans `tools/doc_ext/api_stability.py`
  (~50 lignes).
- Documenter la politique dans `developer/release.rst`.
- Commit : `[docs] - add migration guides and api stability roles`.

### Étape 29 — Try it online: Binder + Codespaces (1 jour)

- Créer `.binder/` avec `Dockerfile`, `environment.yml` et `postBuild`
  qui pré-installe MODFLOW binaries.
- Créer `.devcontainer/devcontainer.json` pour Codespaces avec config
  équivalente.
- Pré-builder l'image Docker dans GitHub Container Registry pour
  accélérer Binder.
- Ajouter une page `docs/source/getting_started/try_online.rst` avec
  les boutons et la matrice "Binder OK" / "Codespaces OK" / "Local
  required" par tutoriel.
- Commit : `[docs] - enable Binder and Codespaces for hands-on demos`.

### Étape 30 — Notation, comparaisons, concepts en 5 min (1 jour)

- Créer `theory/notation.rst` : tableau de toutes les variables avec
  unités SI, lié depuis chaque page math via `:ref:`.
- Créer `user_guide/comparisons.rst` : tableau honnête HydroModPy vs
  FloPy / MODFLOW-API / ParFlow / PFLOTRAN.
- Créer `getting_started/concepts_in_5_min.rst` : les 5 concepts
  fondamentaux (Project, Run, Workflow, Catchment, Solver) sans code,
  avec analogies.
- Lier depuis la page d'accueil.
- Commit : `[docs] - add unified notation, tool comparisons and 5-min concepts page`.

### Étape 31 — Cookbook étoffé (3 jours)

- Créer `user_guide/recipes/` avec 20-30 fichiers RST.
- Format uniforme : Problem / Code 15 lignes / Output / See also.
- Index avec tags filtrables (calibration, mesh, output, comparison,
  data).
- Liste de départ : voir section 14.1.
- Tester chaque snippet (doctest possible).
- Commit : `[docs] - add cookbook with 20+ targeted recipes`.

### Étape 32 — Difficulty / time badges et GIFs (1 jour)

- Implémenter les roles `:difficulty:` et `:time:` (extension custom).
- Ajouter ces roles en haut de chaque tutoriel et page gallery.
- Capturer 3 GIFs courts (calibration convergence, mesh refinement, CLI
  setup via asciinema).
- Intégrer les GIFs dans les pages correspondantes.
- Commit : `[docs] - add difficulty and time badges, embed key workflow GIFs`.

### Étape 33 — Bibliographie d'usage et reproducibility locks (1 jour)

- Créer `about/papers_using_hydromodpy.rst` avec entrées BibTeX (vide
  au démarrage, à compléter).
- Étendre `tools/doc_config/` ou un nouveau `tools/doc_repro/` qui
  capture pour chaque tutoriel un `.lock` avec versions actuelles.
- Afficher la fingerprint en tête de chaque page tutoriel/cas gallery.
- Commit : `[docs] - add usage bibliography and reproducibility locks per tutorial`.

### Étape 34 — News feed et auto-screenshot étendu (1 jour)

- Ajouter un bloc "Recent news" sur la landing : 3 derniers items du
  changelog avec date et lien.
- Étendre `tools/doc_gallery/` pour capturer aussi les figures des
  tutoriels et recettes (pas seulement les validation cases).
- Détecter le drift visuel via hash des PNG.
- Commit : `[docs] - add news feed on landing and extend auto-screenshot pipeline`.

### Étape 35 — Doc health dashboard (1 jour)

- Créer `tools/doc_health/` qui calcule métriques :
  couverture descriptions, alt text manquants, liens morts, pages
  obsolètes, warnings build, couverture API, build time.
- Hook CI hebdomadaire qui régénère
  `dev_notes/diagnostics/doc_health.md`.
- Pas de publication RTD : cette page reste interne.
- Commit : `[docs] - add weekly doc health dashboard in dev_notes`.

### Étape 36 — Cadence de revue et politique versioning (0.5 jour)

- Compléter `developer/contributing.rst` avec : qui review les PR doc,
  SLA, critères de merge, quand une revue scientifique est nécessaire.
- Compléter `developer/release.rst` avec : SemVer strict, période de
  deprecation, redirections obligatoires sur renames, format
  Keep a Changelog, migration guide obligatoire pour saut MAJOR.
- Commit : `[docs] - document doc review cadence and versioning policy`.

### Estimation d'effort totale

Environ 38-42 jours de travail, étalables sur plusieurs semaines.
Décomposition :

- Étapes 1 à 3 (~5 heures) : nettoyage + élargissement CSS + hygiène
  `conf.py`. Effet immédiat le plus visible côté utilisateur.
- Étapes 4 à 13 (~12-15 jours) : refonte structurelle (notebooks, API,
  architecture, gallery, tutoriels, biblio, hoist, consolidations).
- Étapes 14 à 21 (~8-10 jours) : polissage UX, identité, qualité,
  extensions, accessibilité.
- Étapes 22 à 26 (~7.5 jours) : exposition de la configuration en 4
  couches (overview, pages section, schema explorer, TOML reference).
- Étapes 27 à 36 (~11.5 jours) : contenus complémentaires (FAQ,
  migration, Binder/Codespaces, notation, comparaisons, cookbook,
  badges, bibliographie, news feed, dashboard, gouvernance).

Possibilité de paralléliser : étapes 14-21, 22-26 et 27-36 peuvent
démarrer en parallèle des étapes 6-13 si plusieurs personnes
travaillent sur la doc. Les étapes 27-36 sont particulièrement bien
adaptées à des contributeurs externes (rédaction de FAQ, recettes,
cookbook, comparaisons) car elles n'exigent pas une connaissance
profonde de l'architecture.

---

## 16. Questions ouvertes (pour la prochaine session)

1. Le dossier `validation_cases/` doit-il être exposé dans la doc en tant
   que section "Numerical validation" séparée, ou rester implicite derrière
   la gallery ?
2. Le changelog doit-il être auto-généré depuis les tags git
   (style `sphinxcontrib-versioning`) ou maintenu à la main ?
3. Des builds PDF (RTD multi format) sont-ils nécessaires pour un public ?
   Si oui, le choix de thème et la politique de résolution des figures sont
   à revoir.
4. La doc doit-elle être bilingue (FR + EN) à un moment ? Aujourd'hui la
   doc publiée est en anglais. Si FR nécessaire, `sphinx-intl` est l'outil.
5. Faut-il ajouter un backend de recherche (Algolia DocSearch, MeiliSearch)
   pour remplacer la recherche Sphinx par défaut sur RTD ?

Ces points ne bloquent pas la refonte. À décider quand chacun devient
pertinent.

---

## 17. Référence : non-objectifs arrêtés

Pour garder le plan focalisé, les points suivants sont explicitement hors
scope :

- Migration vers MyST Markdown.
- Migration vers MkDocs, Quarto ou JupyterBook.
- Migration hors de ReadTheDocs.
- Remplacement du thème (sphinx-book-theme, Furo, sphinx-immaterial).
- Internationalisation.
- Exécution live des notebooks au build (remplacée par sphinx-gallery sur
  des scripts `.py` curés et rapides à exécuter).

Réexaminables plus tard. Les verrouiller maintenant évite le scope creep.
