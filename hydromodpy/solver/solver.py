
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

	def __init__(self, geographic: object, model_modflow: object = None, model_folder: str = 'HydroModPy_outputs', model_name: str = 'Default', **kwargs):
		"""
		Initialisation commune à tous les solveurs.

		Parameters
		----------
		geographic : object
			Objet géographique HydroModPy.
		model_modflow : object, optional
			Objet Modflow parent (pour les solveurs couplés).
		model_folder : str, optional
			Dossier de travail du modèle.
		model_name : str, optional
			Nom du modèle.
		kwargs : dict
			Paramètres spécifiques au solveur.
		"""
		self.geographic = geographic
		self.model_modflow = model_modflow
		self.model_folder = model_folder
		self.model_name = model_name
		self.full_path = None # Peut être défini dans les sous-classes
		# Les sous-classes peuvent traiter kwargs pour leurs besoins spécifiques

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

	# Optionnel : méthode de filtrage/traitement avancé (présente dans Modpath)
	def filt_processing(self, *args, **kwargs):
		"""
		(Optionnel) Traitement ou filtrage avancé des résultats.
		À surcharger dans les solveurs qui le nécessitent.
		"""
		raise NotImplementedError("Ce solveur n'implémente pas filt_processing.")
