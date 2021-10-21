from vedo import *
from vedo.applications import Browser, FreeHandCutPlotter
import numpy as np

file = 'C:/Users/alexa/Dropbox/HP_Article_Data/Data/output_files/VTU_Grid.vtu'
mesh2 = Mesh(file)
mesh0 = mesh2.clone().wireframe()
file1 = 'C:/Users/alexa/Dropbox/HP_Article_Data/Data/output_files/VTU_WaterTable_0.vtu'
mesh1 = Mesh(file1)
mesh3 = mesh1.clone()
mesh4 = mesh1.clone()
file2 = 'C:/Users/alexa/Dropbox/HP_Article_Data/Data/output_files/VTU_Pathlines.vtk'
mesh5 = Mesh(file2)

# Create a plotter and add landSurface to it
plt = Plotter(N=4, axes=dict(xtitle='m', ytitle='m', ztitle='m', yzGrid=False),
              bg2='lb', size=(1500,1080)) # screen size

# Watertable
zvals = mesh1.points()[:, 2]
mesh1.addElevationScalars(lowPoint=(0,0,-30),highPoint=(0,0,100), vrange=(-30, 100))
mesh1.cmap('jet',zvals, vmin=min(zvals))
mesh1.addScalarBar(pos=(0.1,0.8), title='Watertable elevation (m)', horizontal=True, titleFontSize=20)
#mesh1.color('b')
mesh1.scale([1,1,20])
plt += mesh1.flag()   

mesh3.mapCellsToPoints()
mesh3.cmap('coolwarm_r',input_array='Drawdown', vmin=0, vmax=2)
mesh3.addScalarBar(pos=(0.1,0.8), title='Watertable depth (m)', horizontal=True, titleFontSize=20)
mesh3.scale([1,1,20])
plt += mesh3.flag()

mesh4.color('b')
mesh4.alpha(0.2)
mesh4.scale([1,1,20])
mesh4.legend('Watertable')
plt += mesh4.flag()              

# Grid
mesh0.color('white')
mesh0.scale([1,1,20])
mesh0.alpha(0.2)
plt += mesh0.flag()     

#Grid
mesh2.addElevationScalars(lowPoint=(0,0,-30),highPoint=(0,0,100), vrange=(-30, 100))
zvals = mesh2.points()[:, 2]
mesh2.cmap('terrain',zvals, vmin=-30)
mesh2.addScalarBar(pos=(0.1,0.8), title='Topography elevation (m)', horizontal=True, titleFontSize=20)
mesh2.scale([1,1,20])
plt += mesh2.flag()     
plt += mesh2.isolines(5).lw(1).c('k')

#Pathlines
vmax = max(mesh5.pointdata['Time'])
mesh5.cmap('hot',input_array='Time',vmax=vmax/50).lw(5)
mesh5.addScalarBar(pos=(0.1,0.8), title='Time (d)', horizontal=True, titleFontSize=20)
mesh5.scale([1,1,20],)
mesh5.renderLinesAsTubes(value=True)
mesh5.legend('Pathlines')

n = 100
x = mesh5.lines()
length = max(map(len, x))
y=np.array([xi+[None]*(length-len(xi)) for xi in x])
number_of_rows = y.shape[0]
random_indices = np.random.choice(number_of_rows, size=len(x)-n, replace=False)
y1 = y[random_indices, :].flatten()
pts =  y1[y1 != np.array(None)]
mesh5.deletePoints(pts)

# faire les vues
xs = max(mesh1.points()[:, 0]) - min(mesh1.points()[:, 0])
ys = max(mesh1.points()[:, 1]) - min(mesh1.points()[:, 1])
zs = max(mesh1.points()[:, 2]) - min(mesh1.points()[:, 2])
pos = (min(mesh1.points()[:, 0])- xs ,min(mesh1.points()[:,1])- ys,max(mesh1.points()[:, 2])*10)
print(pos)
cam = dict(pos = pos)

lbox = LegendBox((mesh4, mesh5), alpha=0.2)
plt.show(mesh2, at=0, axes=True)
plt.show(mesh0, mesh1, at=1)
plt.show(mesh4, mesh5,lbox, at=2)
plt.show(mesh0, mesh3, at=3, camera=cam, viewup ='z').screenshot('image.png')

plt.close()
