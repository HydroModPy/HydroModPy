# État de la refonte gestion des simulations

Date : 2026-06-12. Branche : `dev-lakeres_refact`. Base : `plan_refonte_gestion_simulations.md`
(plan corrigé, section 12 = spéc d'exécution). Suite de tests affectée : **1977 passed, 1 failed,
3 skipped** ; le seul rouge est `test_examples_projects_load` (TOML sous `examples/projects/`
off-limits, migrables via `hmp doctor --fix-config`). `test_derived_mass_seepage` est un échec
**préexistant** (ImportError `_positive_cell_flux`), sans lien avec cette refonte.

25 commits, tous ruff-clean et vérifiés par tests ciblés.

---

## 1. Ce qui est fait

### Schéma (migration 0007)

Un seul fichier `0007_simulation_lifecycle.sql` porte tout le schéma Phase 1+2 :
statut `trashed` ; colonnes `name_stem` / `version_int` / `trashed_at` / `original_name` sur
`simulations` (+ index) ; `audit_log` recréé avec le CHECK élargi (hash-chain 0002 préservée) ;
tables `sim_notes`, `export_log`, `purge_journal`. `PER_SIM_TABLE_NAMES` étendu. Schéma v6 -> v7.

### Identité et nommage

- `simulation.run_id` **supprimé** ; `name` est l'unique identité. `on_collision` renommé
  `if_exists` (défaut `version`). Champ `tags` ajouté.
- Versioning par stem : un run nu se fait démoter en `.v1` à la première collision, les suivants
  sont `.v2`, `.v3`. `replace` met le prédécesseur à la corbeille (restaurable). `fail` lève.
- `started_at` enfin écrit à l'enregistrement. Basename de stockage id-only `<project>__<id8>`
  (renommer/versionner ne touche plus le disque). Nom mémorable déterministe si aucun nom.

### Résolveur unique

UUID / préfixe hex >= 4 / nom exact / **stem -> dernière version** / @-sélecteurs
(`@last`, `@last~N`, `@best:METRIC` et `@worst:METRIC` scopés station outlet, `@running`).
Erreurs `ReferenceResolutionError` (plus `KeyError`), exit code 20 pour l'ambiguïté, suggestions
de noms proches. Matcher viz divergent et code mort `helpers.resolve_sim_id` supprimés.
`find/best/worst` scopés outlet. `find(config_hash=, name_stem=)` ajoutés.

### Lectures honnêtes

- `hmp.open()` read-only par défaut ; mode `read_only` sur la façade (vues TEMPORARY, pas de
  mkdir/migration, erreur claire si schéma en retard). Le writer du workflow passe par
  `from_workspace` (rw), donc le solve n'est pas touché.
- Workers `ls` / `show` read-only (sautent un projet au schéma en retard avec un hint).
- Fix du crash `ls --format json` + projection stable 12 colonnes (ids en strings, dates ISO,
  zéro blob config). `ls --status` / `--tag`.

### Cycle de vie

- Engine catalog : `add_tag` / `write_tags` (no-op corrigé) / `add_note` / `trash` / `restore` /
  `list_trash` / `empty_trash`, garde `PinnedRunError`. `rename_simulation` met à jour
  name_stem/version_int. `find` exclut les trashed par défaut.
- `gc` est un **planificateur** par défaut ; `--apply` pour agir (inverse sûr de l'ancien défaut
  destructif).

### Outils et migration

- `hmp doctor --fix-config FILE.toml` (rewriter tomlkit : `on_collision`->`if_exists`,
  `run_id`->`name`, commentaires préservés, idempotent).
- `hmp doctor --migrate` (upgrade du schéma catalog).
- Épilogue de fin de run (carte d'identité + commandes suivantes, best-effort).

### API Python

`Run.tag()` / `note()` / `delete()` (-> corbeille) / `parent` (lignée). Les accesseurs riches
existants `Run.parameters` / `Run.metrics` (DataFrames) sont conservés.

### CLI (sous le namespace `hmp catalog`)

`ls` `show` `query` `gc` `vacuum` `delete`(->corbeille, `--now` purge) `restore` `trash`
`tag` `note` `rename` `diff` `watch` `export` `import` `rerun`.

---

## 2. Exemples

Session CLI, le matin après une nuit de calibration :

```
$ hmp catalog ls --status completed --limit 5
# project: cheze
  ksweep/trial-013  [9c41aa02]  solver=mf6  status=completed  8.7s
  ...
$ hmp catalog tag ksweep/trial-013 pinned paper-fig4
added: pinned, paper-fig4  [9c41aa02]
$ hmp catalog diff cheze_baseline.v2 cheze_baseline.v3
a: 2b7a4dd2   b: 9c41aa02
params:
  hydraulic_conductivity: 0.0001 -> 0.0002
metrics:
  nse: 0.74 -> 0.78
$ hmp catalog delete ksweep/trial-004 -y
moved to trash [d11b32c8]. Bytes freed at 'hmp catalog trash --empty'. Restore: hmp catalog restore d11b32c8
$ hmp catalog export ksweep/trial-013 -o paper.hmp
wrote paper.hmp  [9c41aa02]
$ hmp catalog rerun cheze_baseline --set flow.hydraulic_conductivity=2e-4
```

Fin de run (épilogue auto-enseignant) :

```
Run completed: cheze_baseline.v3 [9c41aa02] 557s nse=0.78
next: hmp catalog show cheze_baseline.v3 | hmp catalog diff cheze_baseline.v3 <other> | hmp catalog export cheze_baseline.v3
```

API Python :

```python
import hydromodpy as hmp

cat = hmp.open("~/ws/projects/cheze")     # read-only : ne migre rien, ne touche pas le mtime
run = cat["cheze_baseline"]                # stem -> dernière version (cheze_baseline.v3)
run = cat["@best:nse"]                      # meilleur nse à l'outlet

run.parameters                             # DataFrame indexé par param_name
run.metrics                                # DataFrame long-form (station, metric, value)
run.parent.name                            # lignée

cat_rw = hmp.open("~/ws/projects/cheze", read_only=False)
cat_rw["cheze_baseline"].tag("+pinned").note("best fit after widening Sy")
```

Migration d'un TOML legacy :

```
$ hmp doctor --fix-config examples/projects/02_nancon_watershed/project.toml
Migrated .../project.toml:
  - simulation.on_collision -> if_exists ('replace')
  - simulation.run_id -> name ('nancon')
```

---

## 3. Livré dans la 2e vague (2026-06-12, +9 commits, revue adversariale)

Tout vérifié par tests ciblés + une revue adversariale (31 agents, file:line) dont les blocages
ont été corrigés. Détail des commits : `git log --oneline b01d1cc3b..HEAD`.

- **`[export]` top-level** (chantier #3) : `ExportConfig` déplacé dans
  `simulation/planning/export_config.py`, exposé sur `HydroModPyConfig.export`, retiré de
  `ResultsConfig`. Champs `package: bool` + `times` ajoutés ; `csv_timeseries` gardé (pas de shim).
  `times` câblé dans `_auto_export` (rasters mono-step / netcdf multi-step), `package` écrit le
  `.hmp` **pendant que le store est ouvert** (avant `step_finalize_store` qui le ferme ; les deux
  chemins ExportStep et orchestrator). `hmp doctor --fix-config` promeut `[simulation.results.export]`.
  Référence de config régénérée (`python -m tools.doc_config`).
- **Purge journalisée 2 phases** (chantier #4) : `delete(remove_storage=True)` est crash-safe
  (journal `pending` + `sim.purge.begin`, rmtree idempotent, cascade + clear journal + commit).
  `replay_purge_journal()` rejoue les purges interrompues. Émission `sim.purge.begin` idempotente
  sur retry de lock. Tests d'injection de fautes prouvant l'invariant « aucun byte inatteignable ».
- **gc = verbe unique de maintenance** (chantier #5a) : absorbe `vacuum` (verbe supprimé) +
  expiry corbeille (`TRASH_RETENTION_DAYS=30`, pins respectés) + orphan stores + replay purge +
  stale-running. **export_log + RUN.txt** (#5b) : `record_export` (no-op en read-only),
  `list_exports`, RUN.txt par dossier d'export, `show` liste les exports. **Adoption** (#5c) :
  `finalize` écrit `simulation.parquet`, `catalog.adopt(store)` + `hmp catalog adopt`.
- **Fédération** (chantier #6) : `GlobalIndex.find` gagne les filtres mots-clés + opérateurs
  `_gt/_gte/_lt/_lte/_like` + `name_like` + masquage des trashed ; `hmp catalog export REF1 REF2`
  écrit N archives.

## 4. Livré dans la 3e vague (2026-06-12, +4 commits)

- **#2 `hmp run --resume REF`** : config optionnelle ; sans config, REF est résolu dans le
  catalogue, la config est reconstruite depuis le snapshot (`Project(snapshot).simulate(resume=name)`)
  et le run reprend via la machinerie de journal keyée par nom déjà testée.
  **Migration 0008 délibérément NON faite** : la prémisse du plan (re-key `workflow_steps.run_id`
  par id8) est invalidée par le code (le journal est keyé avant que le `sim_id` existe ; les
  premières étapes tournent avant l'enregistrement, `_state_sim_id` renvoie `None` tôt). Le re-key
  casserait le journaling des étapes précoces. Le journal name-keyé suffit pour resume.
- **#1 heartbeat sidecar** : `<workspace>/.hmp/running/<id8>.json` rafraîchi par `HeartbeatPulse`,
  retiré à la sortie. `hmp watch` lit le sidecar (donc utilisable **pendant** un solve qui tient
  le lock DuckDB) ; `gc` protège les runs à sidecar frais et nettoie ceux des runs crashés.
  **Connexion-par-transaction NON faite** : le plan **mandate un benchmark réel** sur le solve de
  557 s avant de figer la granularité (hot-path, risques ART-index/audit hash-chain). C'est un
  réglage de perf, pas un trou de correction. **À faire avec un vrai run cheze.**
- **#7 rename `SimulationCatalog`->`Catalog`, `SimulationGroup`->`RunSet`** : passe mécanique sur
  160 fichiers .py (tokens uniques, aucune collision ; `hydromodpy.catalog` n'a pas de classe
  `Catalog`). Test garde-fou retourné pour acter le clean break (anciens noms supprimés, pas
  d'alias). Doc de config régénérée.

## 5. Seul reste non livré : connexion-par-transaction (cœur de #1)

Diagnostic file:line (5 agents) : **architecturalement bloquée**, pas seulement gated benchmark.
4 contraintes dures interdisent une connexion par transaction : (1) le double-transaction du
journal contre le bug d'index ART de DuckDB (même connexion obligatoire), (2) l'atomicité de la
hash-chain d'audit (lecture `prev_hash` + calcul dans la même session), (3) le register/unregister
de table temporaire dans `write_observations`, (4) l'état des vues parquet entre statements. Ce
n'est pas un réglage de perf : la correction casserait. La connexion reste longue ; le heartbeat
sidecar (livré) couvre la liveness pendant un solve. À ne PAS implémenter sans réécrire ces 4
sous-systèmes (gros chantier, hors scope).

## 7. Améliorations livrées (4e vague, 2026-06-12, +7 commits)

Issues de la revue + santé repo + complétude plan. Toutes vérifiées par tests ciblés.

- **§3 durcissements** : `adopt` insère les colonnes communes (robuste à l'évolution de schéma),
  `_write_simulation_snapshot` loggue en WARNING (plus de silence), `export.times` rejette la liste
  vide.
- **§4 santé repo** : `test_derived_registry` corrigé (vrai `ExecutionRegistry` au lieu de
  `SimpleNamespace`), `test_derived_mass_seepage` corrigé (teste le `_positive_cell_flux_stack`
  vivant, pas le helper supprimé — respect du « no legacy »), `DuckDBCacheBackend` exposé
  publiquement (suppression de l'import `_private` cross-package dans le worker gc).
- **§5 complétude** : **archive multi-runs single-container** (export N runs -> 1 `.hmp` qui
  contient N archives single-run + manifest v2.0 ; import restaure tout, single-run encore lisible) ;
  `export_log` aussi alimenté par l'export CLI ; `doctor` honore le heartbeat sidecar.
- **§2 resume** : un resume qui dégénère en full restart loggue désormais un WARNING au lieu d'être
  silencieux.

## 6. État de la suite (full `tests/unit`)

**4945 passed, 6 failed, 19 skipped.** Les 6 rouges :

- **3 préexistants** (échouent aussi à la base, hors périmètre) : `test_examples_projects_load`,
  `test_derived_registry` (2, ctx factice sans `models_by_run_id`).
- **3 dus au rename**, tous dans `test_b0_score_candidate_table.py`, tous via le **même** script
  OFF-LIMITS `examples/projects/12_calibration_network_transient_b0/score_candidate_table.py` qui
  fait `from hydromodpy.results.catalog import SimulationCatalog`. Le rename couvre désormais tout
  l'éditable (`hydromodpy/`, `tests/`, `validation_cases/`, `tools/`, `docs/`) ; seul reste ce
  script d'exemple off-limits (plan §12.2 « je ne les édite pas »). **Migration triviale côté
  utilisateur** dans ses scripts d'exemple, comme les TOML déjà assumés en clean break.
  (Au premier jet j'avais oublié `validation_cases/`+`tools/` -> corrigé, +2 verts.)
