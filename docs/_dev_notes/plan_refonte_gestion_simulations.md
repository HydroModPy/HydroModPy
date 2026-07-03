# Plan de refonte : gestion des simulations (TOML, CLI, Python, DB)

Date : 2026-06-11. Statut : **partiellement implémenté** (2026-06-12, 25 commits sur
`dev-lakeres_refact`). Pour reprendre dans une nouvelle session, lire d'abord la **section 13**
(ce qui est fait, exemples, ce qui reste) : elle est le point d'entrée de reprise. Détail
complet dans `etat_refonte_simulations.md`.
Base factuelle : `docs/_dev_notes/audit_simulation_catalog_ux.md` (28 findings confirmés contre le code).
Méthode : 4 designs concurrents (UX-first, architecture-first, transplantation d'outils éprouvés,
delta minimal), panel de 3 juges (hydrogéologue, mainteneur, product designer), 6 vérifications de
faisabilité contre le code réel (file:line), red team adversarial, puis synthèse. Le design gagnant
est UX-first (98 pts contre 97.5 pour architecture-first), enrichi des mécanismes internes
d'architecture-first (trash par flag, purge journalisée) et des idées validées des deux autres.

---

## 1. La thèse

**Un projet tient un carnet de laboratoire de runs.**

Chaque run porte un nom qu'on peut prononcer en réunion (`cheze_baseline.v3`, `ksweep/trial-013`).
Le carnet est append-only par défaut : on n'arrache jamais une page par accident. Toute action
(chercher, inspecter, comparer, exporter, supprimer) adresse un run par son nom ou par un sélecteur
relatif (`@last`, `@best:nse`), jamais par hash. Les UUID existent toujours mais sont rétrogradés
en plomberie : l'id court à 8 caractères apparaît dans les listings comme départage, aucun workflow
n'exige de le taper.

La doctrine sous-jacente tient en une phrase : **id forever, name for now**. Le `sim_id` uuid4 est
permanent et invisible (il keye le stockage, le journal, la fédération) ; le nom est une colonne
mutable du catalogue, donc renommer, versionner, remplacer sont de purs UPDATE et le filesystem
ne ment jamais.

Cinq principes en découlent, chacun corrige une classe entière de findings de l'audit :

1. **Lire ne modifie jamais.** Toute inspection ouvre DuckDB en read-only, ne migre rien, ne
   réécrit aucune vue. Un projet archivé sur clé USB se consulte sans trace. "Tu peux toujours
   regarder pendant qu'un run tourne" devient un contrat, pas un espoir.
2. **Détruire se fait par étages.** `rm` bascule vers une corbeille (flip de colonne, instantané
   sur un store de 40 GB), `gc` ne fait que planifier sauf `--apply`, la purge définitive est
   journalisée en deux phases : aucune séquence delete/gc/crash ne peut produire un byte
   inatteignable sous `simulations/`. Le tag réservé `pinned` protège les runs de publication partout.
3. **Un seul artefact portable.** L'archive `.hmp` (déjà complète dans le code : manifest SHA-256,
   snapshot DuckDB, zarr.zip, parquet, RO-Crate) et une seule paire de verbes `export`/`import`
   pour toute l'histoire partage-archive-restauration.
4. **CLI et Python sont deux projections de la même grammaire.** Un résolveur unique, un flux de
   sécurité unique, une carte d'identité unique. Qui apprend une surface a appris les deux.
5. **L'outil s'auto-enseigne.** Chaque run terminé imprime sa carte d'identité et les prochaines
   commandes à taper. Un hydrogéologue qui ne lit pas la doc apprend `show`, `diff` et `export`
   parce que l'outil les lui montre au moment exact où il s'y intéresse.

---

## 2. Identité et nommage

### Schéma d'identité

- `sim_id` uuid4 interne, permanent, jamais requis. `run.id` = ses 8 premiers hex (mécanisme
  existant, `storage_paths.py:57-59`), affiché dans les listings, accepté partout en référence.
- `started_at` enfin écrit à l'enregistrement (colonne déclarée depuis 0001 mais jamais remplie).
- **Basename de stockage immuable et id-only** : `<project>__<id8>` pour les nouveaux
  enregistrements (3 lignes dans `build_storage_basename`). Le nom humain ne vit que dans le
  catalogue : renommer/versionner/remplacer ne touche plus jamais le disque. Les basenames legacy
  mixtes restent un état lu supporté (le résolveur lit déjà la colonne stockée, zéro migration).
  Les scientifiques, eux, naviguent dans `<project>/exports/<nom-du-run>/`, qui reste lisible.

### Noms humains

- `[simulation] name` devient **la seule entrée d'identité**. `simulation.run_id` est supprimé
  (c'était l'identité de fait pendant que `name` n'avait aucun consommateur : deux champs pour
  une identité, la racine de la confusion).
- Défaut : stem du TOML moins le préfixe `run_` (règle existante). Run programmatique sans nom :
  nom mémorable déterministe seedé de l'uuid (`brisk_heron`), prononçable, sans état, garantit
  qu'aucun run n'est adressable uniquement par hex.
- Trials de calibration nommés à la suggestion : `ksweep/trial-007`. Fini les lignes anonymes en
  masse (la calibration était le producteur principal de runs sans nom), et `hmp ls ksweep` se lit
  comme le carnet.

### Versioning fermé sur lui-même

- Migration 0007 : colonnes `name_stem` + `version_int` indexées, le nom affiché est dérivé
  (`stem` ou `stem.vN`). Tout chemin qui versionne (register, hard-replace, restore, import) bumpe
  `version_int` sur le stem : `cheze_baseline.v3.v2` est impossible par construction, et le scan
  LIKE bogué (`_` et `%` wildcards) disparaît.
- À la première collision, l'original nu est renommé `.v1` dans la même transaction. Règle
  phare, toujours vraie : **un nom nu désigne la version la plus récente de ce stem**.
- `if_exists` (renommage de `on_collision`, jargon développeur), **défaut `version`** : une nuit
  de calibration de 20 tours produit 20 lignes adressables, plus 19 fantômes `(no name)`.
  `replace` devient un hard-replace honnête : le prédécesseur est version-bumpé et mis à la
  corbeille, nommé, listable, restaurable. `fail` avorte en pre-flight (avant download/meshing).
  Plus aucun chemin ne peut produire un run sans nom.

### Sélecteurs relatifs (un seul résolveur)

`DiscoveryMixin.resolve` gagne les @-tokens ; le matcher divergent de viz gallery et le code mort
`helpers.resolve_sim_id` sont supprimés. Toutes les surfaces (CLI, `cat[...]`, viz, `--resume`)
passent par lui :

- `cheze_baseline.v3` exact ; `cheze_baseline` = version la plus récente ; `name@project`
- `@last`, `@last~1` ; `@running` (exclut les heartbeats morts et dit pourquoi)
- `@best:nse` / `@worst:rmse` : scope canonique station outlet + variable canonique, et chaque
  sortie imprime le scope résolu ("best nse @ outlet/discharge"). Corrige le mensonge actuel des
  extremums multi-stations.
- `id8`, tout préfixe hex unique >= 4 chars, UUID complet.
- Scope projet strict : plusieurs projets sans `-p` lève l'erreur d'ambiguïté qui liste les
  projets. Not-found (exit 10) suggère les plus proches sur les noms ET les tags ; ambigu = exit 20.

---

## 3. Surface TOML

Deux sections visibles : `[simulation]` (identité + intention) et `[export]` promu au top niveau
(il était enterré trois niveaux sous `[simulation.results.export]`).

```toml
[simulation]
name = "cheze_baseline"        # défaut : stem du TOML; programmatique : nom mémorable auto
description = "Weekly transient 2019, SIM2 recharge, LAK+SFR"
tags = ["2019", "reservoir"]   # éditables ensuite via hmp tag
if_exists = "version"           # défaut; "replace" (prédécesseur -> corbeille) | "fail"

[export]                        # écrit dans <project>/exports/<nom-du-run>/ en fin de run
csv = true                      # défaut : les timeseries sortent toujours en CSV
variables = ["head", "watertable_depth"]
geotiff = false
netcdf = false
package = false                 # true -> écrit aussi <name>.hmp (archive portable complète)
times = "last"                  # "last" | "all" | liste de dates ISO
```

- `[export]` vide ou absent : CSV des timeseries seulement. Pas cher, toujours voulu, jamais surprenant.
- `package = true` est l'interrupteur une-ligne "ce run doit être partageable pour toujours"
  (configs de publication : `doi`, `description` coulent dans le RO-Crate).
- Chaque dossier d'export reçoit un `RUN.txt` (name, id8, status) : un dossier copié à la main
  reste auto-identifiant. Chaque artefact est enregistré dans la nouvelle table `export_log` :
  `show`, `rm` et `gc` voient les exports sans glober.
- Migration des TOML existants : `hmp doctor --fix-config FILE.toml` réécrit en un coup
  (`on_collision` -> `if_exists`, `run_id` -> `name`, montée de `[export]`). L'erreur Pydantic
  `extra="forbid"` sur les anciennes clés imprime exactement cette commande. Un réécriveur one-shot
  est un outil de migration, pas un shim : compatible avec les règles du repo.

---

## 4. Surface CLI

Le namespace `hmp catalog` disparaît. Les hydrogéologues pensent "runs", pas "catalog", et les
messages d'erreur actuels pointaient déjà vers un `hmp list` top-level qui n'existait pas. Verbes
promus au premier niveau, help sectionné :

| Quotidien | Annoter | Cycle de vie | Avancé |
|---|---|---|---|
| `hmp ls` | `hmp tag` | `hmp rm` (-> corbeille) | `hmp sql` |
| `hmp show REF` | `hmp note` | `hmp trash ls/restore/empty` | `hmp rerun REF --set k=v` |
| `hmp watch` | `hmp rename` | `hmp gc [--apply]` | `hmp run --resume REF` |
| `hmp export REF` | | | `hmp diff REF_A REF_B` |
| `hmp import FILE` | | | |

Une session réaliste, le matin après une nuit de calibration :

```
$ hmp ls --best nse -n 5
# project: cheze (23 runs, 1 running, 1 stale, 1 failed; trash: 12 GB)
NAME                  ID        WHEN          STATUS     SOLVER  TIME    NSE
ksweep/trial-013      9c41aa02  today 03:12   completed  mf6     8m41s   0.86
ksweep/trial-007      2b7a4dd2  today 01:55   completed  mf6     9m02s   0.84
...
$ hmp tag @best:nse +pinned +paper-fig4
pinned 'ksweep/trial-013' [9c41aa02]   (scope: best nse @ outlet/discharge, project cheze)
$ hmp rm --status failed
1 run -> trash: ksweep/trial-004 [d11b32c8] failed today 02:31, 0.2 GB. Confirm? [y/N] y
moved to trash. Bytes freed at expiry (30 d) or via 'hmp gc --apply'. Restore: hmp trash restore trial-004
$ hmp export ksweep/trial-013
wrote ksweep_trial-013.hmp (1.1 GB, sha256 9f3c..., includes config, provenance, fields, timeseries)
```

Six mois plus tard, retrouver le run de la figure 4 :

```
$ hmp show fig4
No run matches 'fig4' in project 'cheze'. Closest: ksweep/trial-013 (tag: paper-fig4). [exit 10]
```

Fin de run, l'épilogue qui enseigne la grammaire :

```
Run completed: cheze_baseline.v3 [2b7a4dd2] 9m17s nse=0.78
exports: exports/cheze_baseline.v3/ (3 CSV)
next: hmp show cheze_baseline.v3 | hmp diff cheze_baseline.v2 cheze_baseline.v3 | hmp export cheze_baseline.v3
```

Règles transverses :

- **Flux de sécurité unique pour tout verbe destructif** : résoudre la référence, imprimer la
  carte d'identité (nom, id8, statut, date, taille, exports liés), prompt avec le coût, agir,
  dire la vérité sur ce qui est libéré ou non. Non-TTY sans `-y` : refus, exit 2.
- **Sorties scriptables** : `--format json/csv` sur une projection fixe de 12 colonnes (ids en
  strings, dates ISO, zéro blob config). L'actuel crashait : aucun consommateur à casser.
- **Thin wrapper respecté** : chaque verbe a sa fonction `_api` adossée à des méthodes de mixin
  catalogue ; les 654 LOC de logique du worker CLI migrent dans les mixins.

---

## 5. Surface Python

Deux points d'entrée, inchangés : `hmp.open()` (un workspace) et `hmp.index()` (fédération
machine). `SimulationCatalog` est renommé `Catalog`, `SimulationGroup` devient `RunSet` (clean
break, pas d'alias, conforme aux règles du repo). Le handle est connection-per-operation : il
n'ouvre DuckDB que le temps d'une requête, donc jamais de conflit ro/rw dans un même notebook.

```python
import hydromodpy as hmp

cat = hmp.open("~/ws/projects/cheze")        # read-only; ne migre jamais, ne touche pas le mtime

cat.df()                                      # 12 colonnes + métriques, du plus récent au plus ancien
best = cat.best("nse")                        # Run; scope canonique outlet, affiché dans le repr
top5 = cat.find(status="completed", nse_gt=0.8)

run = cat["ksweep/trial-013"]                 # même grammaire que la CLI, même résolveur
run = cat["@best:nse"]; run = cat["9c41"]

run.params                                    # {"hydraulic_conductivity": 8.6e-5, "sy": 0.05}
run.metrics                                   # {"nse": 0.86, "rmse": 0.11} (scope global/outlet)
head = run.read("head", time=-1, layer=0)
run.tag("+pinned"); run.note("best fit after widening Sy bounds")

run.export("trial13.hmp")                     # destination d'abord; sans var = archive complète
run.export("head.tif", var="head", time="last", resolution=50)

new = run.rerun(set={"flow.hydraulic_conductivity": 2e-4}, name="trial13_k2e4")
new.parent.id == run.id                       # lignée

run.delete()                                  # -> corbeille; PinnedRunError si pinned
cat.trash.restore("trial-004")

cat.sql("SELECT ... FROM metrics JOIN simulations USING (sim_id)")   # power user, read-only
```

Une seule règle d'export à retenir : **le premier argument est la destination** ; le format vient
de l'extension ; sans `var`, c'est l'archive complète. Identique en CLI (`-o` / `--var`).

`project.runs.latest()` est réimplémenté sur le `last()` du catalogue (l'actuel était un
`iloc[-1]` aveugle au statut qui contredisait la CLI). `run.rerun` passe par un protocole
`RerunProvider` enregistré dans `_bootstrap` (même pattern que `TrialPromotionProvider`) : la
layer matrix est respectée, `results` n'importe jamais `project`.

---

## 6. Export et import : une seule histoire

- `hmp export REF` sans aucun flag produit la vraie archive `.hmp` (le moteur route déjà
  `ExportFormat.hmp` vers `export_package` ; seule la CLI mentait). `hmp import FILE` restaure
  avec vérification des checksums, l'identité survit (même uuid, `imported_from` tracé, nom
  stem-versionné si déjà pris).
- Supprimés : `hmp data export-package` (fusionné) et le mensonge `hmp data export --format hmp`
  qui n'écrivait qu'un sidecar RO-Crate. `hmp data export` survit pour les données d'entrée.
- Export variable pour les collègues SIG/Excel : `hmp export REF --var head --to head.tif --time
  last` ; `--resolution` devient optionnel (le fallback moteur existe déjà, seule la CLI l'exigeait).
- **Adoption d'orphelins** : `hmp import <store-dir>` ré-enregistre un store présent sur disque
  mais absent du catalogue. Deux étages : legacy via les attributs ACDD écrits au finalize
  (dégradé : pas de config snapshot, donc pas de rerun) ; et désormais le finalize écrit un
  snapshot une-ligne `simulation.parquet` dans le dossier du run, rendant l'adoption sans perte.
  Un seul concept, "faire entrer un run dans le carnet", partagé par archives et orphelins.
- Archive multi-runs (`hmp export REF1 REF2 -o paper2026_runs.hmp`, prête pour Zenodo) : phase 4,
  bump de version du format ; en v1, N refs donnent N archives.

---

## 7. Suppression et cycle de vie : quatre étages, chacun réversible sauf le dernier

Mécanisme : corbeille par flip de colonne (greffe d'architecture-first sous l'UX d'ux-first).
Migration 0007 : statut `trashed`, colonnes `trashed_at`/`original_name`/`name_stem`/`version_int`,
tables `purge_journal`, `export_log`, `notes`. Aucun byte ne bouge au `rm` : un UPDATE est
instantané et atomique sur un store de 40 GB.

1. **`rm` = corbeille.** Carte d'identité, prompt, flip. Le stockage reste en place. Bulk :
   `--status failed`, `--tag draft`, une liste, une confirmation consolidée. `--keep-storage`
   disparaît (la corbeille le remplace en mieux : 30 jours, restaurable). Le message dit la
   vérité : "bytes freed at expiry or via hmp gc --apply".
2. **`trash restore`** rétablit ; si le nom a été repris, stem-versionnage automatique.
3. **`gc` = l'unique verbe de maintenance, planificateur par défaut.** Catégories : corbeille
   expirée, stores orphelins (avec taille), exports de runs purgés, lignes `running` au heartbeat
   mort (basculées `failed` uniquement sous `--apply`), rejeu du journal de purge, checkpoint
   DuckDB + consolidation Zarr (l'ancien `vacuum` est absorbé : deux verbes de maintenance aux
   défauts de sécurité opposés étaient un piège). `gc` ne migre jamais le schéma (ça devient
   `hmp doctor --migrate` : un verbe ne ment pas sur ce qu'il fait). Parce que la persona ne
   lance jamais de maintenance, la corbeille hors rétention est aussi expirée opportunistiquement
   dans les fenêtres d'écriture déjà ouvertes (registration/finalize), borné, pins respectés.
4. **Purge définitive journalisée en deux phases** (remplace le commit-puis-rmtree actuel et sa
   fenêtre d'orphelins) : journal `purge_pending` + flip, commit ; rmtree idempotent ; cascade des
   12 tables + clear du journal, commit. Un crash à n'importe quel point laisse soit une ligne
   restaurable, soit une entrée de journal que le prochain gc rejoue. **Invariant de régression :
   aucune séquence delete/gc/crash ne peut produire un byte inatteignable sous `simulations/`.**

**`pinned`** est un tag réservé (les tables existent, seul `add_tag` manque) : `rm`, `rm --now`,
l'expiry, et `if_exists="replace"` refusent un run pinné sans `--force`, en nommant le run et qui
l'a pinné. `hmp ls --tag pinned` est l'inventaire de publication.

---

## 8. Accès DB et concurrence

**Lecture (défaut partout).** `hmp.open()` et tous les verbes de lecture ouvrent en
`read_only=True` : pas de mkdir, pas de migration, pas de DDL persistant. Les 15 vues sont
recréées en TEMPORARY à chaque ouverture lecture (pattern GlobalIndex déjà en arbre, quelques
millisecondes ; le stamping persistant casserait les projets déplacés car les vues parquet
embarquent des globs absolus). Schéma en retard : erreur claire "run 'hmp doctor --migrate'",
jamais d'auto-migration sous un verbe de lecture. Le listing devient une projection SQL fixe de
12 colonnes avec WHERE/LIMIT côté SQL : fini les 2.6 MB de blobs JSON déplacés pour lister 100 runs.

**Écriture (interne au run).** La connexion rw tenue 557 s pendant tout le solve disparaît : la
durée de vie de connexion descend dans `DuckDBBackend` (une connexion par transaction, fermée au
commit), la façade reste vivante pour le run (chemins, handles zarr), donc aucun call-site ne
change et tous les écrivains mi-run vérifiés survivent. Le heartbeat devient un **sidecar JSON**
(`.hmp/running/<id8>.json`) : `hmp watch` et la détection de staleness lisent un fichier qui ne
peut jamais tenir le lock. Un solve ne touche le lock DuckDB qu'à l'enregistrement, aux
transactions bornées mi-run, et au finalize.

**Le contrat, en une phrase documentée : "tu peux toujours regarder pendant que ça tourne".**

Calibration parallèle : les writes d'un process passent par une file unique côté backend ;
les trials nommés à la suggestion suppriment la contention sur les compteurs de version.
Point de vigilance explicite (gate de perf en phase 3) : benchmarker connexion-par-transaction
contre connexion-par-étape sur le run cheze de 557 s avant de figer la granularité, DuckDB
checkpointant à la fermeture.

**Power users, trois étages** : (1) le vocabulaire `cat.find` (status, solver, tag, config_hash,
since, name_like, nse_gt=...) ; (2) `hmp sql` / `cat.sql` en read-only sur des vues stables
documentées (la page de doc des vues devient le contrat de schéma) ; (3) `cat.db_path` public
pour DBeaver/duckdb-CLI, documenté at-your-own-risk, avec un message dédié qui nomme le PID
détenteur du lock le cas échéant.

---

## 9. Les ruptures principales (clean breaks, tous justifiés)

Le repo interdit les shims et les alias : chaque renommage est franc. Les plus structurants :

| Avant | Après | Pourquoi |
|---|---|---|
| `simulation.run_id` + `name` | `simulation.name` seul | deux champs d'identité = la racine de la confusion |
| `on_collision="replace"` (défaut) | `if_exists="version"` (défaut) | le défaut actuel efface 19 noms sur 20 en une nuit de calibration |
| replace = nom NULLé, fantôme | hard-replace : prédécesseur versionné + corbeille | un store de 1 GB sans nom était le pire des deux mondes |
| `hmp catalog ls/show/delete/...` | verbes top-level `hmp ls/show/rm/...` | les utilisateurs pensent "runs", pas "catalog" |
| `catalog delete --keep-storage` | `hmp rm` -> corbeille 30 j restaurable | la corbeille fait mieux, sans aller simple |
| `catalog gc` destructif par défaut + `vacuum` | `gc` planificateur, `--apply` pour agir, vacuum absorbé | seul verbe qui détruisait sans confirmation |
| `data export-package` + `--format hmp` menteur | `hmp export REF` / `hmp import` | le moteur routait déjà correctement, seule la CLI mentait |
| basename `<project>__<name>__<hash8>` | `<project>__<id8>` immuable | rename/version/replace deviennent de purs UPDATE |
| `SimulationCatalog` rw à l'ouverture | `Catalog` read-only, connection-per-operation | lire ne doit pas modifier |
| connexion rw tenue tout le solve | connexions par transaction + heartbeat sidecar | inspecter pendant un run devient possible |
| `[simulation.results.export]` (3 niveaux) | `[export]` top-level, liste `variables` | le bloc le plus utilisateur était le plus enterré |
| 3 résolveurs de référence divergents | 1 résolveur, @-sélecteurs, scope strict | une grammaire, partout |

La liste exhaustive (27 ruptures avec justification une-ligne chacune) est dans la sortie du
workflow de design ; aucune ne casse un consommateur fonctionnel existant (le seul format
machine du listing crashait déjà).

---

## 10. Plan de réalisation : 4 phases livrables, 22 à 30 jours

**Phase 1 : identité et lectures honnêtes (7-9 j).** La migration 0007 porte TOUS les deltas de
schéma d'un coup (le catalogue ne migre qu'une fois). Rupture config (`name`, `if_exists`,
`[export]`, `hmp doctor --fix-config`, ~38 TOML in-tree mis à jour). Nommage : versioning par
stem, règle `.v1`, noms mémorables, `started_at`. Résolveur unique avec @-sélecteurs. Lecture
read-only partout, projection 12 colonnes, vues TEMPORARY, codes 20/21. Fusion export/import
mono-run, épilogue de fin de run.
*Critère de livraison : relancer 3x le même TOML donne trois lignes adressables et
`resolve('stem') == .v3` ; un `hmp ls` sur un projet archivé read-only ne touche pas son mtime.*

**Phase 2 : cycle de vie indulgent (6-8 j).** Corbeille (rm, trash ls/restore/empty),
hard-replace, purge journalisée + `rm --now`, gc planificateur/apply absorbant vacuum + orphelins
+ stale-running + expiry opportuniste, `add_tag` + verbes tag/note/rename + garde `pinned`,
`export_log` + RUN.txt, adoption d'orphelins, migration de la logique worker vers les mixins.
*Critère : une suite d'injection de fautes prouve qu'aucune séquence delete/gc/crash ne laisse un
byte inatteignable ; un run pinné survit à tous les chemins destructifs sans `--force`.*

**Phase 3 : runs vivants et lignée (6-8 j).** Connexions par transaction dans le backend,
heartbeat sidecar JSON, `hmp watch`, rendering "stale" partout, journal/scratch keyés par id8 +
`hmp run --resume REF`, `hmp rerun --set/--reuse` via RerunProvider, trials nommés à la
suggestion, `hmp diff`, benchmark de granularité (gate de perf).
*Critère : ls/show/watch ne bloquent jamais pendant deux solves concurrents ; un SIGKILL mi-solve
donne un rendu "stale", puis un seul `gc --apply` guérit la ligne.*

**Phase 4 : partage et échelle (3-5 j).** Archive multi-runs, `hmp ls --config FILE.toml`
(filtre par config_hash), filtres mots-clés sur la fédération, page de doc des vues comme contrat
de schéma, extension du payload de progression du heartbeat (gatée sur le benchmark).
*Critère : un `paper2026_runs.hmp` de trois runs fait l'aller-retour vers une machine vierge avec
provenance intacte.*

Chaque phase est livrable indépendamment ; le seul couplage inter-phases est la migration 0007
qui part entière en phase 1.

---

## 11. Risques acceptés et compromis (issus du red team)

- Une connexion read-only externe garée (DBeaver) peut affamer un enregistrement : risque accepté,
  mitigé par un message qui nomme le PID détenteur et documente `hmp sql` comme porte supportée.
- Le coût de la connexion-par-transaction sur le chemin chaud journal/events est non mesuré :
  gate de benchmark explicite en phase 3 avant de figer.
- Les pins oubliés pour toujours : rendus au moins visibles (catégorie informative du plan gc,
  âge + taille).
- La corbeille ne libère pas le disque immédiatement : assumé et dit en clair dans le message de
  `rm`, avec l'expiry opportuniste en filet pour les utilisateurs qui ne lancent jamais gc.
- L'homonymie package `hydromodpy.catalog` vs classe `Catalog` : documentée, pas masquée.

---

## 12. Corrections post-validation (2026-06-11) - spec d'exécution faisant foi

Validation adversariale : 11 agents, vérification file:line contre le code réel, red team
conformité CLAUDE.md, critique de complétude/séquencement. Verdict global : la thèse UX et
~70 % des claims tiennent ; mais plusieurs faits sont faux ou sous-spécifiés, et il existe
un blocage de règle. Cette section corrige les §1-11 et fait autorité sur l'implémentation.
Décision utilisateur actée : **clean break assumé, on casse le fonctionnement actuel et on
corrige après** ; pas de shim, pas de compat. Les TOML sous `examples/projects/` (off-limits)
cassent sous `extra="forbid"` jusqu'à `hmp doctor --fix-config` ; je ne les édite pas.

### 12.1 Faits corrigés (le plan disait faux)

| Plan | Réalité (file:line) | Conséquence |
|---|---|---|
| basename `<...>__<hash8>` | 3e segment = `short_uuid` = 8 hex du **sim_id**, pas un hash (`storage_paths.py:57-59`) | terminologie : c'est **id8**, pas hash8 ; unicité par id, pas par contenu |
| basename id-only = « 3 lignes » | aussi : param `name` mort, 2 call-sites (`registration.py:275`, `hmp_package.py:841`), re-dérivation au restore `.hmp` (`hmp_package.py:838-846`), test `test_result_storage_layout.py:46` | petit changement **multi-fichiers** |
| « 15 vues recréées » | exactement **10** (5 `ensure_views` + 5 `ensure_parquet_views`) ; `v_workflow_heartbeats` créée une fois par 0004 | chiffre |
| `helpers.resolve_sim_id` « code mort » | **confirmé mort** (0 caller, défini + `__all__` seulement) ; un agent s'est trompé, 2 autres avec grep confirment | suppression OK |
| `[export]` « simple promotion » | `ExportConfig` réel = `csv_timeseries`/`vtu`/`geotiff`/`shapefile`/`variables`(objet de toggles)/`resolution`/`artifacts` ; **ni `csv`, ni `package`, ni `times`, ni `variables` liste** | c'est une **refonte de forme** + ajout root sur `HydroModPyConfig` + retrait de `ResultsConfig.export` + rewire `post_run.py:357` |
| champs `[simulation]` incluent `tags` | **pas de champ `tags`** dans `SimulationConfig` | `tags` est à **créer** |
| verbes catalog « adossés à `_api` » | ils wrappent `cli/_workers/catalog.py` (653 LOC) ; `_api` n'a **aucun** verbe catalog | migration worker→mixins + ajout `_api` = **net-new** |
| `project.runs.latest` réimplémenté sur `last()` | la méthode est `latest()` (`discovery.py:233`), et elle **lève** `KeyError` (vs `None` aujourd'hui) | adapter le contrat raise/None |
| `run.rerun/parent/tag/note/delete` (montrés comme existants) | **aucun** n'existe sur `Run` (`run.py` = export + propriétés RO + `parent_sim_id` str) | net-new |
| connexion-par-opération « aucun call-site ne change » | faux : `self._db` utilisé en direct (`writes_parquet.py:202/437/450/456`, `reads.py:379`, `writes_duckdb.py:701`) + escape hatch public `.connection` (`audit_prune`) | rerouter ces sites |
| migration 0007 = `name_stem`+`version_int` | très insuffisant (voir 12.3) | 0007 doit porter **tout** le schéma Phase 1+2 |
| `started_at` à ajouter en 0007 | colonne **déjà** déclarée (`0001:216`), jamais **écrite** | pas de DDL, juste écrire à l'INSERT |
| `notes` (table) | collision avec colonne `simulations.notes` (`0001:220`) | table renommée `sim_notes` + migration de la colonne |
| « 0007 est le seul couplage inter-phases » | Phase 3 (journal/scratch keyés id8) exige `workflow_steps.run_id` → **migration 0008** | corriger : 2 migrations |
| exit codes 20/21 | n'existent pas (stop à 19) ; `SimulationNotFoundError`/`AmbiguousReferenceError` sont des `KeyError` non mappés | ajouter constantes + dé-`KeyError` ou mapping explicite |

### 12.2 Blocages et fixes de règle CLAUDE.md

1. **OFF-LIMITS / extra=forbid (résolu par décision utilisateur).** 42 TOML portent
   `on_collision`/`run_id`/`[simulation.results.export]` ; 36 sous `examples/projects/`
   (off-limits + 19_cheze a des modifs non commitées), 6 éditables
   (`tests/regression/fixtures/projects/simulation_regression/`). Décision : on casse,
   je n'édite que les 6 fixtures + je livre `hmp doctor --fix-config` ; l'utilisateur migrera
   ses projets. `test_examples_projects_load.py` casse → assumé.
2. **`dispatch.py:217` `getattr(ctx.cfg.simulation, "on_collision", "replace")`** = fallback
   défensif interdit. À remplacer par lecture directe `ctx.cfg.simulation.if_exists`
   (le `:134` est déjà propre) et **supprimer** le getattr dans le commit de rename.
3. **gc/vacuum NE migrent PAS dans une mixin results.** `cli/_workers/catalog.py:616` importe
   `hydromodpy.data.registry._backend.DuckDBCacheBackend` : `results -> data` viole la matrice
   ET importe un `_backend` privé cross-package. Donc : seules les opérations DuckDB-catalog
   pures (`delete/trash/restore/list/show/query`) descendent dans `results/catalog/` ;
   le nettoyage cache/géo/tmp-parquet/zarr reste en `cli/_workers` ou `_api`. Ne pas concentrer
   dans `facade.py` (410 LOC / 19 méthodes) : répartir sur discovery/lifecycle/reads.
4. **`RerunProvider` Protocol vit dans `results/` (ou calibration), pas `project/`.** Miroir de
   `TrialPromotionProvider` (Protocol en `calibration/runners/contracts.py`, impl en
   `project/dispatch/`, enregistré par `_bootstrap.py`). Sinon `results -> project` (interdit).
5. **Rename `SimulationCatalog`→`Catalog` / `SimulationGroup`→`RunSet`** : 156 + 12 fichiers,
   plus `_lazy.py:104-106`, `results/catalog/__init__.py:__all__`,
   `test_api_public_consistency.py` (asserte `LAZY_IMPORTS keys == __all__`). Pure churn
   cosmétique, zéro gain fonctionnel, collision avec le package `hydromodpy.catalog`.
   **Séquencé en dernier** (pass mécanique), pas prérequis. Pas de double entrée `__all__`
   (sinon re-export interdit).

### 12.3 Migration 0007 - spec complète (porte tout le schéma Phase 1+2)

Un seul fichier `0007_simulation_lifecycle.sql`, appliqué en transaction par le runner
(`core/migrations/runner.py`, checksum figé après application). DuckDB ne peut pas `ALTER` un
CHECK → recréation de table avec copie verbatim.

- **statuses** : `INSERT INTO statuses (id, code) VALUES (8, 'trashed');`
- **simulations** : `ALTER ADD COLUMN name_stem VARCHAR`, `version_int INTEGER`,
  `trashed_at TIMESTAMPTZ`, `original_name VARCHAR`. Backfill :
  `name_stem = regexp_replace(name,'\.v[0-9]+$','')`,
  `version_int = coalesce(try_cast(regexp_extract(name,'\.v([0-9]+)$',1) AS INTEGER),1)`.
  Index `ix_sim_name_stem ON (project, name_stem, version_int)`. (Remplace le scan LIKE bugué.)
- **audit_log** : recréer avec CHECK élargi (+ `sim.trash`, `sim.restore`, `sim.purge.begin`,
  `sim.purge.commit`, `export.write`) en copiant **toutes** les colonnes (dont `prev_hash`/
  `chain_hash`) verbatim → hash-chain 0002 préservée ; recréer les 4 index + `ix_audit_chain_hash`.
- **sim_notes** (net-new, append-only) : `(note_id UUID PK, sim_id UUID, note VARCHAR,
  added_at TIMESTAMPTZ, added_by VARCHAR)`. Migrer les `simulations.notes` non-NULL vers
  `sim_notes`, puis `ALTER TABLE simulations DROP COLUMN notes` ; rewire `registration.py:308/351`.
- **export_log** (net-new) : `(export_id UUID PK, sim_id UUID, kind VARCHAR, rel_path VARCHAR,
  bytes BIGINT, sha256 VARCHAR, created_at TIMESTAMPTZ)`.
- **purge_journal** (net-new, crash-safety 2 phases) : `(sim_id UUID PK, phase VARCHAR
  CHECK(phase IN ('pending','rmtree_done')), requested_at TIMESTAMPTZ, requested_by VARCHAR)`.
  `deletions` (tombstone GDPR, déjà là, non peuplée aujourd'hui) reste le registre final de purge.
- **constants.py** : ajouter `sim_notes`, `export_log` à `PER_SIM_TABLE_NAMES:53` (cascade/purge).
- **Tests** : `test_schema_migrations.py` 6→7 (lignes 71/72/88).

### 12.4 Décisions de conception tranchées

- **Read-only vs writer (même façade).** `__init__` gagne `read_only: bool = False`. `True` :
  `duckdb.connect(read_only=True)`, pas de mkdir/migration, vues en `TEMPORARY` (pattern
  `global_index.py:390`), erreur claire si schéma en retard. `hmp.open()` passe `read_only=True`
  par défaut ; le writer du workflow utilise `from_workspace(...)` (rw), donc le solve n'est pas
  touché. Pas de classe séparée.
- **@best/@worst scope.** Canonique = station `__outlet__` (`OUTLET_STATION`,
  `constants.py:14`) ; `rank/best/worst/find` gagnent un prédicat `station_id = '__outlet__'`.
  Chaque sortie imprime le scope résolu. (`variable` reste libre : `metric_name` la porte déjà.)
- **`[export]` Phase 1 minimal.** Promotion top-level `[export]` = `ExportConfig` actuel déplacé
  sous `HydroModPyConfig.export`, retiré de `ResultsConfig`. `package: bool` et `times` ajoutés ;
  `csv_timeseries` gardé (pas renommé `csv` : un alias serait un shim). La liste `variables`
  reste un objet de toggles (pas une liste) en Phase 1. Rewire `post_run.py:357`, step export.
- **run_id → name.** Supprimer `simulation.run_id` **après** avoir repointé
  `setup.py:399-405` et `hydromodpy_config.py:426-428` pour dériver `setup_state.run_id`
  (clé interne journal/scratch, conservée) depuis `simulation.name` (ou stem TOML). La clé
  interne `run_id` du workflow **reste** (renommer 40 sites = Phase 3) ; seul le champ config part.

### 12.5 Ordre de commit Phase 1 (sans laisser l'arbre rouge entre commits)

1. **0007** (schéma seul, 12.3) + `constants.py` + `test_schema_migrations` 6→7. *Importable.*
2. **started_at** écrit à l'INSERT (`registration.py`) + **versioning par stem** (`name_stem`/
   `version_int`, remplace `_next_available_version` LIKE) + basename id-only.
3. **Rename `on_collision`→`if_exists`** (défaut `version`) sur `config.py:359` +
   `registration.py` + `protocol.py` + `dispatch.py:134/217` (suppr getattr) +
   `child_materialization.py` + 6 fixtures + tests `test_on_collision_*`→`test_if_exists_*`.
4. **Suppr `simulation.run_id`** après repointage `setup.py`/`hydromodpy_config.py`.
   Ajout champ `tags` sur `SimulationConfig`.
5. **`[export]`** top-level (12.4) + rewire consommateurs.
6. **Résolveur** : @-sélecteurs (`@last`, `@last~N`, `@best:metric` scopé outlet, `@running`
   best-effort), résolution stem→version récente, hint corrigé, erreurs non-`KeyError` +
   exit 20/21, suppression matcher viz divergent + `resolve_sim_id` mort.
7. **Read-only** : `hmp.open(read_only=True)` + mode façade + projection 12 colonnes +
   fix `ls --format json` (CAST sim_id VARCHAR au niveau SQL).
8. **`hmp doctor --fix-config`** (tomlkit, `core/toml_io/io.py:166`) : `on_collision`→`if_exists`,
   suppr `run_id`, montée `[export]`.
9. **Export/import** mono-run + épilogue de fin de run.

Rename de classe `Catalog`/`RunSet` : pass mécanique final, hors séquence fonctionnelle.

### 12.6 Re-scope honnête

Le plan d'origine estime 22-30 j. En exécution autonome je livre d'abord le **socle Phase 1
fonctionnel** (identité honnête + lectures honnêtes : 0007, started_at, versioning, résolveur,
read-only), vérifié (ruff + pytest ciblé). Les pièces à forte churn ou multi-phases (rename de
classe 156 fichiers, connexion-par-transaction + heartbeat sidecar, trash/purge complets,
`hmp watch`/`diff`/`rerun`, federation) sont livrées ensuite et signalées explicitement quant à
leur état réel. Aucune complétion n'est annoncée sans vérification.

---

## 13. État d'implémentation et reprise (2026-06-12)

**Point d'entrée pour une nouvelle session.** Cette refonte est partiellement implémentée sur
`dev-lakeres_refact` (25 commits, tous ruff-clean). Suite de tests affectée : **1977 passed,
1 failed, 3 skipped**. Le seul rouge est `test_examples_projects_load` (TOML sous
`examples/projects/` off-limits, à migrer via `hmp doctor --fix-config`). `test_derived_mass_seepage`
est un échec **préexistant** (ImportError `_positive_cell_flux`), hors périmètre. Détail complet et
exemples : `etat_refonte_simulations.md` ; référence CLI à jour : `docs/source/cli/catalog.rst`.

### 13.1 Fait (vérifié, commité)

- **Migration `0007_simulation_lifecycle.sql`** : tout le schéma Phase 1+2 (statut `trashed`,
  `name_stem`/`version_int`/`trashed_at`/`original_name`, `audit_log` recréé CHECK élargi +
  hash-chain préservée, tables `sim_notes`/`export_log`/`purge_journal`). v6 -> v7.
- **Identité** : `run_id` supprimé, `on_collision` -> `if_exists` (défaut `version`), `tags`
  ajouté, versioning par stem (démote en `.v1` + `.vN`), `started_at` écrit, basename id-only
  `<project>__<id8>`, noms mémorables.
- **Résolveur** : @-sélecteurs (`@last`/`@last~N`/`@best:M`/`@worst:M` scopés outlet/`@running`),
  stem -> dernière version, erreurs `ReferenceResolutionError` + exit 20, suggestions, kill des
  matchers divergents. `find/best/worst` scopés outlet ; `find(config_hash=/name_stem=)`.
- **Lectures honnêtes** : `hmp.open(read_only=True)` par défaut + mode façade (vues TEMPORARY),
  workers `ls`/`show` read-only, fix crash `ls --format json` + projection 12 colonnes,
  `ls --status/--tag`.
- **Cycle de vie** : engine catalog `add_tag`/`write_tags`(corrigé)/`add_note`/`trash`/`restore`/
  `empty_trash` + garde `pinned` ; `gc` planificateur (`--apply`). CLI : `tag` `note` `rename`
  `trash` `restore` `delete`(->corbeille,`--now`) `diff` `watch` `export` `import` `rerun`.
- **Outils** : `hmp doctor --fix-config` (rewriter TOML) et `--migrate` ; épilogue de fin de run.
- **API Python** : `Run.tag/note/delete/parent` (les DataFrames `Run.parameters`/`metrics` restent).
- **`rerun` via `RerunProvider`** (Protocol dans `results/rerun_contract.py`, impl
  `project/dispatch/rerun.py`, enregistré dans `_bootstrap.py` ; matrice de couches respectée).

### 13.2 Reste à faire (ordre de reprise suggéré)

1. **Connexion-par-transaction + heartbeat sidecar JSON** `.hmp/running/<id8>.json`. Le plus
   impactant ET le plus risqué : touche le hot-path du solve (557 s). **Gate de benchmark
   obligatoire** (connexion-par-transaction vs par-étape sur le run cheze) avant de figer ;
   rewire la staleness gc/doctor + les `self._db` directs (`writes_parquet`/`reads`/`writes_duckdb`).
2. **`hmp run --resume REF`** : exige une **migration 0008** (re-keyer `workflow_steps.run_id`
   par id8 ; le journal est keyé par nom aujourd'hui).
3. **`[export]` top-level** : refonte de forme (l'`ExportConfig` réel a `csv_timeseries` + toggles,
   pas `csv`/liste/`package`/`times`) + retrait de `ResultsConfig.export` + rewire `post_run.py`
   et le step export.
4. **Purge journalisée 2 phases** : `purge_journal` existe mais `empty_trash` fait un `delete`
   simple (commit-puis-rmtree) ; convertir pour l'invariant « aucun byte inatteignable », plus
   `gc` absorbant vacuum + orphan stores + expiry corbeille ; orphan adoption + `RUN.txt` +
   consommateur `export_log`.
5. **Fédération** : filtres mots-clés GlobalIndex ; archive multi-runs (`export REF1 REF2`).
6. **Rename `SimulationCatalog`->`Catalog` / `SimulationGroup`->`RunSet`** : 156 + 12 fichiers +
   `_lazy.py` + `__all__` + `test_api_public_consistency`. Pure churn, **en DERNIER**, jamais
   prérequis. Faire via une passe mécanique vérifiée. NE PAS migrer `gc`/`vacuum` dans une mixin
   `results` (le worker importe `data.registry._backend` -> violerait la matrice).

### 13.3 Garde-fous pour la reprise

- Off-limits `examples/projects/` : ne pas éditer ; les TOML cassés se migrent via
  `hmp doctor --fix-config`.
- Tout commit : `ruff check --fix` + `ruff format`, puis `pytest` ciblé sur la zone touchée.
  Vérifier `tests/unit/architecture/test_layer_matrix.py` après tout nouvel edge d'import.
- `Run` est à 50 méthodes publiques (cap CLAUDE.md). Toute nouvelle méthode sur `Run` exige d'en
  retirer une.
