# Audit du transport existant

Date : 2026-05-14

Statut : audit basé sur l'inspection du code local, des tests unitaires et des
régressions existantes. Aucun workflow complet de transport n'a été relancé et
aucun solveur externe MODPATH, MT3DMS ou MODFLOW 6 GWT n'a été exécuté dans cette
passe.

## Résumé exécutif

Le transport existe réellement dans HydroModPy, mais il est moins accompli que
les parties flow, comparaison, résultats et Boussinesq. La plomberie
architecturelle est présente : configuration, planification, adapters, exécution
après le flow, extraction vers le catalogue et quelques dérivés. En revanche, la
partie transport reste fragile sur trois axes :

- validation physique limitée ;
- couverture source/puits encore étroite ;
- intégration incomplète avec calibration, observations eau qualité et registre
  de résultats.

Les trois familles de transport n'ont pas le même niveau de maturité :

| composant | maturité observée | commentaire |
|---|---|---|
| MODFLOW 6 GWT | moyenne | chemin moderne, branché au launcher et aux régressions, mais limité surtout à la concentration portée par la recharge |
| MT3DMS | moyenne | chemin legacy NWT assez opérationnel, avec post-traitements historiques, mais validation scientifique limitée |
| MODPATH | faible à moyenne | pré-processing riche, mais ingestion catalogue et tests de sorties pathlines/endpoints insuffisants |
| calibration transport | faible | adapters explicites, mais extraction calibration non implémentée |
| water quality observations | faible | données chargeables, mais pas encore reliées proprement à une simulation/calibration transport |
| résultats dérivés transport | faible à moyenne | dérivés présents, mais certaines conventions physiques sont ambiguës |

Conclusion courte : le transport est au stade "capacité branchée", pas encore au
stade "capacité scientifiquement robuste".

## Fichiers inspectés

Fichiers principaux :

- `hydromodpy/physics/transport/transport_config.py` ;
- `hydromodpy/physics/transport/transport.py` ;
- `hydromodpy/solver/base/registry.py` ;
- `hydromodpy/simulation/planning/planner.py` ;
- `hydromodpy/simulation/execution/runner.py` ;
- `hydromodpy/simulation/adapters/transport_helpers.py` ;
- `hydromodpy/simulation/extraction/post_run.py` ;
- `hydromodpy/simulation/extraction/extractors/derived.py` ;
- `hydromodpy/simulation/planning/results_config.py` ;
- `hydromodpy/results/field_registry.py` ;
- `hydromodpy/solver/modflow6/transport.py` ;
- `hydromodpy/solver/modflow6/adapters/transport.py` ;
- `hydromodpy/solver/modflow6/extractors/transport.py` ;
- `hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py` ;
- `hydromodpy/solver/modflow_nwt/adapters/transport_mt3dms.py` ;
- `hydromodpy/solver/modflow_nwt/extractors/mt3dms.py` ;
- `hydromodpy/solver/modflow_nwt/modpath/modpath.py` ;
- `hydromodpy/solver/modflow_nwt/modpath/_pre_processing.py` ;
- `hydromodpy/solver/modflow_nwt/modpath/_post_processing.py` ;
- `hydromodpy/solver/modflow_nwt/modpath/_filt_processing.py` ;
- `hydromodpy/solver/modflow_nwt/modpath/_resolvers.py` ;
- `hydromodpy/solver/modflow_nwt/adapters/transport_modpath.py` ;
- `hydromodpy/solver/modflow_nwt/extractors/modpath.py` ;
- `hydromodpy/solver/modflow_common/mt3dms_extractor_base.py`.

Tests et docs inspectés :

- `tests/unit/simulation/test_transport_common.py` ;
- `tests/unit/solver/modflow_nwt/test_mt3dms_postprocessing.py` ;
- `tests/unit/solver/modflow_nwt/test_modpath_runtime_builder.py` ;
- `tests/unit/workflow/test_modpath_ingestion.py` ;
- `tests/unit/solver/test_solver_registry.py` ;
- `tests/regression/fixtures/projects/launcher_simulation/*.toml` ;
- `tests/regression/reference/golden_references/**/*.json` ;
- `tests/validation/README.md` ;
- `tests/validation/analytical/transient/test_ogata_banks.py` ;
- `docs/source/about/roadmap.rst` ;
- `docs/source/capability_gallery/simulation.rst` ;
- `docs/source/theory/solvers/flow/modflow/transport-coupling.rst`.

## Architecture générale

Le transport est intégré au même pipeline que les autres processus :

1. La configuration `TransportConfig` expose trois solveurs :
   `modpath`, `mt3dms`, `modflow6gwt`.
2. Le planner transforme un processus `transport` en runs concrets, par exemple
   `transport_main::mt3dms` ou `transport_main::modflow6gwt`.
3. Le runner crée `state.setup.transport` si nécessaire et résout le modèle flow
   amont compatible.
4. L'adapter transport instancie le solveur concret et l'exécute.
5. `post_run_results()` récupère l'extracteur associé au solveur, ingère les
   sorties brutes dans le catalogue, puis lance les dérivés demandés.

Ce chemin est sain conceptuellement. Le registre déclare explicitement les trois
adapters de transport :

- `transport/modpath` vers `ModpathTransportAdapter` ;
- `transport/mt3dms` vers `Mt3dmsTransportAdapter` ;
- `transport/modflow6gwt` vers `Modflow6GwtTransportAdapter`.

Les capacités sont aussi typées :

- `modpath` produit des particules ;
- `mt3dms` et `modflow6gwt` produisent de la concentration.

Point important : la robustesse actuelle porte surtout sur cette plomberie. Elle
ne prouve pas encore que les hypothèses hydrochimiques et les conversions de
sources/puits soient suffisamment générales.

## Configuration et objet `Transport`

`TransportConfig` hérite de `ProcessSpatialConfig`, mais plusieurs champs
spatiaux génériques sont exclus de la sérialisation transport. Le transport a
donc un support config dédié, mais ne réutilise pas vraiment toute la richesse
spatiale des autres processus.

Les paramètres concentration sont communs à MT3DMS et GWT :

- nom d'espèce ;
- concentration initiale ;
- concentration de recharge ;
- dispersivité longitudinale ;
- dispersivités transversales relatives ;
- diffusion ;
- ordre de réaction ;
- décroissance ;
- option de tracé.

L'objet `Transport` lui-même est mince. Il contient trois sous-composants
`modpath`, `mt3dms`, `modflow6gwt`, recopie les paramètres de config, et expose
quelques méthodes utilitaires. Il ne porte pas encore une logique métier forte
du type "construire des sources de concentration depuis les données eau qualité"
ou "mapper les observations de concentration vers les cellules".

Interprétation : le transport a une façade de configuration, mais pas encore un
modèle de domaine aussi développé que le flow.

## MODFLOW 6 GWT

### Ce qui existe

`hydromodpy/solver/modflow6/transport.py` construit un modèle GWT couplé au GWF
existant. Le chemin inclut :

- un IMS spécifique au GWT ;
- un modèle `ModflowGwt` ;
- une grille DISV issue du `solver_mesh` du flow ;
- `GWTIC` pour la concentration initiale ;
- `GWTADV` avec schéma upstream ;
- `GWTDSP` pour dispersion/diffusion ;
- `GWTMST` pour porosité et décroissance ;
- `GWTSSM` pour les sources ;
- un échange `GWF6-GWT6` ;
- un OC qui écrit concentration et budget.

Le chemin est bien aligné avec l'architecture MF6 et semble être la voie
stratégique pour le transport moderne.

### Limites observées

La source de concentration est actuellement très centrée sur la recharge. Le code
exige un package recharge GWF existant, puis injecte l'auxiliaire
`CONCENTRATION` dans `RCHA`. Le `SSM` est construit avec :

```text
("RCHA", "AUX", "CONCENTRATION")
```

Ce choix couvre les scénarios où le soluté arrive par la recharge. Il ne couvre
pas encore proprement les concentrations portées par des frontières ou sources
comme CHD, WEL, RIV ou autres packages.

Un autre point à vérifier est l'indexation temporelle de `sconc_input`. Dans le
chemin GWT, `_build_crch()` parcourt `range(nper)` et lit `self.sconc_input.get(k)`.
Cela suppose des clés 0-based. Les helpers communs de runtime concentration
normalisent certains mappings en périodes 1-based dans les tests. Ce décalage
potentiel doit être vérifié avec un test ciblé GWT.

### Niveau de confiance

Confiance moyenne. Le chemin est présent et utilisé dans des fixtures de
régression launcher MF6, mais la validation analytique Ogata-Banks ne passe pas
encore par la plomberie HydroModPy. Le test analytique construit directement un
couplage GWF + GWT avec FloPy.

## MT3DMS

### Ce qui existe

`hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py` est le chemin concentration du
couple NWT/MT3DMS. Il utilise :

- le binaire `mt3dusgs` ;
- les overrides runtime via `build_concentration_runtime_overrides()` ;
- `Mt3dBtn` ;
- `Mt3dAdv` ;
- `Mt3dDsp` ;
- `Mt3dRct` ;
- `Mt3dSsm` ;
- la copie de `MT3D001.UCN` vers un nom stable ;
- un post-processing historique qui peut exporter concentration, concentration
  seepage, mass seepage et masse accumulée.

L'extracteur moderne réutilise `Mt3dmsExtractorBase`, qui lit le fichier `.ucn`
et écrit le champ `concentration` dans le catalogue.

### Limites observées

MT3DMS dépend du monde NWT et de ses conventions legacy. Le chemin semble
fonctionnel, mais reste moins intégré que les sorties flow modernes :

- source/sink semantics limitées ;
- paramètres exposés majoritairement au profil DEV ;
- calibration concentration absente ;
- validation analytique HydroModPy non démontrée ;
- post-processing en partie historique, en partie catalogue moderne.

### Niveau de confiance

Confiance moyenne. La plomberie est couverte par des tests unitaires et des
goldens NWT avec signatures `mt3dms_expected`, mais ce n'est pas encore une
validation scientifique complète.

## MODPATH

### Ce qui existe

MODPATH est le chemin particules du couple NWT/MODPATH. Le pré-processing est
relativement riche :

- résolution de `zone_partic` ;
- support de l'alias `domain` ;
- support de l'alias `seepage_clip` ;
- construction de raster clipé de seepage ;
- création des fichiers de départ ;
- lancement via le binaire `mp6`.

Il existe aussi du code legacy de post-processing et filtrage :

- écriture de shapefiles ;
- filtrage de pathlines ;
- calculs pondérés par flux.

### Limites observées

L'adapter moderne saute explicitement `post_processing()` et `filt_processing()`
legacy. Il s'appuie sur `ModpathOutputAdapter.extract()` pour lire les
pathlines/endpoints dans le catalogue. Cette migration est saine dans l'idée,
mais l'ingestion catalogue semble moins mature que le pré-processing.

Point suspect dans `hydromodpy/solver/modflow_nwt/extractors/modpath.py` :

- l'extracteur ouvre le store Zarr ;
- écrit `endpoint_x`, `endpoint_y`, `endpoint_z` ;
- ferme le store dans `finally` ;
- puis tente d'écrire `endpoint_time` avec le groupe obtenu avant fermeture.

Cela ressemble à un bug probable, surtout si un fichier endpoint non vide est
rencontré. Le fait que les goldens NWT contiennent `modpath_expected: {}` réduit
la capacité des tests actuels à attraper ce type de problème.

### Niveau de confiance

Confiance faible à moyenne. La préparation MODPATH est développée, mais les
sorties pathlines/endpoints ne semblent pas verrouillées par une régression
non vide. MODPATH devrait être considéré comme moins accompli que MT3DMS et GWT.

## Extraction et champs dérivés

Les extracteurs concentration lisent les fichiers `.ucn` et écrivent
`concentration` dans le store. Ensuite les dérivés transport peuvent produire :

- `concentration_seepage` ;
- `mass_seepage` ;
- `mass_accumulated`.

Ces dérivés sont utiles, mais certaines conventions sont discutables.

### `concentration_seepage`

Le docstring indique "Zero elsewhere", mais le code écrit `NaN` hors seepage :

```python
result = np.where(seepage > 0, conc * seepage, np.nan)
```

Ce choix peut être acceptable, mais il doit être documenté. Une valeur nulle et
une valeur `NaN` ne portent pas la même signification :

- `0` signifie concentration ou contribution nulle ;
- `NaN` signifie pas de donnée ou hors domaine d'interprétation.

### `mass_seepage`

Le dérivé utilise le budget drain si disponible. S'il ne trouve pas de clé drain,
il remplace le flux par un tableau de `1`. C'est risqué :

```python
flux = np.ones(n_cells, dtype="float64")
```

Cela peut produire une grandeur appelée "mass_seepage" qui est en réalité une
concentration masquée, pas une masse ou un flux de masse. Il serait plus sûr de
ne pas calculer `mass_seepage` sans flux drain exploitable, ou d'écrire un statut
explicite.

### `mass_accumulated`

La masse accumulée est une somme simple des `mass_seepage` successifs. Il n'y a
pas de pondération temporelle explicite par la durée de pas. Si `mass_seepage`
est un flux, alors l'accumulation devrait probablement intégrer `flux * dt`.

### Registre de champs

`hydromodpy/results/field_registry.py` déclare `concentration`, mais pas les
champs dérivés transport ni `pathlines`. Cela rend ces sorties moins visibles et
moins auto-documentées dans l'API résultats.

## Calibration et observations eau qualité

Les adapters transport exposent une méthode `extract_calibration_series()`, mais
elle lève explicitement `NotImplementedError` :

- MODFLOW 6 GWT : extraction calibration non implémentée ;
- MT3DMS : extraction calibration non implémentée ;
- MODPATH : extraction calibration particules non implémentée.

Côté calibration générale, les chemins actuellement pris en charge sont surtout
`discharge` et `head`. Les commentaires de config mentionnent la possibilité de
combiner des signaux transport, mais le moteur de métriques ne dispose pas encore
d'un vrai chemin concentration/eau qualité.

Les données `water_quality` existent dans les data managers, mais l'audit ne
montre pas de lien abouti :

- ingestion eau qualité ;
- mapping station vers cellule ;
- extraction concentration simulée ;
- alignement temporel observation/simulation ;
- fonction objectif concentration ;
- calibration de paramètres transport.

Interprétation : l'eau qualité est présente comme famille de données, mais pas
encore comme boucle complète de simulation/calibration transport.

## Tests et validation

Tests ciblés exécutés pendant cet audit :

```powershell
python -m pytest tests/unit/simulation/test_transport_common.py tests/unit/solver/modflow_nwt/test_mt3dms_postprocessing.py tests/unit/solver/modflow_nwt/test_modpath_runtime_builder.py tests/unit/workflow/test_modpath_ingestion.py tests/unit/solver/test_solver_registry.py::test_transport_capabilities_are_explicit -q
```

Résultat :

```text
15 passed in 4.32s
```

Ce résultat confirme que les tests unitaires ciblés passent. Il ne confirme pas
que les solveurs externes produisent des résultats physiquement validés sur des
cas complets.

### Régression launcher

Les fixtures regression incluent :

- MF6 + `modflow6gwt` ;
- NWT + `mt3dms` ;
- dérivés `concentration_seepage` et `mass_seepage`.

Les goldens NWT contiennent aussi une section `modpath_expected`, mais elle est
vide dans les références inspectées. Cela limite fortement la portée de la
régression MODPATH.

### Validation analytique

Le benchmark Ogata-Banks valide un modèle MF6 GWF + GWT construit directement
avec FloPy. Le commentaire du test indique que le couplage n'utilise pas encore
la plomberie HydroModPy launcher. Cette validation est utile pour MF6 GWT, mais
elle ne valide pas encore le pipeline HydroModPy transport complet.

### Documentation

La roadmap marque explicitement `Transport coverage` en statut `Catch-up`.
La capability gallery mentionne MODFLOW 6 GWT comme solveur transport couvert.
La documentation de couplage rappelle les conventions actuelles :

- MF6 flow vers `transport/modflow6gwt` ;
- NWT vers `transport/modpath` et `transport/mt3dms` ;
- prudence avant toute comparaison transport sans contrôler grille,
  discrétisation temporelle, sources/puits, concentrations auxiliaires,
  packages et masques de post-processing.

## Points forts

1. Le transport n'est pas absent : il est intégré au planner, au runner, au
   registre d'adapters et au post-run.
2. Les capacités sont typées entre concentration et particules.
3. GWT est présent dans le chemin MF6 moderne.
4. MT3DMS dispose d'un chemin legacy assez complet.
5. Les extracteurs concentration partagent une base commune.
6. Les résultats concentration sont persistés dans le catalogue.
7. Quelques dérivés transport existent déjà.
8. Les tests unitaires de plomberie ciblés passent.

## Points faibles

1. La validation physique est incomplète. Le test analytique GWT ne valide pas
   encore le pipeline HydroModPy launcher.
2. Les sources de concentration sont trop centrées sur la recharge.
3. La calibration transport n'est pas implémentée.
4. Les observations `water_quality` ne sont pas encore reliées à un cycle
   simulation/calibration transport.
5. MODPATH n'a pas de golden non vide de pathlines/endpoints.
6. L'extraction endpoint MODPATH contient un bug probable autour de la fermeture
   du store.
7. Les dérivés transport ont des conventions physiques ambiguës.
8. Les champs dérivés transport ne sont pas inscrits dans le registre public des
   champs.
9. Les validations externes MODPATH et MT3DMS ne sont pas requises par la suite
   de validation courante.
10. Les adapters transport ont des `validate()` vides, donc peu de préconditions
    sont vérifiées avant lancement.

## Priorités recommandées

### P0

1. Corriger et tester l'extraction MODPATH endpoint non vide.
2. Ajouter une régression MODPATH avec pathlines/endpoints réellement présents.
3. Ajouter un test GWT ciblé sur l'indexation temporelle de `sconc_input`.
4. Refuser ou marquer explicitement `mass_seepage` si aucun budget drain fiable
   n'est disponible.
5. Documenter la convention `NaN` vs `0` de `concentration_seepage`.

### P1

1. Faire passer le benchmark Ogata-Banks par le pipeline HydroModPy complet.
2. Étendre GWT aux concentrations auxiliaires sur d'autres packages que `RCHA`.
3. Ajouter des validateurs adapters :
   - flow compatible ;
   - package recharge disponible si requis ;
   - dimensions concentration/périodes cohérentes ;
   - binaire externe disponible ;
   - sorties attendues produites.
4. Enregistrer `concentration_seepage`, `mass_seepage`, `mass_accumulated` et
   les objets pathlines dans le registre de champs ou dans un registre résultats
   adapté aux objets non scalaires.

### P2

1. Relier `water_quality` à une extraction concentration simulée.
2. Ajouter une calibration concentration minimale :
   - mapping station vers cellule ;
   - extraction concentration ;
   - alignement temporel ;
   - métrique objective ;
   - support MT3DMS et GWT.
3. Ajouter des pages de validation transport :
   - Ogata-Banks HydroModPy ;
   - conservation de masse simple ;
   - injection recharge contrôlée ;
   - MODPATH pathlines sur cas synthétique.
4. Clarifier la stratégie long terme entre MT3DMS legacy et MF6 GWT moderne.

## Risques actuels

- Un run transport peut réussir techniquement tout en ne couvrant qu'une partie
  des sources/puits hydrochimiques réelles.
- Les sorties dérivées peuvent être interprétées comme des flux de masse alors
  que certaines branches utilisent des fallbacks non physiques.
- MODPATH peut donner une impression de couverture parce que le solveur est
  lancé, alors que les sorties catalogue ne sont pas assez validées.
- La calibration peut annoncer des objectifs transport dans les commentaires ou
  la config, mais le chemin effectif lève encore `NotImplementedError`.
- Les régressions actuelles vérifient surtout des signatures numériques, pas
  toujours des propriétés physiques.

## Commandes exécutées

Recherche de code et fichiers :

```powershell
rg --files hydromodpy tests docs examples | rg -i "transport|mt3d|modpath|gwt|concentration|water_quality|derived|post_run|extraction"
rg -n "transport|mt3dms|modpath|modflow6gwt|GWT|MT3DMS|MODPATH|concentration|pathlines|mass_seepage|concentration_seepage" hydromodpy tests docs examples
Get-ChildItem hydromodpy/solver/modflow_nwt/modpath
Get-ChildItem hydromodpy/solver/modflow_nwt/mt3dms
Get-ChildItem hydromodpy/solver/modflow6
```

Tests ciblés :

```powershell
python -m pytest tests/unit/simulation/test_transport_common.py tests/unit/solver/modflow_nwt/test_mt3dms_postprocessing.py tests/unit/solver/modflow_nwt/test_modpath_runtime_builder.py tests/unit/workflow/test_modpath_ingestion.py tests/unit/solver/test_solver_registry.py::test_transport_capabilities_are_explicit -q
```

Résultat :

```text
15 passed in 4.32s
```

## Recommandation finale

Le transport doit être traité comme un chantier de consolidation, pas comme une
fonctionnalité absente. Le bon prochain jalon n'est pas d'ajouter beaucoup de
paramètres, mais de verrouiller les bases :

1. ingestion MODPATH non vide ;
2. test analytique GWT via HydroModPy ;
3. conventions physiques des dérivés ;
4. validation des préconditions adapters ;
5. premier pont water_quality vers calibration concentration.

Après ces étapes, le transport pourra être considéré comme une capacité fiable
plutôt qu'une capacité seulement branchée.
