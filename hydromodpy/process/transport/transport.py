# -*- coding: utf-8 -*-

from hydromodpy.process.process import Process

class Transport(Process):
    def __init__(self):
        super().__init__()

    def set_parameters(self, parameters: dict):
        self.parameters.update(parameters)

    def set_variables(self, variables: dict):
        self.variables.update(variables)

    def set_initial_conditions(self, initial_conditions: dict):
        self.initial_conditions.update(initial_conditions)

    def set_boundary_conditions(self, boundary_conditions: dict):
        self.boundary_conditions.update(boundary_conditions)

    def set_sinks_sources(self, sinks_sources: dict):
        self.sinks_sources.update(sinks_sources)

