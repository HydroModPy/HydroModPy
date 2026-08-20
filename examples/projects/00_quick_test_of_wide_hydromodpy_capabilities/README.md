# 00 - Quick test of wide HydroModPy capabilities

Portage sur l'architecture v1 de
`examples/old/00_quick_test_of_wide_hydromodpy_capabilities/example_00.py`,
résolu avec **MODFLOW 6** au lieu de MODFLOW-NWT.

Bassin de l'Aber (Bretagne, EPSG:2154) extrait d'un MNT régional 75 m par
accrochage d'exutoire. Une année transitoire mensuelle (2017) sur la boîte
rectangulaire tamponnée, une couche d'aquifère de 50 m, deux puits de
pompage, un drainage de versant, et un suivi de particules.

## Lancer

```bash
# via le TOML
hmp run examples/projects/00_quick_test_of_wide_hydromodpy_capabilities/project.toml

# via l'API Python (même config, mêmes résultats)
python examples/projects/00_quick_test_of_wide_hydromodpy_capabilities/run_manual.py

# re-rendre les figures sans re-simuler
hmp viz gallery examples/projects/00_quick_test_of_wide_hydromodpy_capabilities/project.toml
```

Durée : environ 5 s (980 mailles, 12 périodes de contrainte).

## Données

Toutes partagées sous `examples/data/`, résolues par nom de fichier nu :

| Fichier | Famille | Rôle |
|---|---|---|
| `dem/regional_dem_aber.tif` | dem | MNT régional 75 m (legacy `regional dem.tif`) |
| `hydrography/regional_stream_network.shp` | hydrography | réseau de référence |
| `recharge/recharge_custom_00_*.csv` | recharge | recharge mensuelle, mm/j |
| `wells/wells_custom_00_*.csv` | (forçage puits) | débits mensuels, m3/j |

## Correspondance avec le script legacy

| Legacy | v1 |
|---|---|
| `from_xyv = [x, y, 100, 10]` | `[geographic.catchment]` `from_outlet_coord`, `snap_dist`, `buff_area` |
| `update_box_model(True)` | `geographic.domain_extent = "box"` |
| `update_sink_fill(False)` | `geographic.dem_correc_type = "breach"` |
| `update_dis_perlen(True)` | `simulation.time.substeps_per_period = 30` |
| `update_thick(50)` / `update_nlay(1)` | `[domain.depth_model]` / `[modflow6.sgrid.vertical]` |
| `update_hk/sy/ss` | `[flow.param.K/Sy/Ss.field]` |
| `update_well_pumping(...)` | `[flow.sinks_sources.wells.W1/W2]` |
| `update_first_clim('mean')` | `flow.first_period_steady = true` |
| MODPATH backward depuis les zones de suintement | MODFLOW 6 PRT forward (voir ci-dessous) |
| tracés matplotlib du script | `[display].figures` |

### Suivi de particules : pourquoi forward

Le script legacy lançait MODPATH en **backward** depuis les zones de
suintement pour montrer quelle recharge les alimente. MODFLOW 6 PRT ne
suit que vers l'aval : la même physique s'écrit dans l'autre sens, les
particules sont relâchées sur le domaine et se terminent là où la nappe
affleure. La figure se lit à l'identique.

## Figures

Toutes viennent du registre HydroModPy, aucune n'est codée dans un `.py`.

| Figure | Ce qu'elle montre | Équivalent legacy |
|---|---|---|
| `watershed_id_card` | carte d'identité du bassin | `watershed_local` |
| `mesh_map` | grille du solveur colorée par la topographie | `visual2D(['grid'])` |
| `recharge_map` | recharge par maille | - |
| `piezometric_map` | altitude de la nappe | `visual2D(['watertable'])` |
| `watertable_depth_map` | profondeur de nappe + suintement + trajectoires + puits | la carte composite du script |
| `seepage_map` | zones de suintement | - |
| `particle_tracks` | trajectoires colorées par temps de transit | `pathlines` |
| `cross_section` | coupe topographie / nappe / base d'aquifère | la coupe fixe du script |
| `flux_timeseries` | bilan hydrique par pas de temps, mm/période | le graphe recharge / drain / puits |
| `water_budget` | bilan cumulé par composante | - |

La carte composite est déclarative, pas codée :

```toml
[display.overrides.watertable_depth_map]
overlays = ["watershed", "seepage", "particles", "wells", "outlet"]
```

`on_error = "raise"` : une figure qui s'applique mais échoue fait échouer le
run. Une figure qui ne s'applique pas à ce run est passée avec un motif
explicite dans le log.

## Basculer vers MODFLOW-NWT

Seuls le nom du solveur et le préfixe de section changent. Le suivi de
particules passe alors de PRT à MODPATH, qui accepte le backward :

```toml
[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[[simulation.process]]
id = "particles"
type = "transport"
solvers = ["modpath"]

[transport.modpath.parameters]
zone_partic = "seepage_clip"
track_dir = "backward"

[modflownwt.sgrid.planar]
mode = "keep_native"

[modflownwt.sgrid.vertical]
nlay = 1
```
