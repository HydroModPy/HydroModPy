from groundwater_flow import vizualisation
vtk.VTK(BV, model_name)
visu = vizualisation.Vizualisation(BV, model_name)
visu.visual3D(interactive=false, object_list=['grid','watertable','watertable_depth'], view='south-west')
