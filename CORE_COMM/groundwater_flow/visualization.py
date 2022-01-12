import vedo
import numpy as np
import os


class Visualization():
    def __init__(self, watershed, modelname):
        self.watershed = watershed
        self.modelname = modelname
    
    def visual3D(self, object_list = ['grid', 'watertable'] , view = 'south-west', 
                 interactive = False, lines=100, z_scale=20):
        """
        3Dvisual shows the vtk objects from an interactive windows or a 
        screenshot.

        Parameters
        ----------
        object_list : list of str, optional
            list of visualisation.
            possible options: grid, watertable, watertable_depth, pathlines
            The default is ['grid', 'watertable'].
        view : str, optional
            position of view to see the 3D visual.
            possible options: north, north-east, east, south-east, south,
            south-west, west, north-west
            The default is 'south-west'.
        interactive : bool, optional
            activate the interactive window, if True the figure doesn't save. 
            The default is False.
        lines : int, optional
            the number of random pathlines displayed
        """
        plt = vedo.Plotter(N=len(object_list), axes=dict(xtitle='m', ytitle='m', ztitle='m', 
                                          yzGrid=False), bg2='lb', size=(1500,1080))
        # load files
        contour = vedo.Mesh(os.path.join(self.watershed.simulations_folder, self.modelname, '_extraction', 'VTK','VTU_watershed_contour.vtk'))
        contour.scale([1,1,z_scale])
        contour.color('k').lw(5)
        contour.renderLinesAsTubes(value=True)
        
        try:
            stream = vedo.Mesh(os.path.join(self.watershed.simulations_folder, self.modelname, '_extraction', 'VTK','VTU_streams.vtk'))
            stream.scale([1,1,z_scale])
            stream.color('b').lw(5)
            stream.renderLinesAsTubes(value=True)
        except:
            pass
        
        try:
            grid = os.path.join(self.watershed.simulations_folder, self.modelname, '_extraction', 'VTK','VTU_Grid.vtu')
            grid_mesh = vedo.Mesh(grid) #grid_mesh
            grid_wireframe = vedo.Mesh(grid).wireframe() #grid_wireframe
            grid_wireframe.color('white')
            grid_wireframe.scale([1,1,z_scale])
            grid_wireframe.alpha(0.2)
            plt += grid_wireframe.flag()
            
            zvals = grid_mesh.points()[:, 2]
            grid_mesh.addElevationScalars(lowPoint=(0,0,min(zvals)),highPoint=(0,0,max(zvals)), vrange=(min(zvals), max(zvals)))
            grid_mesh.cmap('terrain',zvals, vmin=min(zvals))
            grid_mesh.addScalarBar(pos=(0.1,0.8), title='Topography elevation (m)', horizontal=True, titleFontSize=20)
            grid_mesh.scale([1,1,z_scale])
            plt += grid_mesh.flag()     
            plt += grid_mesh.isolines(5).lw(1).c('k')
        except:
            print("VTK grid doesn't exist")
            
        try: 
            watertable = os.path.join(self.watershed.simulations_folder, self.modelname, '_extraction', 'VTK','VTU_Watertable_0.vtu')
            watertable_elev = vedo.Mesh(watertable) # 1 Elevation
            watertable_depth = vedo.Mesh(watertable) # 3 Depth
            watertable_blue = vedo.Mesh(watertable) # 4 blue
            
            zvals = watertable_elev.points()[:, 2]
            watertable_elev.cmap('jet',zvals, vmin=min(zvals))
            watertable_elev.addScalarBar(pos=(0.1,0.8), title='Watertable elevation (m)', horizontal=True, titleFontSize=20)
            watertable_elev.scale([1,1,z_scale])
            plt += watertable_elev.flag() 
            
            watertable_depth.mapCellsToPoints()
            watertable_depth.cmap('coolwarm_r',input_array='Drawdown', vmin=0, vmax=2)
            watertable_depth.addScalarBar(pos=(0.1,0.8), title='Watertable depth (m)', horizontal=True, titleFontSize=20)
            watertable_depth.scale([1,1,z_scale])
            plt += watertable_depth.flag()
            
            watertable_blue.color('b')
            watertable_blue.alpha(0.2)
            watertable_blue.scale([1,1,z_scale])
            watertable_blue.legend('Watertable')
            plt += watertable_blue.flag()  
        except:
            print("VTK watertable doesn't exist")
        try:
            pathlines = os.path.join(self.watershed.simulations_folder, self.modelname, '_extraction', 'VTK','VTU_Pathlines.vtk')
            pathlines_mesh = vedo.Mesh(pathlines) #5
            
            #Pathlines
            vmax = max(pathlines_mesh.pointdata['Time'])
            pathlines_mesh.cmap('hot',input_array='Time',vmax=vmax/50).lw(5)
            pathlines_mesh.addScalarBar(pos=(0.1,0.8), title='Time (d)', horizontal=True, titleFontSize=20)
            pathlines_mesh.scale([1,1,z_scale])
            pathlines_mesh.renderLinesAsTubes(value=True)
            pathlines_mesh.legend('Pathlines')
            n = lines
            x = pathlines_mesh.lines()
            length = max(map(len, x))
            y=np.array([xi+[None]*(length-len(xi)) for xi in x])
            number_of_rows = y.shape[0]
            random_indices = np.random.choice(number_of_rows, size=len(x)-n, replace=False)
            y1 = y[random_indices, :].flatten()
            pts =  y1[y1 != np.array(None)]
            pathlines_mesh.deletePoints(pts)
        except:
            print("VTK pathlines doesn't exist")

        #View
        xs = max(watertable_elev.points()[:, 0]) - min(watertable_elev.points()[:, 0])
        ys = max(watertable_elev.points()[:, 1]) - min(watertable_elev.points()[:, 1])
        if view == 'north':
            pos = (min(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'north-east':
            pos = (max(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'east':
            pos = (max(watertable_elev.points()[:, 0])+ xs ,min(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'south-east':
            pos = (max(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])- ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'south':
            pos = (min(watertable_elev.points()[:, 0])+ xs ,min(watertable_elev.points()[:,1])- ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'south-west':
            pos = (min(watertable_elev.points()[:, 0])- xs ,min(watertable_elev.points()[:,1])- ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'west':
            pos = (min(watertable_elev.points()[:, 0])- xs ,min(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'north-west':
            pos = (min(watertable_elev.points()[:, 0])- xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*10)
        if view == 'custom':
            pos = (max(watertable_elev.points()[:, 0])+ 2*xs ,max(watertable_elev.points()[:,1])+ 2*ys,max(watertable_elev.points()[:, 2])*4)
        print(pos)
        cam = dict(pos = pos)
        
        for i in range (0,len(object_list)):
            obj = object_list[i]
            if obj == 'grid':
                print(obj,i)
                plt.show(grid_mesh,contour,stream, at=i, axes = 13)
            if obj == 'watertable':
                print(obj,i)
                plt.show(grid_wireframe,contour,stream, watertable_elev,camera=cam, viewup ='z', at=i)
            if obj == 'watertable_depth':
                print(obj,i)
                plt.show(grid_wireframe,contour,stream, watertable_depth,camera=cam, viewup ='z', at=i)
            if obj == 'pathlines':
                print(obj,i)
                plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh,camera=cam, viewup ='z', at=i)      
        
        
        if interactive == True:
            plt.show(interactive=1).close()
        else:
            plt.screenshot(os.path.join(self.watershed.simulations_folder, self.modelname, '_figure','3Dvisual')).close()

