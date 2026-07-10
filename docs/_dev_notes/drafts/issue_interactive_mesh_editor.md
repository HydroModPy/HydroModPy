## Idea

Right now HydroModUi is just a form. You set the mesh and the features by typing numbers, blind. I want an interactive editor instead: a map where you build the mesh and place things by hand, and the UI writes the config for you.

What you should be able to do:

- pick the DEM, move sliders for the mesh params and see the mesh change live
- draw or brush the zones to refine (streams, lakes)
- add a well by clicking on the map, typing coordinates, or dropping a shapefile, then fill its setup
- draw an HFB or a boundary condition directly on the cell faces
- change the role of a cell, for example turn a wrong lake cell back to a standard cell

The main rule: you never edit the mesh by hand. Everything you draw is stored as config that feeds the mesher, so the mesh can always be rebuilt and the run stays reproducible.
