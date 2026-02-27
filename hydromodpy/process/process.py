
# -*- coding: utf-8 -*-
"""
Classe abstraite pour le traitement des processus HydroModPy.
Regroupe les paramètres, variables, conditions initiales, conditions limites, et termes puits/sources.
"""

from abc import ABC, abstractmethod
from pydantic import BaseModel, Field

class Parameter(BaseModel):
    id: str = Field(..., description="id of the parameter (ex: K, R, Sy, etc.)")
    value: float = Field(..., description="Value of the parameter")
    description: str = Field('', description="Description of the parameter")
    units: str = Field('', description="Units of the parameter")
    field_type: str = Field('homogeneous', description="Type of the field (e.g., 'homogeneous', 'heterogeneous')")
    link_data: list = Field(default_factory=list, description="List of the id of the data linked to this parameter")
    parameters: dict = Field(default_factory=dict, description="Dictionary of the parameters linked to this parameter")
      
    def update_value(self, new_value: float):
        self.value = new_value
    
    def add_parameter(self, parameter: 'Parameter'):
        self.parameters[parameter.id] = parameter

class Variable(BaseModel):
	id: str = Field(..., description="id of the variable (ex: h, etc.)")
	value: float = Field(..., description="Value of the variable")
	description: str = Field('', description="Description of the variable")
	units: str = Field('', description="Units of the variable")

class InitialCondition(BaseModel):
	id: str = Field(..., description="id of the initial condition (ex: h0, etc.)")
	value: float = Field(..., description="Value of the initial condition")
	description: str = Field('', description="Description of the initial condition")
	units: str = Field('', description="Units of the initial condition")

class BoundaryCondition(BaseModel):
	id: str = Field(..., description="id of the boundary condition (ex: h_BC, etc.)")
	value: float = Field(..., description="Value of the boundary condition")
	description: str = Field('', description="Description of the boundary condition")
	units: str = Field('', description="Units of the boundary condition")
	type: str = Field('Dirichlet', description="Type of the boundary condition (e.g., 'Dirichlet', 'Neumann', 'Cauchy')")
	data_value: bool = Field(False, description="If True, boundary condition value is sourced from data")

class SinkSource(BaseModel):
	id: str = Field(..., description="id of the sink/source (ex: Q_well, etc.)")
	value: float = Field(..., description="Value of the sink/source")
	description: str = Field('', description="Description of the sink/source")
	units: str = Field('', description="Units of the sink/source")
	link_data: list = Field(default_factory=list, description="List of the id of the data linked to this parameter")

class Process(ABC):
	"""
	abstract class for HydroModPy processes.
    Defines the common structure for all processes (parameters, variables, initial conditions, boundary conditions, sinks/sources).
	"""

	def __init__(self):
		self.parameters = {}
		self.variables = {}
		self.initial_conditions = {}
		self.boundary_conditions = {}
		self.sinks_sources = {}
		# Les sous-classes peuvent traiter kwargs pour leurs besoins spécifiques

	@abstractmethod
	def set_parameters(self, parameters: dict):
		"""
		Définir ou mettre à jour les paramètres du modèle.
		"""
		pass
	
	#@abstractmethod
	def add_parameter(self, parameter: Parameter):
		"""
 		Ajouter un paramètre au processus.
 		Args:
            parameter (Parameter): Instance de la classe Parameter à ajouter.
        """
		self.parameters[parameter.id] = parameter


	@abstractmethod
	def set_variables(self, variables: dict):
		"""
		Définir ou mettre à jour les variables d'état.
		"""
		pass

	#@abstractmethod
	def add_variable(self, variable: Variable):
		"""
 		Ajouter une variable au processus.
 		Args:
			variable (Variable): Instance de la classe Variable à ajouter.
		"""
		self.variables[variable.id] = variable

	@abstractmethod
	def set_initial_conditions(self, initial_conditions: dict):
		"""
		Définir ou mettre à jour les conditions initiales.
		"""
		pass

	#@abstractmethod
	def add_initial_condition(self, initial_condition: InitialCondition):
		"""
 		Ajouter une condition initiale au processus.
 		Args:
			initial_condition (InitialCondition): Instance de la classe InitialCondition à ajouter.
		"""
		self.initial_conditions[initial_condition.id] = initial_condition

	@abstractmethod
	def set_boundary_conditions(self, boundary_conditions: dict):
		"""
		Définir ou mettre à jour les conditions limites.
		"""
		pass

	#@abstractmethod
	def add_boundary_condition(self, boundary_condition: BoundaryCondition):
		"""
 		Ajouter une condition limite au processus.
 		Args:
			boundary_condition (BoundaryCondition): Instance de la classe BoundaryCondition à ajouter.
		"""
		self.boundary_conditions[boundary_condition.id] = boundary_condition

	@abstractmethod
	def set_sinks_sources(self, sinks_sources: dict):
		"""
		Définir ou mettre à jour les termes puits/sources.
		"""
		pass
	
	#@abstractmethod
	def add_sink_source(self, sink_source: SinkSource):
		"""
 		Ajouter un terme puits/source au processus.
 		Args:
			sink_source (SinkSource): Instance de la classe SinkSource à ajouter.
		"""
		self.sinks_sources[sink_source.id] = sink_source
    
	

        
