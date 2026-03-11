# Display

`hydromodpy/display/` centralise les sorties de visualisation et les exports
graphiques utilises apres l'execution des simulations HydroModPy.

## Fichiers principaux

- `__init__.py`: expose l'API publique du package display.
- `options.py`: parse et normalise les options du bloc TOML `[display]`.
- `common.py`: helpers partages pour les dossiers de sortie et la fermeture
  propre des figures.
- `flow_plots.py`: figures Matplotlib liees au module d'ecoulement.
- `particles_plots.py`: cartes de trajectoires et ponts vers les viewers 2D/3D
  historiques.
- `transport_plots.py`: export des cartes de concentration, GIF et animation
  HTML.
- `suites.py`: orchestration haut niveau des suites `flow`, `particles` et
  `transport`.
- `visualization_results.py`: viewer 2D/3D historique reutilise par certains
  affichages.
- `visualization_watershed.py`: outils de visualisation geographique du bassin.
- `export_vtuvtk.py`: export VTK utilise par les visualisations 3D.

## Configuration attendue

Le package consomme un bloc optionnel `[display]` dans le TOML principal :

```toml
[display]
enabled = true
show = true
save = false
dpi = 300
respect_env_no_display = true

[display.flow]
cross_section = true
streamflow = true
piezometry = true

[display.particles]
pathlines = false
plot_2d = false
plot_3d = false

[display.transport]
concentration = false
gif = false
web_animation = false
```

`HYDROMODPY_NO_DISPLAY=1` force `show = false` si
`respect_env_no_display = true`, ce qui permet des executions CI/headless sans
ouvrir de fenetres.
`HYDROMODPY_NO_SAVE=1` force `save = false` si `respect_env_no_save = true`,
empêchant les exports de figures lorsque les runs CI/headless doivent rester
propres.

## Flux d'execution

1. `display_options_from_raw_toml(...)` construit un objet `DisplayOptions`.
2. Le code appelant selectionne `plot_flow_suite(...)`,
   `plot_particles_suite(...)` et/ou `plot_transport_suite(...)`.
3. Chaque suite verifie les drapeaux actives, charge les donnees
   post-traitees, puis delegue aux fonctions de tracage specialisees.
4. `finalize_figure(...)` decide si la figure doit etre affichee, sauvegardee
   ou simplement fermee.

## Sorties ecrites

- Figures standard: `simulations/<model>/_postprocess/_figures/`
- Figures transport: `simulations/<model>/_postprocess/_figures/transport/`
- Les viewers 3D peuvent aussi generer des fichiers VTK sous le dossier de
  simulation du modele.

## Notes maintenance

- Les imports lourds (`geopandas`, `rasterio`, `plotly`, `flopy`) sont gardes
  au plus pres des fonctions qui en ont besoin pour limiter les dependances au
  chargement du module.
- Les nouveaux tracages doivent passer par `DisplayOptions` pour rester
  coherents avec les modes interactif, headless et export disque.
