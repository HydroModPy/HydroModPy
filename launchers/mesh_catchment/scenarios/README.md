# Mesh Catchment Scenarios

`scenarios/` contient uniquement des TOML runnable versionnes pour
`MeshCatchmentLauncher`.

Pour la matrice de decision, les configs minimales, et la carte du package,
voir aussi `../README.md`.

- Les bases partagees restent au niveau parent (`config_common.toml`,
  `config_batch_common.toml`).
- Les templates schema-first restent aussi au niveau parent
  (`config_template.toml`, `config_batch_template.toml`).
- Les fichiers de ce dossier representent des cas d'usage concrets et peuvent
  donc heriter des bases via `base_config = "../..."`.

Commande recommandee :

`python -m launchers mesh-catchment run launchers/mesh_catchment/scenarios/config_example.toml`
