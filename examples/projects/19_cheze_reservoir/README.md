# 19 - Reservoir de la Cheze (EBR), MODFLOW 6 LAK

Portage du modele historique EBR du reservoir de la Cheze (Plelan-le-Grand,
Bretagne) vers l'architecture v1 MODFLOW 6. Le reservoir est un package **LAK
natif** pose sur la grille DISV : selection des cellules par le polygone, relation
hauteur-volume-surface par l'abaque, echange nappe-lac par la CONNECTIONDATA, et
surverse par un exutoire WEIR.

## Ce que fait l'exemple

- Delimitation du bassin de la Cheze depuis le DEM regional partage et l'exutoire
  aval du barrage.
- Recharge depuis l'**API SIM2 Meteo-France** (`source = "sim2"`), recuperee au
  run (connexion reseau ou cache SIM2 requis).
- Reservoir LAK : geometrie + abaque (donnees reelles 2025), niveau initial
  observe, exutoire WEIR a la crete du barrage (87.3 m), les flux geres
  (transferts Meu/Canut en entree, prelevement + restitution en sortie), et les
  forcages de surface SIM2 (pluie, evaporation eau-libre, ruissellement de bassin).
- Transitoire hebdomadaire sur 2019.

## Donnees

Tout ce qui est meteo vient de l'**API SIM2 Meteo-France** (recupere au run) :

| Variable | Source | Cible |
|---|---|---|
| recharge | SIM2 | nappe (recharge au toit de l'aquifere) |
| precipitation | SIM2 | pluie sur le plan d'eau (taux) |
| etp | SIM2 | evaporation eau-libre du lac (taux) |
| runoff | SIM2 | ruissellement de bassin -> apport volumetrique au lac (taux x aire bassin) |

Donnees lac locales (sous `examples/data/`) :

| Famille | Fichier | Contenu |
|---|---|---|
| `lake_geometry` | `lake_geometry/reservoir_cheze.gpkg` | polygone du reservoir (EPSG:2154, 1.58 km2) |
| `lake_abacus` | `lake_abacus/reservoir_cheze.csv` | abaque `stage,volume,sarea` (54.45 -> 87.58 m, jusqu'a 13.5 Mm3) |
| `lake_inflow` | `lake_inflow/` | transferts Meu + Canut vers le lac (m3/j) |
| `lake_withdrawal` | `lake_withdrawal/` | prelevement + restitution quittant le lac (m3/j) |

## Lancer

```bash
mamba activate hmp_refact
hmp run examples/projects/19_cheze_reservoir/project.toml
# ou, pour les figures lac :
python examples/projects/19_cheze_reservoir/run_cheze_reservoir.py
```

## Choix de portage et hypotheses

- **SFR abandonne (v1 = LAK seul).** La surverse et la restitution **sortent bien
  du lac** (exutoire LAK), mais comme la riviere n'est plus modelisee elles
  quittent le modele (`lakeout = 0`, flux enregistres) au lieu d'etre routees dans
  un cours d'eau simule.
- **bedleak** : l'ancien `1e-6 m/s` est une vitesse ; le champ v1 est une leakance
  [1/T] = K_lit / epaisseur_lit. Valeur retenue `1e-6 1/s` en supposant un lit de
  1 m. **A ajuster** avec l'epaisseur de lit reelle.
- **Exutoire WEIR** : crete a 87.3 m (ancien `stagemax`), largeur 35 m (crete beton).
- **bathymetrie** : non utilisee en v1 (l'abaque porte le stockage ; le branchement
  bathymetrie -> cote du lit est differe). Le raster 1 m n'est pas commite.

## Apport naturel (remplacement de SFR)

L'apport naturel dominant du reservoir est la **riviere Cheze**, modelisee avant
par SFR. En v1 (sans SFR) il est approxime par le **ruissellement de bassin SIM2
accumule** : taux de ruissellement (m/s) x aire de bassin -> apport volumetrique
au lac (terme `runoff`), exactement comme le faisait l'ancien script
(`runoff * area`). C'est une approximation (tout le ruissellement amont arrive au
lac, sans routage ni dephasage) ; un apport Cheze mesure pourrait le remplacer en
`lake_inflow` si disponible.
