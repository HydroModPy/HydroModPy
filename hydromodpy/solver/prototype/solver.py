# -*- coding: utf-8 -*-
"""
Classe abstraite pour les solveurs HydroModPy (Modflow, Modpath, Mt3dms).
Regroupe les signatures et attributs communs pour uniformiser l'API.
"""

from abc import ABC, abstractmethod


class Solver(ABC):
    """
    Classe abstraite pour les solveurs HydroModPy.
    DÃ©finit l'interface commune pour tous les solveurs (prÃ©traitement, calcul, post-traitement).
    """

    @abstractmethod
    def pre_processing(self):
        """
        PrÃ©traitement : prÃ©paration des fichiers d'entrÃ©e, initialisation des structures de donnÃ©es, etc.
        """
        pass

    @abstractmethod
    def processing(self, write_model: bool = True, run_model: bool = False, **kwargs):
        """
        Lancement du solveur : Ã©criture des fichiers, exÃ©cution du modÃ¨le, etc.

        Parameters
        ----------
        write_model : bool
            Ã‰crire les fichiers d'entrÃ©e du modÃ¨le.
        run_model : bool
            ExÃ©cuter le solveur.
        kwargs : dict
            ParamÃ¨tres additionnels pour certains solveurs (ex: verbose, link_mt3dms).
        Returns
        -------
        success_model : bool
            Indique si la simulation s'est terminÃ©e correctement.
        """
        pass

    @abstractmethod
    def post_processing(self, *args, **kwargs):
        """
        Post-traitement : analyse et export des rÃ©sultats, figures, rasters, etc.

        Parameters
        ----------
        args, kwargs :
            ParamÃ¨tres spÃ©cifiques selon le solveur et le type de post-traitement.
        """
        pass

