# Plan de developpement MF6-PRT pour le transport HydroModPy

Date : 2026-05-14

Statut : plan base sur l'inspection du code local, les exemples transport
synthetiques/Nancon recents, la documentation officielle MODFLOW 6 PRT, et la
disponibilite locale de FloPy `3.10.0`. Une premiere implementation a ete
ajoutee le 2026-05-14 : configuration `transport.modflow6prt`, registre solveur,
runtime MF6-PRT, adaptateur, extracteur CSV PRT, lecture de figures pathlines et
tests unitaires.

## Resume executif

HydroModPy dispose maintenant d'un premier backend `transport/modflow6prt`.

Ce qui existe deja :

- `transport/modpath` pour MODFLOW-NWT, avec backend MODPATH 6 ;
- `transport/mt3dms` pour MODFLOW-NWT ;
- `transport/modflow6gwt` pour MODFLOW 6 GWT ;
- un affichage `particle_tracks`, mais il doit etre verifie/adapte au format
  Zarr effectivement produit ;
- un registre solveur pret a accueillir un nouveau solveur transport.

Ce qui a ete ajoute dans la premiere passe :

- une configuration `transport.modflow6prt.parameters` ;
- un runtime `hydromodpy/solver/modflow6/prt.py` ;
- un adaptateur `transport/modflow6prt` dependant de `flow/modflow6` ;
- un extracteur de fichiers PRT vers `SimulationCatalog/pathlines` ;
- des tests unitaires et un exemple Nancon permanent MF6-GWF + MF6-PRT.

Ce qui reste a valider hors tests unitaires :

- execution d'un vrai modele avec un executable MODFLOW 6 contenant PRT ;
- inspection des CSV PRT reels sur Nancon ;
- affichage automatique des pathlines MF6-PRT dans un rapport web de run ;
- selection hydrologique plus fine des particules au-dela du premier
  `upstream_nonriver`.

Le choix recommande est de ne pas commencer par MODPATH 7 pour le Nancon DISV
triangulaire. MODFLOW 6 PRT est le chemin naturel, parce qu'il travaille
directement avec le modele GWF MODFLOW 6 et supporte les grilles DISV.

## Existant dans le code

Les sections suivantes gardent l'analyse de l'etat initial pour tracer les
decisions. Les actions marquees comme attendues dans cette analyse ont ete
realisees pour le socle `modflow6prt`; les validations longues restent a faire
sur des runs MODFLOW 6 reels.

### Registre solveur

Fichier :

- `hydromodpy/solver/base/registry.py`

Etat actuel :

- `("transport", "modpath")` pointe vers
  `hydromodpy.solver.modflow_nwt.adapters.transport_modpath:ModpathTransportAdapter`;
- `("transport", "modflow6gwt")` pointe vers
  `hydromodpy.solver.modflow6.adapters.transport:Modflow6GwtTransportAdapter`;
- les capacites declarent `transport:particles` pour `modpath`, mais pas pour
  MODFLOW 6 ;
- les extracteurs connus incluent `modpath` et `modflow6gwt`, mais pas
  `modflow6prt`.

Action attendue :

- ajouter `("transport", "modflow6prt")` ;
- lui declarer la capacite `{"transport", "transport:particles"}` ;
- ajouter un extracteur `modflow6prt`.

### Configuration transport

Fichier :

- `hydromodpy/physics/transport/transport_config.py`

Etat actuel :

- `TransportConfig` contient `modpath`, `mt3dms` et `modflow6gwt` ;
- les parametres MODPATH existants couvrent des concepts utiles :
  `zone_partic`, `track_dir`, `cell_div`, `sel_random`, `sel_slice` ;
- aucune section `modflow6prt` n'existe.

Action attendue :

- ajouter un `Modflow6PrtParametersConfig` distinct ;
- garder une compatibilite conceptuelle avec `modpath`, mais sans forcer le
  meme schema exact.

Parametres minimum recommandes :

| champ | role |
|---|---|
| `release_zone` | zone/cellules de depart : `domain`, `river`, `upstream`, `upstream_nonriver`, raster ou liste de cellules |
| `upstream_top_quantile` | quantile de topographie utilise par les zones amont |
| `track_dir` | `forward` au depart ; backward plus tard par inversion de flux |
| `cell_div` | subdivision horizontale dans chaque cellule source |
| `local_z` | position verticale relative ou absolue |
| `porosity` | porosite PRT, par defaut issue de `Sy` ou d'un champ dedie |
| `release_times_days` | liste explicite des temps de relargage |
| `track_times_days` | temps de sortie des trajectoires |
| `stop_time_days` | temps d'arret |
| `extend_tracking` | extension optionnelle au-dela de la simulation |
| `dry_tracking_method` | `drop`, `stop`, `stay` |
| `exit_solve_tolerance` | tolerance importante pour DISV triangulaire |
| `write_track_csv` | sortie CSV lisible pour extraction/debug |

### Runtime MODFLOW 6 GWT

Fichier :

- `hydromodpy/solver/modflow6/transport.py`

Etat actuel :

- `Modflow6Transport` ajoute un modele GWT a la simulation GWF existante ;
- il reutilise `model_modflow.sim`, `model_modflow.gwf` et
  `model_modflow.solver_mesh.to_disv_kwargs()` ;
- il cree `ModflowGwt`, `ModflowGwtdisv`, `ModflowGwtadv`,
  `ModflowGwtdsp`, `ModflowGwtmst`, `ModflowGwtssm`, puis l'echange
  `GWF6-GWT6`.

Action attendue :

- construire `Modflow6Prt` sur le meme modele d'integration ;
- reutiliser `model_modflow.solver_mesh.to_disv_kwargs()` pour `ModflowPrtdisv`;
- creer `ModflowPrtmip`, `ModflowPrtprp`, `ModflowPrtoc`, puis l'echange
  `ModflowGwfprt`.

### Runtime MODPATH existant

Fichiers :

- `hydromodpy/solver/modflow_nwt/modpath/modpath.py`;
- `hydromodpy/solver/modflow_nwt/adapters/transport_modpath.py`;
- `hydromodpy/solver/modflow_nwt/extractors/modpath.py`.

Etat actuel :

- backend limite explicitement MODPATH a MODFLOW-NWT ;
- il exige `model_modflow.mf` ;
- il utilise `flopy.modpath.Modpath6` ;
- l'adaptateur depend de `("flow", "modflownwt")`.

Action attendue :

- ne pas essayer de reutiliser directement cette classe pour MF6-PRT ;
- reutiliser seulement les idees de resolution de zone particulaire et de
  signature d'extraction.

### Affichage particules

Fichier :

- `hydromodpy/display/figures/particle_tracks.py`

Etat actuel :

- la figure `particle_tracks` existe ;
- elle lit un groupe `pathlines` dans le store ;
- le format attendu par la figure semble etre une collection de tableaux
  `p_<idx>` avec colonnes `x, y, z`, alors que l'extracteur MODPATH ecrit plutot
  des tableaux separes `x`, `y`, `z`, `time`.

Action attendue :

- normaliser le schema `pathlines` avant d'ajouter MF6-PRT ;
- faire accepter a la figure le format vectorise `x/y/z/time`, ou migrer
  l'extracteur vers le format `p_<idx>`.

## Etat de l'environnement local

Commande inspectee :

```powershell
python - <<'PY'
import flopy
print(flopy.__version__)
for name in ["ModflowPrt", "ModflowPrtdisv", "ModflowPrtprp",
             "ModflowPrtmip", "ModflowPrtoc", "ModflowGwfprt"]:
    print(name, hasattr(flopy.mf6, name))
PY
```

Resultat :

- FloPy `3.10.0` ;
- classes PRT disponibles :
  - `ModflowPrt` ;
  - `ModflowPrtdisv` ;
  - `ModflowPrtprp` ;
  - `ModflowPrtmip` ;
  - `ModflowPrtoc` ;
  - `ModflowGwfprt`.

Cela permet de developper MF6-PRT sans attendre une mise a jour FloPy locale.

## Plan de developpement

### Phase 0 : verrouiller le schema `pathlines`

Objectif : eviter que PRT et MODPATH ecrivent deux formats incompatibles.

Travail :

1. definir un schema canonique dans `SimulationCatalog` :
   - `pathlines/x` : `(n_particles, max_steps)` ;
   - `pathlines/y` : `(n_particles, max_steps)` ;
   - `pathlines/z` : `(n_particles, max_steps)` ;
   - `pathlines/time` : `(n_particles, max_steps)` ;
   - optionnel : `pathlines/status`, `pathlines/reason`, `pathlines/release_time`;
2. adapter `display/figures/particle_tracks.py` a ce schema ;
3. ajouter un test unitaire de lecture de pathlines vectorisees.

Critere de sortie :

- une figure particules fonctionne avec le schema ecrit par l'extracteur
  MODPATH actuel.

### Phase 1 : configuration MF6-PRT

Objectif : rendre le backend declarable dans les TOML sans executable encore.

Travail :

1. ajouter `Modflow6PrtParametersConfig` ;
2. ajouter `TransportModflow6PrtConfig` ;
3. ajouter `modflow6prt` dans `TransportConfig` et `Transport` ;
4. ajouter tests de validation config ;
5. mettre a jour la doc de reference si necessaire.

Critere de sortie :

```toml
[simulation]
solvers = ["modflow6", "modflow6prt"]

[transport.modflow6prt.parameters]
release_zone = "upstream_nonriver"
upstream_top_quantile = 0.88
max_particles = 12
track_dir = "forward"
exit_solve_tolerance = 1e-10
```

Mise a jour 2026-05-15 : `upstream_nonriver` a ete ajoute pour liberer quelques
particules dans les zones amont sans les poser sur le support des rivieres. Le
TOML Nancon permanent utilise maintenant `max_particles = 12` pour les premiers
essais visuels.

### Phase 2 : runtime `Modflow6Prt`

Objectif : construire un modele PRT dans la simulation MF6 existante.

Nouveau fichier :

- `hydromodpy/solver/modflow6/prt.py`

Classe :

- `Modflow6Prt`

Structure recommandee :

```python
class Modflow6Prt:
    def __init__(self, domain, transport, model_modflow, model_folder, model_name, suffix_name="_prt", **kwargs):
        ...

    def pre_processing(self):
        sim = self.model_modflow.sim
        gwf = self.model_modflow.gwf
        self.prt = flopy.mf6.ModflowPrt(sim, modelname=...)
        self.prtdisv = flopy.mf6.ModflowPrtdisv(self.prt, **disv_kwargs)
        self.mip = flopy.mf6.ModflowPrtmip(self.prt, porosity=...)
        self.prp = flopy.mf6.ModflowPrtprp(self.prt, packagedata=..., ...)
        self.oc = flopy.mf6.ModflowPrtoc(self.prt, track_filerecord=..., trackcsv_filerecord=...)
        self.gwfprt = flopy.mf6.ModflowGwfprt(sim, exgmnamea=gwf.name, exgmnameb=self.prt.name)

    def processing(self, write_model=True, run_model=False, verbose=True):
        ...
```

Points techniques :

- reutiliser `solver_mesh.to_disv_kwargs()` ;
- passer `xorigin/yorigin` si le mesh les porte deja, sinon rester en coordonnees
  locales comme GWT ;
- commencer avec un seul layer ;
- utiliser `TRACKCSV` pour faciliter l'extraction et le debug ;
- fixer `exit_solve_tolerance = 1e-10` par defaut pour DISV triangulaire, car la
  doc PRT signale que cette tolerance peut etre importante sur grilles DISV.

Critere de sortie :

- un modele PRT peut etre ecrit sur un mini DISV synthetique sans etre execute.

### Phase 3 : adaptateur registre

Objectif : integrer PRT dans la sequence de simulation.

Nouveau fichier :

- `hydromodpy/solver/modflow6/adapters/prt.py`

Classe :

- `Modflow6PrtTransportAdapter`

Registre :

- ajouter `("transport", "modflow6prt")` ;
- `requires = (("flow", "modflow6"),)` ;
- capacite `transport:particles` ;
- extracteur `modflow6prt`.

Critere de sortie :

- `tests/unit/solver/test_solver_registry.py` attend :

```python
assert registry.capabilities("transport", "modflow6prt") == frozenset(
    {"transport", "transport:particles"}
)
```

### Phase 4 : extraction PRT

Objectif : injecter les trajectoires PRT dans le store.

Nouveau fichier :

- `hydromodpy/solver/modflow6/extractors/prt.py`

Approche :

- lire en priorite `*.trk.csv` ou le nom explicite `trackcsv_filerecord` ;
- convertir en tableaux `x/y/z/time` paddes par particule ;
- ecrire dans le groupe `pathlines`.

Donnees minimales attendues :

- identifiant particule ;
- temps ;
- x, y, z ;
- event/status si disponible.

Critere de sortie :

- test unitaire avec CSV PRT minimal ;
- test de figure `particle_tracks`.

### Phase 5 : exemple Nancon permanent

Objectif : remplacer progressivement le transport visuel synthetique par un vrai
triptyque MF6.

Exemple cible :

- `examples/projects/14_transport_nancon_gwt_visual_guard/`

Nouveau mode :

```powershell
python examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_visual_guard.py --mode mf6-prt
```

Scenario minimal :

1. MF6-GWF permanent sur le bundle Nancon existant ;
2. K homogene `5e-5 m/s` ;
3. recharge simple ou gradient hydraulique controle ;
4. PRT depuis une zone amont ou depuis une ligne de depart ;
5. HTML avec :
   - charge ;
   - flux/budget ;
   - lignes PRT ;
   - signatures pathlines.

Ensuite seulement :

- ajouter GWT pulse/source constante ;
- comparer GWT et PRT dans le meme rapport.

### Phase 6 : tests de non-regression

Niveau rapide :

- mini DISV 20-100 cellules ;
- ecriture PRT seulement, sans executable ;
- extraction CSV simulee ;
- figure pathlines depuis store en memoire.

Niveau integration optionnel :

- necessite executable MF6 recent avec PRT ;
- run permanent synthetique ;
- golden signatures :
  - nombre de particules ;
  - temps final median ;
  - distance moyenne parcourue ;
  - fraction terminee ;
  - enveloppe de coordonnees.

Niveau Nancon :

- non CI par defaut ;
- generation HTML et signatures ;
- temps acceptable : jusqu'a environ 1 minute.

## Risques et points d'attention

1. **Version de MF6 executable** : FloPy supporte PRT localement, mais
   l'executable `mf6` doit aussi etre assez recent. PRT n'a pas d'executable
   separe ; il est inclus dans MODFLOW 6. La commande HydroModPy
   `hmp install-binaries --mf6-prt` installe donc seulement `mf6`.
2. **DISV triangulaire** : commencer avec `exit_solve_tolerance=1e-10` et des
   tests de non-termination.
3. **Schema pathlines actuel** : l'affichage existant doit etre harmonise avec
   l'extracteur.
4. **Backward tracking** : ne pas le faire en premier. PRT gere surtout le
   forward ; le backward passe par inversion de flux.
5. **Advanced packages** : PRT ne suit pas toutes les fonctionnalites avancees
   comme des particules a travers des features de lacs/streams. Pour Nancon,
   garder d'abord un flow simple.
6. **Comparaison avec GWT** : PRT trace l'advection, GWT trace
   advection-dispersion-reaction. Les ecarts ne sont pas des bugs par defaut.

## Recommandation concrete

Premier patch de production :

1. ajouter la configuration `modflow6prt` ;
2. ajouter le registre et l'adaptateur squelette ;
3. ajouter l'extracteur CSV PRT et harmoniser `particle_tracks` ;
4. ajouter un test unitaire sans executable ;
5. ajouter un mode Nancon `--mode mf6-prt-write` qui ecrit les fichiers MF6 sans
   les executer.

Deuxieme patch :

1. executer un mini cas PRT si l'executable MF6 local supporte PRT ;
2. produire les premieres pathlines reelles ;
3. ajouter la figure PRT dans le HTML Nancon.

Troisieme patch :

1. coupler PRT et GWT dans le meme exemple permanent ;
2. definir les signatures de non-regression ;
3. passer ensuite aux heterogeneites K et aux cas naturels plus complets.

## Mise a jour 2026-05-15 : premier run Nancon MF6-PRT reel

Le premier run reel `flow/modflow6` puis `transport/modflow6prt` a ete execute
avec le binaire Linux MODFLOW 6.7.0 installe dans WSL:

```bash
export PATH="$HOME/.local/bin:$PATH"
export HYDROMODPY_BIN="$HOME/.local/bin"
cd /mnt/c/codes/HydroModPy
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m hydromodpy.cli.main run \
  examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_steady_mf6_prt_pathlines.toml
```

Resultat:

- le run permanent GWF DISV termine normalement avec MF6 `6.7.0`;
- le run PRT termine normalement avec le meme executable;
- `12` particules sont liberees dans des cellules amont hors support riviere;
- l'extracteur a ecrit des pathlines vectorisees de forme `(12, 12)` dans le
  store Zarr du run;
- le store final est archive dans
  `examples/projects/14_transport_nancon_gwt_visual_guard/outputs/mf6_prt_pathlines/workspace/simulations/workspace__run_0001__03f15ca9.zarr.zip`.

Deux corrections ont ete necessaires avant d'obtenir ce run:

1. La migration DuckDB des colonnes `date_start`/`date_end` doit dropper et
   recreer les index `entries` connus quand DuckDB refuse `ALTER COLUMN` a cause
   de dependances existantes.
2. PRT doit avoir son propre solveur `EMS` enregistre apres l'`IMS` GWF, et le
   fichier de trajectoire `.trk` doit etre declare seulement dans `PRT-OC`, pas
   a la fois dans `PRT-PRP` et `PRT-OC`.

La configuration Nancon PRT pointe maintenant explicitement vers le bundle de
maillage existant du projet 09:

```toml
[mesh_input]
bundle_dir = "../09_comparison_workflow/outputs/nancon_transient_seasonal_hydrography/workspace_mf6/mesh/mesh_catchment_bundle"
```

## Mise a jour 2026-05-15 : page HTML de demonstration PRT

Une page HTML autonome a ete ajoutee pour visualiser le premier run Nancon
MF6-PRT reel en reutilisant les blocs de visualisation deja presents dans
`run_nancon_visual_guard.py`:

- `load_nancon_mesh`;
- `DEFAULT_MESH_BUNDLE`;
- `linked_figure` pour rendre les figures cliquables en pleine resolution;
- les collections Matplotlib de maillage/rivieres.

Script:

```powershell
python examples/projects/14_transport_nancon_gwt_visual_guard/build_mf6_prt_pathline_html.py
```

Sortie:

- `examples/projects/14_transport_nancon_gwt_visual_guard/outputs/mf6_prt_pathlines/web/index.html`;
- `figures/pathlines_topography.png`;
- `figures/global_displacement_vectors.png`;
- `figures/velocity_magnitude.png`;
- `figures/release_points.png`;
- `figures/pathline_displacement_zoom.png`;
- `figures/travel_time_summary.png`;
- `metrics.json`;
- `metrics.csv`.

La page affiche les particules liberees en amont hors cellules riviere, les
trajectoires sur topographie, les vecteurs de deplacement net sur la carte
globale relief/rivieres, le champ de vitesse de pore derive de `DATA-SPDIS`, un
zoom local des deplacements et une synthese par particule. Les figures sont des
liens directs vers les PNG haute resolution.

Le run de demonstration est volontairement petit (`12` particules). Les
trajectoires extraites sont valides et couvrent maintenant des distances
coherentes avec le champ de vitesse: distance mediane `236.9 m`, maximum
`447.5 m`, temps final `365 jours`. Avec la porosite PRT `0.05`, le champ
`DATA-SPDIS` extrait donne une vitesse de pore mediane d'environ `226.6 m/an`,
un p95 d'environ `364.4 m/an` et un maximum d'environ `582.3 m/an`.

L'ancien diagnostic millimetrique etait du a deux erreurs de plomberie:

1. les parametres `release_times_days`, `track_times_days`,
   `stop_time_days` et `stop_travel_time_days` etaient ecrits directement dans
   les fichiers PRT alors que le `TDIS` GWF est en secondes. Un `365` attendu en
   jours etait donc interprete par PRT comme `365` secondes;
2. l'extraction `DATA-SPDIS` lisait le champ scalaire `q`, nul pour ce record,
   au lieu de reconstruire la norme du vecteur `qx/qy/qz`.

Le store corrige est:

- `examples/projects/14_transport_nancon_gwt_visual_guard/outputs/mf6_prt_pathlines/workspace/simulations/workspace__run_0001__57177b22.zarr.zip`.

## References externes

- USGS MODFLOW 6 : le modele PRT calcule les trajectoires advectives et supporte
  les grilles DIS/DISV :
  https://www.usgs.gov/software/modflow-6-usgs-modular-hydrologic-model
- Documentation MODFLOW 6 PRT-DISV :
  https://modflow6.readthedocs.io/en/6.6.1/_mf6io/prt-disv.html
- Guide migration PRT MODFLOW 6.6.0, notamment `EXIT_SOLVE_TOLERANCE` sur DISV :
  https://modflow6.readthedocs.io/en/latest/_migration/mf6_6_0_prt_migration_guide.html
- USGS MODPATH : MODPATH 7 fonctionne avec MODFLOW 6, mais le support
  non-structure est limite par rapport a PRT pour notre usage DISV triangulaire :
  https://www.usgs.gov/index.php/software/modpath-a-particle-tracking-model-modflow
