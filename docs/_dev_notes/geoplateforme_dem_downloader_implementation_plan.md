# Plan d'implementation - telechargement DEM IGN par departement

Date: 2026-05-23

## Objectif

Mettre en place un outil robuste pour telecharger automatiquement les MNT/DEM
IGN par departement depuis les services publics IGN/Geoplateforme, avec deux
usages distincts:

1. un outil CLI autonome pour explorer et telecharger des archives par
   departement;
2. une brique reutilisable par `hydromodpy.data.variables.dem`, afin que les
   workflows comme `site_selection` puissent demander un DEM regional sans
   connaitre les details de l'API IGN.

Le code ne doit pas etre localise dans `site_selection`. La selection de sites
doit seulement exprimer un besoin de DEM, par exemple via un territoire, une
bbox ou une liste de departements. La resolution des departements, le
telechargement, le cache et l'assemblage raster appartiennent a la couche
`hydromodpy.data`.

## Etat d'implementation

Etat au 2026-05-24.

### Developpe

- Registre statique des regions francaises dans
  `hydromodpy/core/administrative_france.py`, reexporte par
  `hydromodpy/data/common/administrative/france.py`.
  - Regions metropolitaines, Corse et DROM standards couverts:
    Guadeloupe, Martinique, Guyane, La-Reunion, Mayotte.
  - Normalisation sans accent et acceptation des codes INSEE de region.
  - Alias explicites ajoutes pour `La Reunion` et `Reunion`.
- Validation des regions francaises branchee dans:
  - `hydromodpy/spatial/site_selection/config.py`;
  - `hydromodpy/data/variables/dem/config.py` pour les sources
    `ign_bdalti` et `ign_geoplateforme_dem`.
- Resolution administrative locale disponible dans
  `hydromodpy/data/common/administrative/france.py`:
  - `find_departments_in_regions(...)`;
  - `find_departments_in_bbox(...)`;
  - `bbox_for_departments(...)`;
  - `bbox_for_regions(...)`;
  - normalisation des departements en codes 3 caracteres.
- Client Geoplateforme isole dans
  `hydromodpy/data/variables/dem/apis/geoplateforme_download.py`:
  - dataclasses `AtomEntry`, `DiscoveryFilters`, `DownloadFile`;
  - parsing Atom via `parse_atom_entries(...)`;
  - pagination via `fetch_atom_entries(...)`, avec lecture de
    `totalentries`;
  - `RateLimiter`;
  - retry/backoff sur `429`, `500`, `502`, `503`, `504`;
  - `list_subresources(...)`, `list_files(...)`,
    `build_download_url(...)`;
  - `download_file(...)` avec cache local, fichier `.part`, reprise par
    header `Range`, et reuse des fichiers non vides.
- Couche produit DEM IGN dans
  `hydromodpy/data/variables/dem/apis/ign_dem_fr.py`:
  - mapping `bd-alti -> BDALTI`, `rge-alti -> RGEALTI`;
  - `normalize_department_code(...)` vers le format Geoplateforme `Dxxx`;
  - decouverte par departement via sous-ressources/fichiers;
  - filtrage simple par resolution et format dans les noms de fichiers;
  - fallback statique BD ALTI 25 m ASC vers `_BDALTI_ARCHIVES` si la
    decouverte Geoplateforme echoue;
  - `download_ign_dem_departments(...)` avec `dry_run`, `max_files`,
    `overwrite`, `timeout`, `rate_limit` et arborescence de cache brut.
  - `fetch_ign_dem(...)` pour telecharger, extraire, fusionner et recadrer
    BD ALTI 25 m ASC en GeoTIFF via le nouveau cache
    `raw_ign/`, `extracted_ign/`, `processed/`.
- CLI autonome dans `tools/download_dem_fr/`:
  - `download_dem_fr.py`;
  - `README.md`;
  - `requirements.txt`.
  - Arguments implementes: `--departements`, `--dataset`, `--resolution`,
    `--format`, `--crs`, `--output-dir`, `--dry-run`, `--max-files`,
    `--timeout`, `--rate-limit`, `--overwrite`.
  - Le repertoire par defaut est hors depot:
    `HYDROMODPY_WORKSPACE/data/dem/raw_ign` ou
    `~/hydromodpy/data/dem/raw_ign`.
- Integration partielle au `DemManager` existant:
  - la source historique `ign_bdalti` accepte maintenant `departments`,
    `country` et `regions`;
  - les regions francaises sont canonicalisees;
  - les departements peuvent etre deduits depuis `regions`;
  - `fetch_bdalti(...)` recoit les departements explicites ou deduits.
- Nouvelle source configurable `ign_geoplateforme_dem` ajoutee dans
  `hydromodpy/data/variables/dem/config.py`:
  - `dataset = "bd-alti" | "rge-alti"`;
  - `resolution_m`;
  - `file_format`;
  - `crs`;
  - `departments`/`regions`.
- `DemManager` branche sur `ign_geoplateforme_dem`:
  - resolution de bbox via le meme chemin que `ign_bdalti`;
  - resolution des departements par region;
  - appel a `ign_dem_fr.fetch_ign_dem(...)`;
  - enregistrement du GeoTIFF produit dans le catalogue avec metadata
    `dataset`, `resolution_m`, `file_format`, `departments` et `regions`.
- `hydromodpy/data/variables/dem/resolver.py` reconnait aussi
  `ign_geoplateforme_dem` pour le bootstrap `geographic.dem_init_path`.
- Cache produit `processed/`:
  - hash stable par bbox/departements;
  - metadata sidecar JSON;
  - reuse du GeoTIFF si le raster couvre la requete et si la metadata est
    compatible;
  - adoption d'un ancien GeoTIFF compatible sans metadata.
- Adoption des anciens `cache.duckdb` de donnees:
  - les caches V1 qui possedent deja les tables `entries`, `artifacts`, etc.
    mais pas `schema_migrations` sont marques comme migration initiale deja
    appliquee;
  - cela evite que `hmp run` rejoue `0001_initial.sql` et echoue sur
    `entries already exists`.
- Exemples `site_selection` branches sur `[data.dem]` avec
  `ign_geoplateforme_dem` ou `ign_bdalti`:
  - Bretagne;
  - Auvergne-Rhone-Alpes;
  - Corse;
  - variantes avec stations hydrometriques reelles, fixtures de surface et
    BD Topage comme reference de snapping.
- Documentation RTD proposee:
  - page DEM `docs/source/user_guide/data/dem.rst` avec
    `ign_geoplateforme_dem`;
  - page workflow `docs/source/user_guide/workflows/site_selection.rst`;
  - entree `site_selection` dans l'index des workflows.

### Reste a developper

- Conserver `ign_bdalti` comme source historique ou alias compatible, mais
  clarifier quand elle utilise la table statique et quand elle utilise la
  decouverte Geoplateforme.
- Finaliser la documentation publique:
  - relire la nouvelle page RTD `site_selection`;
  - verifier que les captures/rapports HTML a montrer sont les bons;
  - decider si les sorties d'exemples doivent etre publiees comme artefacts
    RTD ou seulement decrites comme commandes reproductibles.
- Gerer RGE ALTI au-dela du telechargement:
  - archives fragmentees `.7z.001`, `.7z.002`, etc.;
  - choix prudent de resolution;
  - refus ou avertissement pour RGE ALTI 1 m sur une grande region.
- Utiliser ou documenter plus explicitement l'etape `capabilities`:
  aujourd'hui `ign_dem_fr.py` appelle directement les ressources fixes
  `BDALTI`/`RGEALTI`.
- Implementer les options encore absentes du CLI cible:
  - `--include-md5`;
  - fallback HTML experimental Geoservices;
  - logs plus structurants pour expliquer decouverte/fallback/cache.
- Ajouter des tests reseau optionnels marques `network`:
  - dry-run sur un petit departement;
  - telechargement limite `--max-files 1`;
  - verification bout en bout du manager `ign_geoplateforme_dem` sur BD ALTI
    25 m ASC.
- Decider du futur de `ign_bdalti`:
  - le garder comme chemin historique compatible;
  - ou le transformer progressivement en alias documente vers
    `ign_geoplateforme_dem` pour BD ALTI 25 m.
- Ne pas afficher BD Topage dans les cartes `site_selection` par defaut:
  - BD Topage reste utile comme reference technique pour `bdtopage_then_dem`;
  - son affichage sur fond DEM regional induit en erreur car il peut etre
    confondu avec le reseau valide des bassins selectionnes.

## Tests developpes et execution

Les tests ajoutes sont des tests sans reseau, marques `@pytest.mark.fast`. Ils
simulent l'API ou monkeypatchent les telechargements.

### Commande recommandee

```bash
python -m pytest -o addopts="" \
  tests/unit/data_managers/test_geoplateforme_dem_downloader.py \
  tests/unit/data_managers/test_france_administrative_regions.py \
  tests/unit/data_managers/test_dem_manager.py \
  tests/unit/config/test_discriminated_unions.py \
  tests/unit/site_selection/test_config.py \
  tests/unit/site_selection/test_example_configs.py \
  -m fast
```

`-o addopts=""` neutralise les options globales de `pytest.ini`, utile quand
les plugins facultatifs de l'environnement local ne sont pas tous installes.

Un test smoke plus large existe aussi:

```bash
python -m pytest -o addopts="" \
  tests/unit/data_managers/test_variable_managers_smoke.py \
  -m fast
```

Il requiert `pandera` dans l'environnement de test. Cette dependance est
declaree dans `pyproject.toml` et dans les YAML d'installation Conda.

### Resultat local observe

Commande lancee le 2026-05-23 avec `-o addopts=""`:

```text
48 tests collectes
48 passed
```

Apres installation locale de `pandera>=0.31.1,<1`, le test smoke passe aussi:

```text
tests/unit/data_managers/test_variable_managers_smoke.py
93 tests collectes
93 passed
```

Tests ajoutes ou relances le 2026-05-24:

```text
tests/unit/data_managers/test_catalog_extended.py::test_legacy_data_cache_schema_is_adopted
1 passed

tests/unit/data_managers/test_catalog_extended.py::test_schema_version_table_records_data_cache_version
1 passed

tests/unit/data_managers/test_geoplateforme_dem_downloader.py::test_fetch_ign_dem_assembles_small_asc_fixture
1 passed

tests/unit/data_managers/test_dem_manager.py::test_ign_geoplateforme_dem_regions_dispatch_to_dynamic_client
1 passed
```

Verification CLI locale le 2026-05-24:

```powershell
python -m hydromodpy.cli.main run `
  examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small_bdtopage.toml
```

Resultat observe:

```text
Workflow 'site_selection' complete
selected: 7
rejected: 0
site_selection_report_html:
  examples/projects/17_site_selection_workflow/outputs/
  bretagne_hydrometry_50_500_small_bdtopage_v1/review/index.html
```

### Couverture par fichier

- `tests/unit/data_managers/test_geoplateforme_dem_downloader.py`
  - normalisation des departements: `29`, `D035`, `971`, `2A`;
  - parsing Atom: liens, taille, md5;
  - pagination Atom;
  - conversion des entrees Atom en `DownloadFile`;
  - reuse d'un fichier local non vide;
  - ecriture `.part` puis renommage final;
  - fallback statique BD ALTI quand la decouverte Geoplateforme echoue;
  - dry-run et layout du cache brut.
  - assemblage d'une petite fixture `.asc` en GeoTIFF;
  - reuse du cache `processed/` et metadata sidecar.
  - rejet explicite de l'assemblage RGE ALTI tant qu'il n'est pas supporte.
  - Attendu: tests sans reseau.
- `tests/unit/data_managers/test_france_administrative_regions.py`
  - presence des regions metropolitaines et DROM;
  - alias `La Reunion`/`Reunion`;
  - codes INSEE de region;
  - erreur claire sur faute de frappe;
  - resolution de La Reunion vers `974`.
  - Attendu: 4 tests passent sans reseau.
- `tests/unit/data_managers/test_dem_manager.py`
  - departements explicites transmis a `fetch_bdalti`;
  - regions AURA resolues en 12 departements.
  - dispatch de `ign_geoplateforme_dem` vers `fetch_ign_dem(...)`.
  - metadata catalogue `dataset`/`resolution_m`/`file_format`/departements.
  - Attendu: tests sans reseau.
- `tests/unit/config/test_discriminated_unions.py`
  - dispatch Pydantic de `source = "ign_geoplateforme_dem"` vers
    `IgnGeoplateformeDemSource`.
  - Attendu: 19 tests passent sans reseau pour ce fichier.
- `tests/unit/site_selection/test_config.py`
  - validation/canonicalisation des regions dans `SiteSelectionConfig`;
  - rejet d'une region inconnue;
  - controles de strategie `area_only` et `observation_led`.
  - Attendu: 8 tests passent sans reseau.
- `tests/unit/site_selection/test_example_configs.py`
  - chargement des exemples Bretagne/AURA;
  - verification des sources DEM `ign_bdalti`;
  - execution de workflows de fixture avec `fetch_bdalti` monkeypatche;
  - verification des artefacts principaux produits.
  - Attendu: 5 tests passent sans reseau.

## Constat actuel

Le depot contient deja:

- `hydromodpy/data/common/administrative/france.py`
  - resolution locale des departements par region ou bbox;
  - normalisation interne des codes departements en format 3 caracteres:
    `35 -> 035`, `2A -> 02A`, `971 -> 971`.
- `hydromodpy/data/variables/dem/apis/ign_bdalti.py`
  - telechargement BD ALTI 25 m;
  - extraction d'archives 7z;
  - fusion et recadrage en GeoTIFF;
  - mais avec une table statique de noms d'archives `_BDALTI_ARCHIVES`.
- `hydromodpy/data/variables/dem/manager.py`
  - orchestration cache/catalogue;
  - appel historique a `fetch_bdalti(...)`;
  - appel dynamique a `fetch_ign_dem(...)` pour
    `source = "ign_geoplateforme_dem"`.

La limite principale restante est le perimetre d'assemblage raster: le nouveau
chemin dynamique produit un GeoTIFF pour BD ALTI 25 m ASC, mais RGE ALTI reste
au stade decouverte/telechargement brut.

## Sources API a supporter

Documentation publique:

- `https://data.geopf.fr/telechargement/capabilities`
- `https://data.geopf.fr/telechargement/resource/{resourceName}`
- `https://data.geopf.fr/telechargement/resource/{resourceName}/{subResourceName}`
- `https://data.geopf.fr/telechargement/download/{resourceName}/{subResourceName}/{fileName}`

Contraintes documentees:

- API conforme Atom RFC 4287;
- pagination avec `page` et `limit`;
- limite de service: 10 requetes/s/IP;
- filtre `zone`, par exemple `D075`;
- filtres optionnels: `format`, `crs`, `polygon`, dates, thematique.

Point de vigilance observe le 2026-05-17: les endpoints directs
`data.geopf.fr/telechargement/capabilities` et `resource/...` ont repondu
temporairement en 500/502 lors d'un test local. L'implementation doit donc etre
robuste aux indisponibilites momentanees et garder une strategie de secours.

## Localisation recommandee

La regle d'organisation est de contenir le changement dans deux zones:

```text
hydromodpy/data/variables/dem/
tools/download_dem_fr/
```

`hydromodpy/data/common/administrative/france.py` peut etre etendu seulement si
la resolution des regions/departements doit etre enrichie, par exemple pour les
noms usuels des DROM. Aucun code Geoplateforme ne doit etre ajoute dans
`site_selection`, dans les exemples de workflow ou dans les modules de figures.

### 1. Module API reutilisable

Creer:

```text
hydromodpy/data/variables/dem/apis/geoplateforme_download.py
```

Role:

- client Atom/HTTP Geoplateforme;
- pagination;
- normalisation des filtres;
- decouverte des ressources et sous-ressources;
- telechargement des fichiers;
- reprise si fichier deja present;
- limitation de debit;
- erreurs explicites.

Ce module ne doit pas fusionner les rasters et ne doit pas connaitre
`site_selection`.

## Politique de stockage des donnees

Les archives DEM/MNT et les rasters assembles sont des donnees de travail. Ils
ne doivent pas etre ecrits par defaut dans le depot Git, meme sous
`examples/data`, car ils peuvent etre volumineux, reutilisables entre projets
et dependants d'un millesime fournisseur.

La convention cible est:

```text
<workspace>/data/
  cache.duckdb
  dem/
    raw_ign/
      bd-alti/25m/D029/...
      rge-alti/5m/D029/...
    processed/
      dem_bdalti_25m_<hash>.tif
```

Resolution du workspace:

1. si `HYDROMODPY_WORKSPACE` est defini, utiliser
   `HYDROMODPY_WORKSPACE/data`;
2. sinon, utiliser le workspace utilisateur par defaut
   `~/hydromodpy/data`;
3. dans un TOML de production, permettre un override explicite via
   `[workspace].root`, `[workspace].data_dir`, `site_selection.input.data_root`
   ou `--output-dir` pour le CLI.

Avantages:

- les donnees brutes sont partagees entre Bretagne, AURA et futures regions;
- les fichiers lourds ne polluent pas le controle de version;
- les workflows restent reproductibles, car le catalogue et les chemins de
  cache sont explicites;
- le nettoyage peut etre gere par les commandes de workspace/data plutot que
  par des suppressions manuelles dans les exemples.

Inconvenients:

- une machine nouvelle doit remplir son cache avant de produire les figures;
- le rapport doit afficher clairement le chemin du DEM utilise pour lever toute
  ambiguite sur la provenance locale.

### 2. Module produit DEM France

Creer:

```text
hydromodpy/data/variables/dem/apis/ign_dem_fr.py
```

Role:

- mapper les choix utilisateur `rge-alti` et `bd-alti` vers les noms de
  ressources Geoplateforme (`RGEALTI`, `BDALTI`);
- choisir les bons fichiers parmi les sous-ressources trouvees;
- gerer les cas specifiques des archives fragmentees `.7z.001`, `.7z.002`,
  etc.;
- exposer une fonction stable du type:

```python
fetch_ign_dem_departments(
    *,
    output_dir: Path,
    departments: Sequence[str],
    dataset: Literal["rge-alti", "bd-alti"],
    resolution_m: float | None = None,
    file_format: str = "ASC",
    crs: str | None = None,
    dry_run: bool = False,
    max_files: int | None = None,
) -> list[Path]
```

### 3. CLI autonome

Creer un outil localise comme une unite autonome:

```text
tools/download_dem_fr/
  download_dem_fr.py
  README.md
  requirements.txt
```

Raison du choix:

- respecte la demande d'un fichier principal `download_dem_fr.py`;
- garde un README et un requirements dedies;
- evite d'ajouter `beautifulsoup4` et `lxml` comme dependances obligatoires de
  tout HydroModPy;
- permet de tester l'outil comme script independant;
- n'empeche pas de reutiliser ensuite la logique dans le package.

Le script CLI doit importer la brique package quand elle existe. En phase 1, il
peut contenir toute la logique. En phase 2, on deplace la logique stable dans
`hydromodpy/data/variables/dem/apis/`.

### 4. Integration au gestionnaire DEM HydroModPy

Etendre:

```text
hydromodpy/data/variables/dem/config.py
hydromodpy/data/variables/dem/manager.py
```

Deux options possibles:

Option A, conservative:

- garder `source = "ign_bdalti"` pour le comportement historique;
- ajouter `source = "ign_geoplateforme_dem"` pour le nouveau client dynamique;
- ajouter `dataset = "bd-alti" | "rge-alti"`.
- ajouter `resolution_m = 1 | 5 | 25 | 75 | ...` selon le dataset.

Option B, refonte progressive:

- remplacer progressivement `ign_bdalti` par une source generique
  `ign_dem`;
- garder un alias de compatibilite `ign_bdalti`.

Recommandation: option A au debut, car elle evite de casser les exemples et les
tests existants.

## Architecture cible

```text
site_selection config
    |
    | demande un DEM: territoire, bbox, departements explicites
    v
hydromodpy.workflow.site_selection
    |
    | construit ou transmet la config data.dem
    v
hydromodpy.data.variables.dem.manager.DemManager
    |
    | resout bbox/departements et cache catalogue
    v
hydromodpy.data.variables.dem.apis.ign_dem_fr
    |
    | selectionne dataset, departements, format
    v
hydromodpy.data.variables.dem.apis.geoplateforme_download
    |
    | capabilities/resource/subresource/download
    v
archives locales par departement
```

## Departements necessaires

Le code ne doit pas demander a l'utilisateur de saisir manuellement les
departements si un territoire est deja connu.

Cas a supporter:

- departements fournis explicitement:
  - `["29", "35"]` ou `["D029", "D035"]`;
- region administrative:
  - `find_departments_in_regions(["Auvergne-Rhone-Alpes"])`;
- bbox EPSG:2154:
  - `find_departments_in_bbox(bbox)`;
- territoire de `site_selection`:
  - conversion region/bbox vers liste de departements dans le workflow ou le
    manager DEM.

Pour Auvergne-Rhone-Alpes, la resolution locale donne:

```text
001, 003, 007, 015, 026, 038, 042, 043, 063, 069, 073, 074
```

Le format Geoplateforme correspondant est:

```text
D001, D003, D007, D015, D026, D038, D042, D043, D063, D069, D073, D074
```

## Couverture des regions francaises

L'objectif est que le code fonctionne pour chaque region administrative
francaise couverte par les produits IGN disponibles.

Etat local actuel:

- le GeoPackage embarque contient les departements de metropole, Corse incluse,
  et les DROM suivants: Guadeloupe, Martinique, Guyane, La Reunion, Mayotte;
- `find_departments_in_regions(...)` accepte deja les codes de region INSEE,
  y compris `01`, `02`, `03`, `04`, `06` pour les DROM;
- les noms de regions metropolitaines sont deja normalises;
- les noms usuels des DROM doivent etre ajoutes explicitement pour eviter
  d'obliger l'utilisateur a connaitre les codes INSEE.

Extension recommandee dans `france.py`:

```python
_REGION_CODE_BY_KEY.update(
    {
        "guadeloupe": "01",
        "martinique": "02",
        "guyane": "03",
        "la-reunion": "04",
        "reunion": "04",
        "mayotte": "06",
    }
)
```

Limites a documenter:

- les collectivites hors region administrative francaise standard ne doivent
  pas etre promises par defaut;
- le downloader peut normaliser `975`, `977`, `978`, etc. si l'utilisateur les
  passe explicitement, mais la resolution automatique par "region" depend du
  referentiel administratif embarque;
- la disponibilite effective depend du dataset IGN choisi et des fichiers
  exposes par Geoplateforme au moment du telechargement.

## Registre des regions autorisees dans les fichiers de parametres

Oui, les noms de regions acceptes dans les fichiers TOML doivent etre figes et
valides explicitement. Le but est d'eviter les erreurs silencieuses du type
`Auvergne Rhone`, `AURA`, `Bretange`, ou un nom de region non couvert.

La validation doit rester legere: elle ne doit pas lire le GeoPackage
departemental a chaque chargement de configuration. Il faut donc exposer un
registre statique d'alias dans:

```text
hydromodpy/data/common/administrative/france.py
```

API recommandee:

```python
FRENCH_REGION_ALIASES: Mapping[str, str]

def normalize_french_region_key(value: str) -> str: ...

def french_region_code(value: str) -> str:
    """Return the INSEE region code for a supported region name or code."""

def validate_french_regions(values: Sequence[str]) -> list[str]:
    """Return canonical region labels or raise ValueError with allowed names."""

def known_french_region_names() -> list[str]: ...
```

Les fichiers de parametres peuvent continuer a accepter les libelles lisibles:

```toml
[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Auvergne-Rhone-Alpes"]
```

Mais les valeurs doivent etre controlees des le chargement de config:

```text
hydromodpy/spatial/site_selection/config.py
  TerritoryConfig._validate_territory()
```

Regle:

- si `mode = "admin_regions"` et `country = "FR"`, chaque region doit etre
  validee par `validate_french_regions(...)`;
- si une region est inconnue, l'erreur doit lister les noms acceptes;
- les alias documentes peuvent etre acceptes, mais ils doivent rester explicites
  dans le registre, pas deduits par heuristique floue.

Liste canonique a supporter:

```text
Auvergne-Rhone-Alpes
Bourgogne-Franche-Comte
Bretagne
Centre-Val-de-Loire
Corse
Grand-Est
Hauts-de-France
Ile-de-France
Normandie
Nouvelle-Aquitaine
Occitanie
Pays-de-la-Loire
Provence-Alpes-Cote-d-Azur
Guadeloupe
Martinique
Guyane
La-Reunion
Mayotte
```

Alias a accepter explicitement:

```text
Auvergne-Rhone-Alpes -> Auvergne-Rhone-Alpes
Ile-de-France -> Ile-de-France
Provence-Alpes-Cote-d'Azur -> Provence-Alpes-Cote-d-Azur
La Reunion -> La-Reunion
Reunion -> La-Reunion
```

Alias a discuter avant acceptation:

```text
AURA
PACA
IDF
```

Ces abbreviations sont pratiques, mais elles peuvent rendre les fichiers moins
explicites. Recommandation: ne pas les accepter dans les TOML de production au
debut; les garder eventuellement pour le CLI interactif.

Tests de validation obligatoires et etat:

- fait: presence des noms canoniques principaux, y compris DROM;
- fait: alias documentes `La Reunion` et `Reunion`;
- fait: codes region INSEE comme `84` et `04`;
- fait: faute de frappe avec `ValueError` claire;
- fait: `TerritoryConfig` rejette une region inconnue quand `country = "FR"`;
- reste a tester explicitement: `TerritoryConfig` ne tente pas de valider avec
  le registre francais quand `country` n'est pas `FR`;
- fait: les exemples Bretagne et AURA restent valides.

Tests developpes:

```text
tests/unit/data_managers/test_france_administrative_regions.py
tests/unit/site_selection/test_config.py
tests/unit/site_selection/test_example_configs.py
```

Documentation:

- ajouter la liste des regions autorisees dans le README de l'exemple
  `17_site_selection_workflow`;
- ajouter cette liste dans la documentation HTML de la reference config
  `site_selection.territory.regions`;
- rappeler que la resolution automatique des departements s'appuie sur ce
  registre.

## Cache local et verification avant telechargement

Le comportement attendu est "cache first":

1. calculer la liste des departements demandes;
2. construire les chemins cibles attendus dans:

```text
<workspace>/data/dem/raw_ign/{dataset}/{resolution_m}m/{departement}/
```

3. si tous les fichiers requis sont presents et non vides, ne rien
   telecharger;
4. si une archive est partiellement presente (`.part`) ou vide, la reprendre ou
   la retenter;
5. si les archives departementales existent mais pas le GeoTIFF assemble, ne
   pas retelecharger: extraire/fusionner a partir du cache local;
6. si le GeoTIFF assemble couvrant la bbox existe dans le catalogue HydroModPy,
   le reutiliser directement, sauf `force_refresh = true`.

Le cache doit donc avoir deux niveaux:

- cache brut: archives et fichiers extraits par departement;
- cache produit: GeoTIFF fusionne/recadre et reference dans le catalogue.

Cela evite de retelecharger les memes departements pour plusieurs exemples ou
plusieurs regions qui se recouvrent.

## Resolution et echelle des DEM

Dans le code, il faut distinguer:

- la resolution raster, ou pas de grille, exprimee en metres;
- l'echelle cartographique d'usage, qui decrit le niveau de detail vise.

Datasets a supporter:

| Dataset | Resolutions visees | Usage recommande |
| --- | ---: | --- |
| `bd-alti` | 25 m, 75 m selon disponibilite actuelle; autres pas historiques possibles selon ressources exposees | fonds regionaux, selection amont, calculs hydrologiques exploratoires |
| `rge-alti` | 1 m, 5 m | analyses fines, petits bassins, controles locaux |

Pour `site_selection`, la valeur par defaut recommandee reste:

```toml
resolution_m = 25.0
dataset = "bd-alti"
```

Raison:

- 25 m est assez fin pour un premier calcul de bassins regionaux;
- le volume reste gerable a l'echelle d'une region;
- RGE ALTI 1 m est trop lourd pour une region entiere et doit etre reserve a
  une emprise locale ou a une demande explicite.

Le parametrage cible dans `[data.dem]`:

```toml
[[data.dem.sources]]
source = "ign_geoplateforme_dem"
dataset = "bd-alti"
resolution_m = 25.0
regions = ["Auvergne-Rhone-Alpes"]
format = "ASC"
cache_policy = "use_cache_else_download"
```

Si `departments` est absent, le manager doit les deduire de la bbox ou de la
region. Si `resolution_m` est absent, le manager choisit une resolution par
defaut coherente avec le dataset (`25 m` pour `bd-alti`, `5 m` pour
`rge-alti` si une emprise locale le justifie).

## Fonctions CLI demandees

Le script `tools/download_dem_fr/download_dem_fr.py` doit exposer au minimum:

```python
normalize_department_code(value: str) -> str
fetch_atom_entries(url: str, params: Mapping[str, str | int | None]) -> list[AtomEntry]
find_resources(dataset: str, filters: DiscoveryFilters) -> list[AtomEntry]
list_subresources(resource_name: str, filters: DiscoveryFilters) -> list[AtomEntry]
list_files(resource_name: str, subresource_name: str, filters: DiscoveryFilters) -> list[DownloadFile]
download_file(file: DownloadFile, destination: Path, session: requests.Session) -> Path
main(argv: Sequence[str] | None = None) -> int
```

Types internes proposes:

```python
@dataclass(frozen=True)
class AtomEntry:
    title: str
    identifier: str
    links: tuple[str, ...]
    properties: Mapping[str, str]

@dataclass(frozen=True)
class DownloadFile:
    resource_name: str
    subresource_name: str
    file_name: str
    url: str
    size: int | None = None
    checksum: str | None = None
```

## Interface CLI

Arguments:

```text
--departements 29 35 75
--dataset rge-alti | bd-alti
--resolution 25
--format ASC
--output-dir ~/hydromodpy/data/dem/raw_ign
--dry-run
--max-files N
```

Arguments utiles a ajouter des le depart:

```text
--crs epsg:2154
--limit 50
--timeout 30
--rate-limit 8
--overwrite
--include-md5
```

`--rate-limit` doit rester par defaut sous la limite publique de 10 requetes/s.
Valeur recommandee: 5 a 8 requetes/s.

## Normalisation des codes departements

Regle CLI:

```text
29   -> D029
035  -> D035
D035 -> D035
75   -> D075
971  -> D971
2A   -> D02A
D02B -> D02B
```

Implementation:

- reutiliser `department_code_to_padded(...)` cote package;
- ajouter seulement le prefixe `D` dans le client Geoplateforme;
- refuser les chaines vides ou non interpretable avec un message clair.

## Decouverte des ressources

Strategie nominale:

1. appeler `capabilities` avec `zone`, `format`, `limit`, `page`;
2. filtrer les entrees dont le nom ou l'identifiant correspond au dataset:
   - `bd-alti` -> `BDALTI`;
   - `rge-alti` -> `RGEALTI`;
3. filtrer la resolution demandee dans le nom de ressource ou les metadonnees,
   par exemple `25M`, `5M`, `1M`;
4. appeler `resource/{resourceName}` pour lister les sous-ressources;
5. appeler `resource/{resourceName}/{subResourceName}` pour lister les fichiers;
6. telecharger via `download/{resourceName}/{subResourceName}/{fileName}`.

Strategie de secours:

- si `capabilities` ou `resource` renvoie 5xx, logguer l'erreur et proposer:
  - dry-run interrompu proprement;
  - ou fallback experimental vers la page
    `https://geoservices.ign.fr/telechargement-api/{resourceName}?zone=Dxxx`
    pour recuperer les liens deja exposes publiquement;
  - ou fallback temporaire vers `_BDALTI_ARCHIVES` pour `bd-alti` uniquement,
    afin de conserver le comportement existant.

Le fallback HTML doit etre isole dans une fonction separee, pas melange avec le
client Atom.

## Pagination Atom

`fetch_atom_entries` doit:

- envoyer `page=1`, `limit=50` par defaut;
- lire le total quand `gpf_dl:totalentries` est present;
- continuer jusqu'a avoir recupere toutes les entrees ou jusqu'a page vide;
- respecter `max_files` quand il est donne;
- ne pas depasser le rate limit;
- lever une erreur dediee pour les codes 4xx;
- reessayer quelques fois sur 429/500/502/503/504 avec backoff.

## Telechargement et reprise

`download_file` doit:

- creer `<workspace>/data/dem/raw_ign/{dataset}/{resolution_m}m/{departement}/`;
- ignorer un fichier deja present si sa taille est non nulle;
- utiliser un fichier temporaire `.part` pendant le telechargement;
- faire un rename atomique vers le nom final;
- afficher les tailles et URLs en dry-run;
- telecharger aussi les `.md5` si `--include-md5`;
- gerer les archives fragmentees `.7z.001`, `.7z.002`, etc. sans les renommer.

Arborescence:

```text
<workspace>/data/dem/raw_ign/
  rge-alti/
    5m/
      D029/
        RGEALTI_...5M...D029....7z
    1m/
      D029/
        RGEALTI_...1M...D029....7z.001
        RGEALTI_...1M...D029....7z.002
  bd-alti/
    25m/
      D035/
        BDALTIV2_...25M...D035....7z
```

## Extraction et assemblage

Le CLI demande surtout le telechargement. Dans HydroModPy, l'assemblage doit
reutiliser le flux existant de `ign_bdalti.py`:

1. extraire les archives dans un cache departemental court;
2. rechercher les fichiers `.asc` ou `.tif`;
3. fusionner et recadrer a la bbox demandee;
4. produire un GeoTIFF unique dans `<workspace>/data/dem/processed`;
5. enregistrer le produit dans le catalogue.

RGE ALTI peut etre volumineux, surtout en 1 m. Pour `site_selection`, le choix
par defaut devrait rester prudent:

- `bd-alti` ou RGE ALTI 5 m pour une carte regionale;
- eviter RGE ALTI 1 m sur une region entiere sauf demande explicite.

## Tests restants a ajouter

Les tests unitaires principaux ont ete ajoutes et sont detailles plus haut dans
la section "Tests developpes et execution". Les manques de couverture sont:

- retry verifie explicitement sur `429` et `500`;
- generation correcte des URLs de download sur plusieurs cas d'encodage;
- filtrage dataset/format/zone sur une fixture plus proche des flux
  Geoplateforme reels;
- CLI `main(...)` teste directement, pas seulement les fonctions importees;
- assemblage raster BD ALTI 25 m ASC teste avec petites fixtures locales;
- cache produit `processed/` teste sans reseau;
- tests reseau optionnels marques `network`:
  - dry-run sur un petit departement;
  - telechargement limite avec `--max-files 1`;
  - verification bout en bout du manager `ign_geoplateforme_dem`.

## Documentation a livrer

### Livre

- `tools/download_dem_fr/README.md` documente:
  - l'objectif du CLI;
  - le cache hors depot;
  - l'installation minimale;
  - les exemples Bretagne/Paris/DROM/AURA;
  - la limite du fallback BD ALTI 25 m ASC.
- `tools/download_dem_fr/requirements.txt` existe avec:

```text
requests
beautifulsoup4
lxml
```

### Reste

- Ajouter dans la documentation HydroModPy utilisateur que le CLI est un outil
  de preparation/cache, tandis que le workflow normal doit passer par
  `[data.dem]`.
- Documenter la source `ign_geoplateforme_dem` dans la documentation utilisateur
  HydroModPy.
- Documenter les regions francaises acceptees dans la reference de configuration
  si ce n'est pas encore synchronise avec les pages generees.

## Plan de developpement - statut

### Phase 1 - CLI autonome: fait

- `tools/download_dem_fr/download_dem_fr.py` cree;
- argparse implemente;
- normalisation des departements implementee;
- client Atom + pagination + rate limit disponible via le package;
- dry-run implemente;
- telechargement avec cache et reprise partielle implemente;
- README et requirements dedies ajoutes.

Livrable atteint: outil executable hors workflow.

### Phase 2 - Factorisation package: fait, a durcir

- client stable deplace dans
  `hydromodpy/data/variables/dem/apis/geoplateforme_download.py`;
- logique produit deplacee dans
  `hydromodpy/data/variables/dem/apis/ign_dem_fr.py`;
- CLI adapte pour importer ces fonctions;
- tests unitaires package ajoutes.

Reste a durcir: couverture de retry, cas d'encodage d'URL, fixtures Atom plus
representatives, tests directs du CLI.

### Phase 3 - Integration DEM manager: partiel avance

Fait:

- `ign_bdalti` accepte `regions` et `departments`;
- AURA est resolue en 12 departements;
- les departements sont transmis a `fetch_bdalti(...)`;
- le comportement historique `ign_bdalti` est conserve.
- `ign_geoplateforme_dem` est ajoute dans `DemConfig`;
- `DemManager` appelle `fetch_ign_dem(...)`;
- le bootstrap `resolver.py` reconnait `ign_geoplateforme_dem`;
- BD ALTI 25 m ASC dispose d'un flux telechargement/extraction/fusion/crop
  vers GeoTIFF.

Reste:

- renforcer les tests d'assemblage raster avec des fixtures locales plus proches
  des archives IGN reelles;
- propager les metadonnees dataset/resolution dans le catalogue HydroModPy, en
  plus du sidecar `processed/*.json` deja ecrit a cote du GeoTIFF assemble;
- etendre le flux a RGE ALTI ou le garder comme telechargement brut uniquement.

Livrable atteint pour BD ALTI 25 m ASC. RGE ALTI est maintenant refuse
explicitement dans `fetch_ign_dem(...)` avec un message indiquant d'utiliser le
telechargement brut tant que l'assemblage raster n'est pas implemente.

### Phase 4 - Application AURA/site_selection: partiel

Fait:

- `[data.dem]` est present dans les exemples AURA;
- `regions = ["Auvergne-Rhone-Alpes"]` est valide et canonicalise;
- les 12 departements AURA sont resolus dans les tests;
- les workflows de fixture produisent les artefacts site_selection;
- les exemples courts Bretagne et AURA utilisent maintenant
  `source = "ign_geoplateforme_dem"` pour passer par le client dynamique;
- le rapport HTML signale explicitement les entrees `fixture` ou `synthetic`;
- un exemple AURA hydrometrique reel borne a cinq stations Hub'Eau est ajoute
  dans `configs/auvergne_rhone_alpes_hydrometry_preview.toml`;
- AURA `area_only` produit un rapport avec fond DEM regional reel issu du cache
  Geoplateforme, mais ses bassins restent volontairement synthetiques;
- AURA `hydrometry_preview` produit un rapport a partir de stations Hub'Eau
  reelles et du DEM regional Geoplateforme.

Reste:

- transformer l'exemple AURA hydrometrique complet en run borne ou pagine pour
  eviter de delimiter plusieurs centaines d'exutoires dans un exemple courant;
- traiter les 24 stations Hub'Eau renvoyees hors emprise AURA lors du run
  complet comme un diagnostic explicite dans le rapport ou dans le filtrage;
- remplacer progressivement les limites de fixture par une selection observee
  reproductible et suffisamment courte pour CI/verification locale.

Livrable atteint pour les rapports de controle Bretagne et AURA avec fond DEM
reel issu de Geoplateforme. Le run AURA hydrometrique complet reste trop lourd
pour etre l'exemple par defaut.

### Phase 5 - Remplacement progressif de la table statique: partiel

Fait:

- decouverte Geoplateforme dynamique disponible pour BD ALTI et RGE ALTI;
- source `ign_geoplateforme_dem` disponible dans la configuration et le
  manager pour BD ALTI 25 m ASC;
- `_BDALTI_ARCHIVES` conserve comme fallback documente pour BD ALTI 25 m ASC.

Reste:

- basculer ou aliaser progressivement `ign_bdalti` vers le nouveau chemin si
  l'on veut remplacer le comportement historique;
- garder `_BDALTI_ARCHIVES` seulement comme fallback de secours;
- supprimer ou reduire le fallback quand la fiabilite API aura ete confirmee;
- verifier le comportement sur RGE ALTI et archives fragmentees.

## Validation complementaire du 2026-05-23

Changements ajoutes:

- cache `processed/` durci par sidecar JSON: dataset, resolution, format, CRS,
  bbox et departements sont verifies avant reutilisation;
- adoption automatique des anciens GeoTIFFs valides sans sidecar;
- test unitaire du cache traite dans
  `tests/unit/data_managers/test_geoplateforme_dem_downloader.py`;
- tests reseau optionnels dans
  `tests/integration/test_geoplateforme_dem_network.py`, actives par
  `HMP_RUN_IGN_NETWORK_TESTS=1`; le telechargement reel d'une archive demande
  en plus `HMP_RUN_IGN_DOWNLOAD_TESTS=1`;
- la decouverte dynamique Geoplateforme peut ne pas exposer de fichier BD ALTI
  pour un departement au moment du test; dans ce cas le test reseau se marque
  `skip` et le chemin de production continue d'utiliser le fallback BD ALTI.

Commandes validees:

```powershell
python -m pytest -o addopts="" `
  tests/unit/data_managers/test_geoplateforme_dem_downloader.py `
  tests/unit/data_managers/test_dem_manager.py `
  tests/unit/site_selection/test_data_layers.py `
  tests/unit/site_selection/test_synthetic_spatial_review.py `
  tests/unit/site_selection/test_example_configs.py `
  -m fast
```

Resultat observe:

```text
28 passed
```

Test reseau dry-run:

```powershell
$env:HMP_RUN_IGN_NETWORK_TESTS = "1"
python -m pytest -o addopts="" tests/integration/test_geoplateforme_dem_network.py -m network -q
```

Resultat observe dans l'environnement courant:

```text
2 skipped
```

Les deux skips sont attendus ici: la decouverte dynamique n'a pas retourne de
fichier BD ALTI pour `D029`, et le test de telechargement reel est protege par
`HMP_RUN_IGN_DOWNLOAD_TESTS=1`.

## Decisions recommandees

1. Oui, HydroModPy doit savoir recuperer les departements necessaires
   automatiquement si le territoire est une region ou une bbox.
2. Le CLI autonome est utile, mais il doit etre place dans `tools/`, pas dans
   `site_selection`.
3. Le code reutilisable doit vivre dans `hydromodpy/data/variables/dem/apis/`.
4. `site_selection` ne doit jamais connaitre les endpoints Geoplateforme.
5. Pour AURA, commencer par BD ALTI/RGE ALTI 5 m pour le fond regional; ne pas
   lancer RGE ALTI 1 m sur toute la region sans une demande explicite.
