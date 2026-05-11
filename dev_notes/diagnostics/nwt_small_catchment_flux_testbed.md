# Testbed flux transitoires MODFLOW-NWT par site

Liens :
[simulation_comparison_workflow.md](simulation_comparison_workflow.md),
[simulation_catalog_architecture.md](simulation_catalog_architecture.md),
[boussinesq_petsc_complementarity_nancon_diagnostic.md](boussinesq_petsc_complementarity_nancon_diagnostic.md).

## Objectif

Cette note documente un testbed leger pour regarder les flux produits par
MODFLOW-NWT sur plusieurs exutoires d'une meme region avant de comparer avec
les formulations Boussinesq ou MODFLOW 6.

Le principe suit l'esprit du batch mesh :

- une region commune, ici le DEM du Massif armoricain,
- un catalogue de sites/exutoires,
- un meme cas transitoire applique a chaque site,
- des workspaces et figures separes par site,
- aucune modification du solveur.

Configuration ajoutee :

```text
examples/projects/10_testbed_workflow/base_armorican_nwt_flux_transient.toml
examples/projects/10_testbed_workflow/nwt_small_catchment_flux_testbed.toml
examples/projects/10_testbed_workflow/site_tables/armorican_demo_sites.csv
```

Par defaut, le fichier execute maintenant huit sites numerotes :

```toml
execute = true
```

Pour inspecter seulement le plan et les TOML enfants sans lancer MODFLOW-NWT,
passer temporairement `execute = false`.

## Pourquoi ce n'est pas encore un vrai batch dynamique

Le workflow `mesh_catchment_batch` sait lire directement une table d'exutoires
et boucler dessus. Le workflow `testbed` actuel ne lit pas encore un catalogue
de sites pour generer automatiquement les variantes.

La solution retenue reste volontairement sans code :

- `site_tables/armorican_demo_sites.csv` sert de catalogue explicite,
- chaque ligne active du catalogue est recopiee comme un `[[testbed.variant]]`,
- la variante ne change que `geographic.x_outlet`, `geographic.y_outlet`,
  `workspace.project_root`, `simulation.name` et `display.output_dir`.

Si le besoin se confirme, l'etape suivante propre serait d'ajouter au testbed
un petit expand depuis catalogue, ou de passer par `workflow = "batch"` /
`regional_lab` pour les campagnes multi-sites.

## Commandes

Depuis la racine du depot :

```powershell
hmp run examples/projects/10_testbed_workflow/nwt_small_catchment_flux_testbed.toml
```

Si `hmp` n'est pas disponible dans le shell courant :

```powershell
python -c "from hydromodpy.cli.main import main; main(['run', 'examples/projects/10_testbed_workflow/nwt_small_catchment_flux_testbed.toml'])"
```

Sorties du plan :

```text
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/testbed_plan.json
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/testbed_cases.csv
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/testbed_manifest.json
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/testbed_report.md
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/_generated_configs/
```

Generer ensuite les pages HTML :

```powershell
python examples/projects/10_testbed_workflow/generate_nwt_flux_testbed_web_report.py
```

Sorties HTML :

```text
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/web/index.html
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/web/site_01.html
...
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/web/site_08.html
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/web/assets/regional_site_locations.png
```

Ces pages restent utiles meme avant execution : elles affichent les cas
planifies et des emplacements `Figure non generee` tant que les figures ne sont
pas encore disponibles.

Pour ne generer que le plan, passer :

```toml
execute = false
```

puis relancer la meme commande.

## Sites

Le catalogue de demonstration contient huit exutoires numerotes :

```text
Site 01  x=131189.100  y=6833784.400
Site 02  x=142435.200  y=6837977.100
Site 03  x=153077.000  y=6832394.300
Site 04  x=162427.700  y=6839998.400
Site 05  x=132962.900  y=6845656.100
Site 06  x=146274.500  y=6849349.000
Site 07  x=158140.700  y=6851240.500
Site 08  x=164915.000  y=6861154.300
```

Ces points restent dans l'emprise de
`examples/data/hydrography/regional_stream_network.shp`. C'est important pour
que les cartes de situation regionales puissent situer les exutoires sur le
reseau de reference. Pour un vrai screening de petits bassins, il faudra
remplir le CSV avec les exutoires issus du scan mesh ou d'une selection SIG
compatible avec le jeu hydrographique choisi.

## Cas transitoire commun

La base regionale est volontairement simple :

- MODFLOW-NWT,
- grille structuree `80 x 80`,
- une couche,
- aquifere d'epaisseur constante `30 m`,
- parametres homogenes `K = 5e-5 m/s`, `Sy = 0.05`, `Ss = 1e-5 m-1`,
- condition de drainage au toit,
- recharge mensuelle synthetique commune a tous les sites,
- hydrographie de reference locale :
  `examples/data/hydrography/regional_stream_network.shp`.

Le choix de la recharge synthetique est intentionnel. Il evite de recycler une
station locale d'un autre bassin et rend la premiere lecture plus autonome.

## Ce qui doit etre regarde

Lire les sorties dans cet ordre.

1. `testbed_cases.csv`

   Verifier que les huit variantes sont presentes, que les chemins de
   configuration enfant sont corrects, et que le statut est `planned` quand
   `execute = false`, puis `ok` quand `execute = true`.

2. Les TOML dans `_generated_configs/`

   Controler que chaque fichier contient le bon exutoire :

   ```text
   site_01.toml -> x_outlet = 131189.100
   ...
   site_08.toml -> x_outlet = 164915.000
   ```

3. `testbed_metrics.csv`

   Colonnes importantes apres execution :

   ```text
   n_cells
   n_timesteps
   max_abs_balance_error_percent
   head_range_m
   watertable_depth_mean_last_m
   budget_recharge_total_in_m3_s
   budget_drains_total_out_m3_s
   drain_outflow_last_positive_sum_m3_s
   accumulation_flux_last_positive_sum
   ```

   Une colonne optionnelle vide n'est pas forcement un echec ; cela signifie
   souvent que le composant n'a pas ce nom exact dans la sortie NWT.

4. Figures par site

   Chaque run ecrit ses figures sous :

   ```text
   <site_workspace>/figures/<run_name>/
   ```

   Figures a ouvrir en premier :

   ```text
   site_regional_location.png
   watershed_id_card.png
   catchment_flux_balance_rates.png
   catchment_flux_balance.csv
   water_budget.png
   recharge_discharge_overlay.png
   head_timeseries_points.png
   piezometric_map.png
   hydrographic_network_overlay.png
   observed_network_seepage_overlay.png
   ```

5. Pages HTML

   Ouvrir :

   ```text
   outputs/nwt_small_catchment_flux/web/index.html
   ```

   L'index donne la comparaison rapide des sites, puis chaque page
   `site_*.html` reprend les controles, les metriques et toutes les figures
   attendues pour un seul exutoire.

## Signes que le calcul a marche

Le testbed doit etre lu comme un diagnostic numerique, pas comme une validation
hydrologique.

Signaux minimaux attendus :

- les sites selectionnes se terminent avec `status = ok`,
- le bilan de masse reste petit dans `max_abs_balance_error_percent`,
- `site_regional_location.png` situe clairement le site courant dans la region,
- `catchment_flux_balance_rates.png` met les entrees au-dessus de zero et les
  sorties en dessous, en `mm/j`, sur le bassin hors tampon,
- `water_budget.png` est lu comme un diagnostic solveur sur le domaine complet,
  tampon inclus,
- `recharge_discharge_overlay.png` montre l'amplitude et le delai de reponse,
- `hydrographic_network_overlay.png` compare le reseau genere au reseau
  observe avec le contour du bassin simule,
- `observed_network_seepage_overlay.png` superpose le reseau observe et les
  zones de drainage/suintement produites par le calcul,
- les cartes d'identite montrent des domaines differents, ce qui confirme que
  l'exutoire a bien change le bassin.

Sur l'index HTML, la table comparative derive en plus :

```text
surface du bassin
altitude de l'exutoire
pente moyenne
debit max et moyen
debits specifiques en L/s/km2
delai de reponse
volume draine cumule
erreur de bilan si disponible dans le catalogue
```

Trois scatters inter-sites aident a lire les tendances :

```text
surface vs debit max
surface vs volume draine
pente moyenne vs delai de reponse
```

## Configuration a retenir

Le deplacement d'un site se fait par la variante :

```toml
[[testbed.variant]]
id = "site_06"
axis = "site"

[testbed.variant.overlay.geographic]
x_outlet = 146274.500
y_outlet = 6849349.000
```

Les sorties de flux sont activees dans la base par :

```toml
[simulation.results.derived]
outflow_drain = true
accumulation_flux = true
watertable_depth = true
watertable_elevation = true

[simulation.results.budget]
spatial_fields = true
```

Les figures sont produites sans interaction graphique :

```toml
[display]
enabled = true
show = false
save = true
figures = [
  "watershed_id_card",
  "piezometric_map",
  "water_budget",
]
```

## Limites connues

Le testbed exploite ce que le catalogue sait deja extraire. Il ne force pas un
schema scientifique nouveau.

Points a surveiller :

- le CSV de sites n'est pas encore consomme automatiquement par `workflow =
  "testbed"`,
- les huit sites sont des points de demonstration, pas un echantillonnage
  hydrologique representatif,
- les metriques testbed ne regardent aujourd'hui que le dernier pas de temps
  pour les statistiques de champs,
- `catchment_flux_balance_*.png` utilise le masque bassin reprojete sur les
  cellules du modele et ne garde les flux `flow right/front face` que lorsque
  la face traverse le contour du bassin,
- `water_budget.png` agrege le budget sur toute la simulation et sur tout le
  domaine MODFLOW, pas seulement sur le bassin hors tampon,
- il n'existe pas encore de figure single-run dediee a la carte continue
  `outflow_drain`.

Si la premiere lecture n'est pas suffisante, l'ajout le plus utile serait une
figure de diagnostic flux single-run avec quatre panneaux :

```text
recharge_series
drain_outflow_series
outflow_drain_map_last
accumulation_flux_map_last
```

Ce serait un ajout de visualisation seulement, sans toucher au solveur.
