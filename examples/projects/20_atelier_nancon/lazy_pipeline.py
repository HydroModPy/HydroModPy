# Piloter un projet etape par etape au lieu d'un seul hmp run.
#
# Project.lazy valide la config mais ne lance rien. On appelle ensuite
# les etapes du pipeline a la main et on inspecte, ou on modifie, le
# projet entre chaque. Utile pour prototyper et montrer ce que fait
# hmp run en interne.
#
#   python lazy_pipeline.py

from pathlib import Path

from hydromodpy import Project
from hydromodpy.config import HydroModPyConfig

here = Path(__file__).resolve().parent

# Charger la config comme objet pour pouvoir l'editer avant de lancer.
cfg = HydroModPyConfig.from_toml(here / "project.toml")

# Lire un parametre, puis le changer. Ici on divise K par deux.
k_field = cfg.flow.param["K"].field
print("K du TOML :", k_field.value, k_field.unit)
k_field.value = k_field.value / 2.0
print("K apres edition :", k_field.value)

# En faire un run permanent rapide pour que la demo reste courte.
cfg.flow.flow_regime = "steady"

# Construire un projet lazy depuis la config editee. headless = pas de
# popups.
project = Project.lazy(cfg, headless=True)

# Etape 1 : workspace et catalog.
project.setup_workspace()

# Etape 2 : delimiter le bassin depuis le DEM et l'exutoire.
project.build_geographic()
print("bassin delimite :", type(project.geographic).__name__)

# Etape 3 : charger les donnees de forcage, puis inspecter ce qui a ete
# charge.
project.load_data()
print("donnees chargees :", sorted(project.data_loaded))

# Etape 4 : lancer le solver sur l'etat qu'on vient de preparer a la main.
run = project.run()
head = run.field("head", timestep=-1)
print(
    "run :", run.name, "| mailles de charge :", head.size, f"| moyenne {float(head.mean()):.2f} m"
)

project.close()
