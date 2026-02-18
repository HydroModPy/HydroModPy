
# -*- coding: utf-8 -*-

from hydromodpy.process.process import Process, Parameter, Variable, InitialCondition, BoundaryCondition, SinkSource

class Flow(Process):
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

	def set_sinks_sources(self, wells_sources: dict):
		self.sinks_sources.update(wells_sources)
  
if __name__ == "__main__":
    test = Flow()
    K = Parameter(id='K', value=1e-5, description='Hydraulic conductivity', units='m/s', field_type='homogeneous')
    Sy = Parameter(id='Sy', value=0.1, description='Specific yield', units='-', field_type='homogeneous')
    h = Variable(id='h', value=0, description='Hydraulic head', units='m')
    q = Variable(id='q', value=0, description='Flow rate', units='m3/s')
    h0 = InitialCondition(id='h0', value=10, description='Initial hydraulic head', units='m')
    h_ocean = BoundaryCondition(id='h_ocean', value=0, description='Ocean boundary condition', units='m', type='Dirichlet')
    drain = BoundaryCondition(id='drain', value=0, description='Drain boundary condition', units='m', type='Cauchy')
    recharge = SinkSource(id='R', value=1e-8, description='Recharge rate', units='m/s')
    well1 = SinkSource(id='W1', value=-1e-4, description='Pumping well', units='m3/s')
    test.set_parameters({K.id: K})
    test.add_parameter(Sy)
    test.set_variables({h.id: h, q.id: q})
    test.set_initial_conditions({h0.id: h0})
    test.set_boundary_conditions({h_ocean.id: h_ocean, drain.id: drain})
    test.set_sinks_sources({well1.id: well1})
    
