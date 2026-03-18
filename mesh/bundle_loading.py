"""Chargement du bundle exporte pour la distribution des maillages.

Ce module ne s'occupe ni de la validation du TOML, ni du rendu graphique.
Il lit uniquement le lecteur embarque dans le bundle, puis reconstruit
l'objet de travail utilise par le reste du sous-package.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import cast

from mesh.config import load_toml_config
from mesh.models import (
    DEFAULT_TOML_SECTION,
    MeshBundleLike,
    MeshVisualizationData,
    VisualizationConfig,
)


def _load_bundle_reader_module(bundle_dir: Path) -> ModuleType:
    """Charge dynamiquement le module `reader.py` present dans le bundle.

    Pourquoi un chargement dynamique ?

    Parce que le lecteur doit voyager avec les donnees exportees. Ainsi, un
    bundle peut etre distribue avec son propre lecteur, sans exiger l'ensemble
    du package `hydromodpy`.
    """

    reader_path = (bundle_dir / "reader.py").resolve()
    if not reader_path.exists():
        raise FileNotFoundError(
            "Fichier lecteur du bundle introuvable : "
            f"{reader_path}. Le dossier bundle doit contenir `reader.py`."
        )

    digest = hashlib.sha1(str(reader_path).encode("utf-8")).hexdigest()
    module_name = f"_distribution_mesh_reader_{digest}"

    # On reutilise le module deja charge si on relit plusieurs fois le meme
    # bundle dans une meme session Python.
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, reader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de preparer l'import de {reader_path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _get_bundle_reader(
    bundle_dir: Path,
) -> Callable[[str | Path], MeshBundleLike]:
    """Retourne la fonction de lecture exposee par `reader.py`.

    Le contrat attendu est simple : le fichier `reader.py` doit definir une
    fonction `load_catchment_mesh_bundle(bundle_dir)` qui retourne un objet
    compatible avec `MeshBundleLike`.
    """

    module = _load_bundle_reader_module(bundle_dir)
    reader_function = getattr(module, "load_catchment_mesh_bundle", None)
    if not callable(reader_function):
        raise AttributeError(
            f"Le lecteur {bundle_dir / 'reader.py'} doit definir "
            "`load_catchment_mesh_bundle(...)`."
        )
    return cast(Callable[[str | Path], MeshBundleLike], reader_function)


def load_visualization_data(
    config: VisualizationConfig,
) -> MeshVisualizationData:
    """Charge le bundle et assemble l'objet de travail final.

    Cette fonction est le point de jonction entre :
    - la configuration validee ;
    - le bundle exporte sur disque.
    """

    bundle_reader = _get_bundle_reader(config.bundle_dir)
    mesh = bundle_reader(config.bundle_dir)
    return MeshVisualizationData(mesh=mesh, config=config)


def load_visualization_data_from_toml(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
) -> MeshVisualizationData:
    """Enchaine lecture du TOML puis lecture du bundle.

    Cette fonction est utile pour les scripts et pour les usages interactifs
    ou l'on veut passer directement d'un chemin TOML a l'objet de travail final.
    """

    config = load_toml_config(toml_path, section=section)
    return load_visualization_data(config)


__all__ = [
    "load_visualization_data",
    "load_visualization_data_from_toml",
]

