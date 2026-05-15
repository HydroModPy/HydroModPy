# Rapport MF6/Boussinesq ? maillage comparable - sites 01 et 02

Date de g?n?ration: 2026-05-13.

Les m?triques comparent `h_Boussinesq - h_MF6`. Quand les deux maillages sont strictement identiques, la comparaison est cellule ? cellule. Quand Gmsh a produit le m?me type de maillage mais quelques cellules diff?rentes, la comparaison utilise l?appariement par centro?de le plus proche; la distance max d?appariement est report?e.

## R?sum? au dernier pas

| Cas | K | Maillage | Statut | M?thode | Cellules MF6/Bouss | Dist. max (m) | Biais (m) | MAE (m) | RMSE (m) | Max (m) | Affl. Bouss. |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Site 01 | faible | Triangulaire contraint | ok | cell_by_cell | 1250/1250 | 0.0 | 0.13 | 0.39 | 0.66 | 3.61 | 7.4 % |
| Site 01 | faible | Triangulaire quasi-uniforme | ok | cell_by_cell | 534/534 | 0.0 | -0.33 | 0.43 | 0.78 | 6.65 | 9.6 % |
| Site 01 | nominal | Triangulaire contraint | ok | cell_by_cell | 1250/1250 | 0.0 | 0.04 | 0.36 | 0.55 | 6.22 | 2.7 % |
| Site 01 | nominal | Triangulaire quasi-uniforme | ok | cell_by_cell | 534/534 | 0.0 | -0.34 | 0.48 | 0.73 | 5.00 | 5.4 % |
| Site 01 | forte | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Site 01 | forte | Triangulaire quasi-uniforme | Boussinesq diverge | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Site 02 | faible | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Site 02 | faible | Triangulaire quasi-uniforme | ok | nearest_centroid | 5720/5716 | 68.0 | -0.11 | 0.20 | 0.51 | 12.79 | 10.6 % |
| Site 02 | nominal | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Site 02 | nominal | Triangulaire quasi-uniforme | ok | nearest_centroid | 5722/5716 | 62.3 | 0.22 | 0.47 | 1.13 | 23.84 | 4.1 % |
| Site 02 | forte | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Site 02 | forte | Triangulaire quasi-uniforme | Boussinesq diverge | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Lecture

- Sur les comparaisons exploitables, la RMSE finale va de 0.51 m ? 1.13 m.
- Site 01 reste relativement stable pour K faible et nominal. Le cas K forte devient probl?matique pour Boussinesq: les sorties haute conductivit? sont incompl?tes ou divergentes.
- Site 02 est plus difficile: les maillages quasi-uniformes ne sont pas toujours strictement identiques entre solveurs et demandent un appariement spatial; Boussinesq diverge pour le cas K forte.
- Les grands ?carts observ?s dans les pages automatiques restent principalement li?s aux comparaisons entre supports diff?rents: maillage contraint vs quasi-uniforme ou grille structur?e MODFLOW.
- Cas non exploitables directement: site_01_k_high / Triangulaire contraint; site_01_k_high / Triangulaire quasi-uniforme; site_02_k_low / Triangulaire contraint; site_02_k_base / Triangulaire contraint; site_02_k_high / Triangulaire contraint; site_02_k_high / Triangulaire quasi-uniforme.

## D?tail temporel

| Cas | K | Maillage | RMSE premier | RMSE humide | RMSE sec | RMSE dernier | Max dernier |
|---|---:|---|---:|---:|---:|---:|---:|
| Site 01 | faible | Triangulaire contraint | 1.13 | 0.90 | 0.69 | 0.66 | 3.61 |
| Site 01 | faible | Triangulaire quasi-uniforme | 0.96 | 0.92 | 0.80 | 0.78 | 6.65 |
| Site 01 | nominal | Triangulaire contraint | 0.78 | 0.65 | 0.54 | 0.55 | 6.22 |
| Site 01 | nominal | Triangulaire quasi-uniforme | 0.59 | 0.64 | 0.72 | 0.73 | 5.00 |
| Site 01 | forte | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a |
| Site 01 | forte | Triangulaire quasi-uniforme | Boussinesq diverge | n/a | n/a | n/a | n/a |
| Site 02 | faible | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a |
| Site 02 | faible | Triangulaire quasi-uniforme | 0.45 | 0.43 | 0.49 | 0.51 | 12.79 |
| Site 02 | nominal | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a |
| Site 02 | nominal | Triangulaire quasi-uniforme | 0.97 | 1.01 | 1.11 | 1.13 | 23.84 |
| Site 02 | forte | Triangulaire contraint | Boussinesq diverge | n/a | n/a | n/a | n/a |
| Site 02 | forte | Triangulaire quasi-uniforme | Boussinesq diverge | n/a | n/a | n/a | n/a |

## Artefacts

- CSV: `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/web_synthesis/same_mesh_direct_metrics.csv`
- JSON: `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/web_synthesis/same_mesh_direct_metrics.json`
- Synth?se HTML testbed: `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/web_synthesis/index.html`

