# 00 — getting_started

Premier contact avec HydroModPy : un aquifère 1D de type **Dupuit**,
recharge uniforme, régime **permanent**, résolu avec **MODFLOW-NWT**.

## Objectif pédagogique

- Découvrir la structure minimale d'un fichier `project.toml`.
- Lancer un run de bout en bout (`hmp run` ou `hmp.run`).
- Comprendre l'écriture automatique dans le `SimulationCatalog`
  (DuckDB + Zarr).

## Prérequis

- `pip install -e .` depuis la racine du dépôt.
- Aucune donnée externe, aucun accès réseau.

## Lancement

```bash
# Depuis la racine du dépôt
hmp run examples/00_getting_started/project.toml
# ou
python examples/00_getting_started/run.py
```

## Ce qui est produit

- Un enregistrement dans `hydromodpy.duckdb` (table `simulations`).
- Un Zarr par run dans `simulations/<uuid>.zarr/`.
- Le `sim_id` imprimé sur stdout.

## Points clés du TOML

| Section | Rôle |
|---|---|
| `[simulation]` | Nom du run, processus actifs, solveurs. |
| `[geographic.synthetic]` | Domaine jouet (pas de DEM externe). |
| `[domain.depth_model]` | Épaisseur constante de l'aquifère. |
| `[flow]` | Régime, BC actives, paramètres. |
| `[flow.bc.dirichlet.*]` | Charges imposées aux bords est et ouest. |
| `[data.recharge.sources]` | Recharge synthétique uniforme (mm/j). |
| `[modflownwt.sgrid.*]` | Discrétisation MODFLOW-NWT. |
| `[display]` | `enabled = false` → pas de fenêtre matplotlib. |
