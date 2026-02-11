from __future__ import annotations

import logging
import os
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from src.tools import folder_root, toolbox

from .config import ProjectConfig


@dataclass
class RuntimeContext:
    root_dir: str
    out_path: str
    data_path: str
    log_manager: toolbox.LogManager


def _configure_warnings() -> None:
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", message=".*pkg_resources.*")
    warnings.filterwarnings("ignore", message=".*declare_namespace.*")


def _resolve_repo_root() -> str:
    return str(Path(__file__).resolve().parents[3])


def _resolve_output_path(config: ProjectConfig) -> str:
    if config.paths.out_path_mode == "env":
        return folder_root.root_folder_results()
    return config.paths.fixed_out_path


def configure_runtime(config: ProjectConfig) -> RuntimeContext:
    _configure_warnings()

    root_dir = _resolve_repo_root()
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    if os.getcwd() != root_dir:
        os.chdir(root_dir)
        logging.info("Répertoire racine défini : %s", root_dir)

    log_manager = toolbox.LogManager(mode=config.runtime.log_mode)

    out_path = _resolve_output_path(config)
    os.makedirs(out_path, exist_ok=True)

    data_path = os.path.join(out_path, config.paths.data_subdir)
    os.makedirs(data_path, exist_ok=True)

    if not os.listdir(data_path):
        raise FileNotFoundError(
            f"Le dossier {data_path} est vide. "
            "Télécharge les données d'entrée avant de lancer la simulation."
        )

    logging.info("Dossier de sortie : %s", out_path)
    logging.info("Dossier de données : %s", data_path)

    return RuntimeContext(
        root_dir=root_dir,
        out_path=out_path,
        data_path=data_path,
        log_manager=log_manager,
    )
