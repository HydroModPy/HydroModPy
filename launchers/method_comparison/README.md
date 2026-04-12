# Method Comparison Launcher

`method_comparison` orchestre plusieurs variantes maillage/solveur pour un
meme probleme, puis extrait des variables d'interet depuis les artefacts
`_postprocess` existants.

## Usage

```powershell
python -m launchers method-comparison run path/to/config_method_comparison.toml
hmp compare path/to/config_method_comparison.toml
```

Un template est disponible :

```powershell
python -m launchers method-comparison template --output config_method_comparison.toml
```

## Ancres

Les observables `point` et `outlet` peuvent referencer des coordonnees nommees
avec :

- `method_comparison.anchors_file = "method_comparison_points.toml"`
- `anchor_id = "example12.outlet"`

Le fichier d'ancres doit exposer un arbre `[method_comparison_anchors...]`
contenant des noeuds `x` et `y`.

## Sorties

Le launcher ecrit dans `method_comparison/<comparison_id>/` par defaut :

- `comparison_manifest.json` : statut des variantes, chemins, metadonnees de runs.
- `observables.csv` : valeurs extraites au format long.
- `comparison_metrics.csv` : resume des ecarts a la variante de reference.
- `comparison_differences.csv` : ecarts detailles par observable et temps.
- `comparison_metrics.json` : representation JSON du resume et des ecarts.
- `comparison_report.md` : synthese lisible des variantes, metriques et lignes non apparies.
- `comparison_figures/` : figures PNG de comparaison quand les observables s'y pretent.

Les figures generees en best-effort sont :

- cartes cote a cote pour les observables `support = "map"` ;
- cartes de difference versus la variante de reference quand les geometries sont compatibles ;
- series temporelles superposees pour les observables non-cartes avec plusieurs pas de temps.

## Outlet

Pour `support = "outlet"`, fournir un `cell_index` ou une coordonnee `x/y`.
Sans localisation explicite, le launcher refuse l'extraction. Un mode
exploratoire reste possible avec `allow_domain_proxy = true`, qui applique le
reducteur a tout le domaine et marque la ligne avec
`selection = "domain_reducer_proxy"`.

## Flux

Pour comparer un flux d'exutoire, utiliser de preference `variable = "outlet_flux"`.
Le launcher applique alors le contrat suivant, dans cet ordre :

- `outlet_discharge_east_side_m3_s` quand la sortie solveur existe deja ;
- `drainage_flux_history_m3_s` ou `drainage_flux_m3_s` cote Boussinesq ;
- `accumulation_flux` cote MODFLOW, converti en `m3/s` a partir de la cellule
  d'exutoire et de `area_m2` dans le bundle maillage.

Les traces de conversion sont conservees dans `observables.csv` via
`derived_from_variable`, `conversion_applied` et `cell_area_m2`.

## Exemple

Un exemple qui reutilise des artefacts deja versionnes est disponible :

```powershell
python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_existing.toml
```

Exemples MF6 vs NWT :

```powershell
python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_same_regular_mesh.toml
python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_mf6_vs_nwt_different_meshes.toml
python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_example12_extensive_mf6_vs_nwt.toml
```

Le premier exemple garde le meme `sgrid` structure pour les deux solveurs. Le
premier montre directement une carte de charge, une carte de difference et une
serie `outlet_flux`. Le second montre un contraste `modflow6` sur maillage
triangulaire pre-calcule contre `modflownwt` sur grille reguliere ; il utilise
donc des reductions de carte au lieu d'un point/cellule partage pour les
metriques, tout en alimentant encore les cartes visuelles.

Autres cas reels :

```powershell
python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_example12_fast_shared_mesh.toml
python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_headwater_100km2_outlet_2_backends.toml
```

Le premier compare MF6 et Boussinesq sur le meme maillage triangulaire versionne
de `example12`. Le second compare deux backends Boussinesq sur le vrai bassin
`headwater_100km2_outlet_2` et son bundle galerie versionne.
