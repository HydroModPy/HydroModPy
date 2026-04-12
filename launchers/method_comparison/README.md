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

## Sorties

Le launcher ecrit dans `method_comparison/<comparison_id>/` par defaut :

- `comparison_manifest.json` : statut des variantes, chemins, metadonnees de runs.
- `observables.csv` : valeurs extraites au format long.
- `comparison_metrics.csv` : resume des ecarts a la variante de reference.
- `comparison_differences.csv` : ecarts detailles par observable et temps.
- `comparison_metrics.json` : representation JSON du resume et des ecarts.
- `comparison_report.md` : synthese lisible des variantes, metriques et lignes non apparies.

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
