# 19 - Reservoir de la Cheze (EBR), MODFLOW 6 LAK + SFR

Portage du modele historique EBR du reservoir de la Cheze (Plelan-le-Grand,
Bretagne) vers l'architecture MODFLOW 6. Le reservoir est un package **LAK
natif** (selection des cellules par le polygone, relation hauteur-volume-surface
par l'abaque, echange nappe-lac par la CONNECTIONDATA, surverse par un exutoire
WEIR), **alimente par le debit de son bassin via un reseau SFR** : les biefs
captent le flux de nappe par leur lit, le ruissellement SIM2 est route le long
du reseau, le drainage de versant converge vers le bief le plus proche
(`route_drainage`), et les biefs terminaux (tronques a la rive) livrent le debit
accumule au lac par des enregistrements MVR.

## Ce que fait l'exemple

- Delimitation du bassin de la Cheze depuis le DEM regional partage et l'exutoire
  aval du barrage ; produits reseau hydrographique (liens + ordre de Strahler)
  pour la delineation SFR.
- Recharge depuis l'**API SIM2 Meteo-France** (`source = "sim2"`), recuperee au
  run (connexion reseau ou cache SIM2 requis).
- Reservoir LAK : geometrie + abaque (donnees reelles 2025), niveau initial
  observe maintenu pendant le warm-up stationnaire (`steady_stage_hold`),
  exutoire WEIR a la crete du barrage (87.3 m), flux geres (transferts
  Meu/Canut en entree, prelevement + restitution en sortie), pluie et
  evaporation eau-libre SIM2 sur le plan d'eau.
- Riviere Cheze SFR : reseau delinee au seuil 1 km2, tronque a la rive du
  reservoir, parametres de lit du modele historique (hcond 0.08 m/j, lit
  0.1 m, Manning 0.03), ruissellement SIM2 route + convergence du drainage de
  versant, couplage MVR vers le lac (`outflow_to_lake = 1`).
- Transitoire hebdomadaire sur 2019 (demo) et journalier 2007-2025 (chronique).

## Donnees

Tout ce qui est meteo vient de l'**API SIM2 Meteo-France** (recupere au run) :

| Variable | Source | Cible |
|---|---|---|
| recharge | SIM2 | nappe (recharge au toit de l'aquifere) |
| precipitation | SIM2 | pluie sur le plan d'eau (taux) |
| etp | SIM2 | evaporation eau-libre du lac (taux) |
| runoff | SIM2 | ruissellement de bassin -> route par le reseau SFR (taux x aire bassin, reparti par longueur de bief) |

Donnees lac locales (sous `examples/data/`) :

| Famille | Fichier | Contenu |
|---|---|---|
| `lake_geometry` | `lake_geometry/reservoir_cheze.gpkg` | polygone du reservoir (EPSG:2154, 1.58 km2) |
| `lake_abacus` | `lake_abacus/reservoir_cheze.csv` | abaque `stage,volume,sarea` (54.45 -> 87.58 m, jusqu'a 13.5 Mm3) |
| `lake_inflow` | `lake_inflow/` | transferts Meu + Canut vers le lac (m3/j, 2007-2026) |
| `lake_withdrawal` | `lake_withdrawal/` | prelevement + restitution quittant le lac (m3/j, 2007-2026) |
| `lake_levels` | `lake_levels/` | niveau observe du reservoir (m NGF, 2007-2026) pour la comparaison |

Les chroniques `lake_inflow`, `lake_withdrawal` et `lake_levels` derivent toutes du
meme fichier source `data_cheze_corrige.csv` (2007-2026) : `inflow = meu + canut`,
`withdrawal = restitution + prelevement`, `niveau = cheze_cote_mNGF`.

## Lancer

```bash
mamba activate hmp_refact
# Demo court : 2019 hebdomadaire (figures lac + figures SFR)
hmp run examples/projects/19_cheze_reservoir/project.toml
python examples/projects/19_cheze_reservoir/run_cheze_reservoir.py

# Chronique complete : journalier 2007-2025 + comparaison simule/observe
python examples/projects/19_cheze_reservoir/compare_chronicle.py
```

## Comment l'eau arrive au reservoir

Trois chemins, tous dans le bilan MF6 (fermes, traces dans le store) :

1. **Baseflow des biefs** : les biefs SFR posent sur des cellules actives et
   captent le flux de nappe par la conductance de leur lit ; les entrees DRN
   coincidant avec un bief sont supprimees (de-confliction).
2. **Convergence du drainage de versant** (`route_drainage = true`) : chaque
   cellule DRN restante livre son debit au bief le plus proche par MVR. Sans
   cette convergence, l'essentiel de la decharge du bassin sortait du modele
   par DRN et le reservoir se vidait (l'echec du portage v1).
3. **Ruissellement route** : la famille `runoff` SIM2 est automatiquement liee
   au forcage `runoff` du reseau SFR (reparti par longueur de bief) et n'est
   PLUS versee directement au lac (pas de double comptage).

Les biefs terminaux (le reseau est tronque a la rive du polygone) remettent le
debit accumule au lac : serie `from_mvr` du lac dans le store, et `to_mvr` par
bief cote SFR.

## SFR seul (sans lac)

Le reseau SFR est independant du lac : pour une etude de debits / intermittence,
garder `[geographic.river_network]` + `[flow.sinks_sources.sfr.<id>]` (sans
`outflow_to_lake`) et `active_bc = ["sfr", "drainage"]`. Le debit simule par
bief est la serie `downstream_flow` (`station_id = sfr:<reseau>:<bief>`), et
`route_drainage = true` donne des chroniques de debit realistes (toute la
decharge du bassin converge au reseau). Voir le guide utilisateur
`modflow6-sfr` dans la documentation.

## Chronique complete et comparaison simule/observe

`project_chronicle.toml` rejoue le reservoir en **pas journalier sur 2007-2025**
(~6940 stress periods). Les forcages varient chaque jour : ils sont deportes en
fichiers MF6 TS6 (`lak_forcing_mode = "ts6"`). Premiere execution : gros fetch
SIM2 (19 ans x 4 variables) puis solve de plusieurs minutes.

La comparaison simule/observe est faite par script, `compare_chronicle.py`, a
partir des briques existantes : `query_timeseries` pour la serie stage simulee,
le CSV observe (`data/lake_levels`), l'abaque pour convertir le niveau observe
en volume, et `core.metrics.goodness_of_fit`. Sorties dans `figures/` : overlay
niveau + volume (`cheze_chronicle_obs_vs_sim.png`) et la table de scores
NSE / RMSE / MAE / bias / R2 (`cheze_chronicle_metrics.csv`). Le warm-up
stationnaire (periode 0) est exclu du calcul.

### Etat des performances (parametres legacy, AUCUNE recalibration)

| Fenetre | NSE | RMSE | biais |
|---|---|---|---|
| 2019 hebdomadaire (demo) | 0.30 | 1.17 m | -0.01 m |
| 2007-2025 journalier | -1.72 | 2.58 m | -0.73 m |

L'annee 2019 est equilibree (biais nul) : les trois chemins d'alimentation
ferment le bilan. Sur 19 ans la structure d'erreur est un sous-remplissage
persistant de 2008-2011 et 2020+ (deficit de volume du forcage et/ou
prelevements, pas un probleme de routage : un test de sensibilite Sy 0.001 ->
0.01 ne change presque rien) et l'ecretage du simule a la crete 87.3 m alors
que l'observe monte a 87.98 m. Les leviers de calibration sont en config :
`bedleak`, `streambed_k`, K/Sy, le seuil de drainage, et la correction du
forcage SIM2. La calibration multi-annees (Optuna) est l'etape suivante,
hors du perimetre de cet exemple.

## Choix de portage et hypotheses

- **bedleak** : l'ancien `1e-6 m/s` est une vitesse ; le champ v1 est une leakance
  [1/T] = K_lit / epaisseur_lit. Valeur retenue `1e-6 1/s` en supposant un lit de
  1 m. C'est un levier de calibration (fuite sous barrage).
- **Exutoire WEIR** : crete a 87.3 m (ancien `stagemax`), largeur 35 m (crete beton).
- **Warm-up** : la periode 1 est stationnaire ; `steady_stage_hold` maintient le
  lac au niveau observe initial (status CONSTANT) pendant que la nappe
  s'equilibre, puis le lac redevient libre (ACTIVE). Sans cela l'equilibre
  naturel stationnaire (lac plein au deversoir) ecraserait le niveau initial
  observe d'un reservoir gere.
- **Seuil de drainage** : 1 km2 (reseau de la Cheze et affluents principaux en
  amont du reservoir). L'ancien masque 0.7 x acc_max ne gardait que le bief sous
  le barrage, inutile une fois le reseau tronque a la rive.
- **Lit des biefs** : parametres du modele historique (`hcond = 0.08 m/j`,
  `thickm = 0.1 m`, `roughch = 0.03`) ; levier de calibration de la capture de
  baseflow.
- **Parametres aquifere** : valeurs legacy non recalibrees (K = 1e-4 m/s,
  Sy = 0.001, Ss = 1e-5). La dynamique de recession (vidange automnale,
  remontee hivernale) est le premier candidat de calibration.
- **bathymetrie** : non utilisee (l'abaque porte le stockage ; le branchement
  bathymetrie -> cote du lit est differe). Le raster 1 m n'est pas commite.
