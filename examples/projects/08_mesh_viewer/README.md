# 08 - Mesh viewer

Inspection visuelle de bundles de maillage pré-exportés (Gmsh + CSV +
JSON sidecars). Aucun solveur n'est lancé : on relit le bundle et on
le rend en PNG + JSON résumé.

## Schéma spécialisé : pas de `hmp run`

Les TOML de ce projet ne sont pas du `HydroModPyConfig`. Leur schéma
dédié est consommé par le runner `tools/mesh_bundle_viewer/`, **pas
par `hmp run`** :

```bash
python -m mesh_bundle_viewer \
    --config examples/projects/08_mesh_viewer/config_example.toml
```

Conséquence : `hmp config check` rejette ces fichiers (champs
inconnus). C'est attendu.

## Contenu

| Fichier / dossier | Rôle |
|---|---|
| `config_example.toml` | Configuration de référence pointant `default_bundle/`. |
| `config_mesh_catchment_outlet_5.toml` | Configuration pour le bundle headwater 100 km² (`mesh_catchment_outlet_5_bundle/`). |
| `default_bundle/` | Bundle minimal 2 cellules (placeholder Gmsh). |
| `sample_bundle/` | Bundle complet pour un workflow externe. |
| `mesh_catchment_outlet_5_bundle/` | Bundle réel issu d'un run `mesh_catchment`. |

Chaque sous-dossier `*_bundle/` porte son propre README détaillant les
CSV (`nodes`, `cells`, `edges`, `cell_geology_fractions`) et le JSON
de métadonnées (`metadata.json`, `mesh_summary.json`).

## Sorties

Quand `show_window = false`, le runner écrit :

- un PNG d'aperçu (panneau structurel + panneau hydraulique) sous le
  chemin `figure_output_path`,
- un JSON résumé sous le chemin `summary_output_path`.

Quand `show_window = true`, une fenêtre matplotlib interactive
s'ouvre à la fin.
