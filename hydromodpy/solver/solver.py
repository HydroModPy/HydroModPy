
# -*- coding: utf-8 -*-
"""
Classe abstraite pour les solveurs HydroModPy (Modflow, Modpath, Mt3dms).
Regroupe les signatures et attributs communs pour uniformiser l'API.
"""

from abc import ABC, abstractmethod

class Solver(ABC):
	"""
	Classe abstraite pour les solveurs HydroModPy.
	Définit l'interface commune pour tous les solveurs (prétraitement, calcul, post-traitement).
	"""

	@abstractmethod
	def pre_processing(self):
		"""
		Prétraitement : préparation des fichiers d'entrée, initialisation des structures de données, etc.
		"""
		pass

	@abstractmethod
	def processing(self, write_model: bool = True, run_model: bool = False, **kwargs):
		"""
		Lancement du solveur : écriture des fichiers, exécution du modèle, etc.

		Parameters
		----------
		write_model : bool
			Écrire les fichiers d'entrée du modèle.
		run_model : bool
			Exécuter le solveur.
		kwargs : dict
			Paramètres additionnels pour certains solveurs (ex: verbose, link_mt3dms).
		Returns
		-------
		success_model : bool
			Indique si la simulation s'est terminée correctement.
		"""
		pass

	@abstractmethod
	def post_processing(self, *args, **kwargs):
		"""
		Post-traitement : analyse et export des résultats, figures, rasters, etc.

		Parameters
		----------
		args, kwargs :
			Paramètres spécifiques selon le solveur et le type de post-traitement.
		"""
		pass