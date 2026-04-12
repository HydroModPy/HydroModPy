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

## Outlet

Pour `support = "outlet"`, fournir un `cell_index` ou une coordonnee `x/y`.
Sans localisation explicite, le launcher refuse l'extraction. Un mode
exploratoire reste possible avec `allow_domain_proxy = true`, qui applique le
reducteur a tout le domaine et marque la ligne avec
`selection = "domain_reducer_proxy"`.

## Flux

`accumulation_flux` est lu depuis les sorties MODFLOW quand elles existent.
Pour Boussinesq, le launcher tente un fallback vers
`drainage_flux_history_m3_s` ou `drainage_flux_m3_s`. Les unites natives sont
conservees dans `native_unit`; les metriques ne comparent que les lignes dont
l'unite de sortie est identique.

## Exemple

Un exemple qui reutilise des artefacts deja versionnes est disponible :

```powershell
python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_existing.toml
```
