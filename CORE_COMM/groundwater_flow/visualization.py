import vedo
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib_scalebar.scalebar import ScaleBar
from matplotlib.collections import LineCollection
import rasterio
from rasterio.plot import show
import geopandas as gpd

import flopy
import os
import contextily as cx

from tools import toolbox


class Visualization():
    def __init__(self, watershed, modelname):
        self.watershed = watershed
        self.modelname = modelname
    
    def visual3D(self, object_list = ['grid', 'watertable'] , view = 'south-west', 
                 interactive = False, lines=100, z_scale=20, render=1, cscale = 'default', cmin = -1, cmax = 1, cloc=(0.65,0.75) , size=(1500,1080)):
        """
        3Dvisual shows the vtk objects from an interactive windows or a 
        screenshot.

        Parameters
        ----------
        object_list : list of str, optional
            list of visualisation.
            possible options: grid, watertable, watertable_depth, pathlines, flux, acc_flux
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
        vedo.settings.screeshotScale = render
        plt = vedo.Plotter(N=len(object_list), axes=dict(xtitle='m', ytitle='m', ztitle='m', 
                                          yzGrid=False), bg2='lb', size=size)

        # load files
        contour = vedo.Mesh(os.path.join(self.watershed.simulations_folder, self.modelname, '_watershed', 'VTK','VTU_watershed_contour.vtk'))
        contour.scale([1,1,z_scale])
        contour.color('k').lw(2)
        contour.renderLinesAsTubes(value=True)
        
        try:
            stream = vedo.Mesh(os.path.join(self.watershed.simulations_folder, self.modelname, '_watershed', 'VTK','VTU_streams.vtk'))
            stream.scale([1,1,z_scale])
            stream.color('b').lw(5)
            stream.renderLinesAsTubes(value=True)
        except:
            stream=None
            pass
        
        try:
            grid = os.path.join(self.watershed.simulations_folder, self.modelname, '_watershed', 'VTK','VTU_Grid.vtu')
            grid_mesh = vedo.Mesh(grid) #grid_mesh
            grid_wireframe = vedo.Mesh(grid).wireframe() #grid_wireframe
            grid_wireframe.color('white')
            grid_wireframe.scale([1,1,z_scale])
            grid_wireframe.alpha(0.2)
            plt += grid_wireframe.flag()
            
            zvals = grid_mesh.points()[:, 2]
            grid_mesh.addElevationScalars(lowPoint=(0,0,min(zvals)),highPoint=(0,0,max(zvals)), vrange=(min(zvals), max(zvals)))
            grid_mesh.cmap('terrain',zvals, vmin=min(zvals))
            grid_mesh.addScalarBar(pos=cloc, title='Topographic elevation, [m]', horizontal=False, titleFontSize=20)
            grid_mesh.scale([1,1,z_scale])
            

            grid_mesh.alpha(1)
            plt += grid_mesh.flag()     
            plt += grid_mesh.isolines(5).lw(1).c('k')

        except:
            print("VTK grid doesn't exist")
            
        try: 
            watertable = os.path.join(self.watershed.simulations_folder, self.modelname, '_watershed', 'VTK','VTU_Watertable_0.vtu')
            watertable_elev = vedo.Mesh(watertable) # 1 Elevation
            watertable_depth = vedo.Mesh(watertable) # 3 Depth
            surface_flow = vedo.UGrid(watertable) # 3 Surface Flow
            drain_flow = vedo.UGrid(watertable) # 3 Drain Flow
            watertable_blue = vedo.Mesh(watertable) # 4 blue
            
            zvals = watertable_elev.points()[:, 2]
            watertable_elev.cmap('jet',zvals, vmin=min(zvals))
            watertable_elev.addScalarBar(pos=cloc, title='Water table elevation, [m]', horizontal=False, titleFontSize=20)
            watertable_elev.scale([1,1,z_scale])
            plt += watertable_elev.flag() 
            
            watertable_depth.mapCellsToPoints()
            watertable_depth.cmap('coolwarm_r',input_array='Drawdown', vmin=0, vmax=1)
            watertable_depth.addScalarBar(pos=cloc, title='Water table depth, [m]', horizontal=False, titleFontSize=20)
            watertable_depth.scale([1,1,z_scale])
            plt += watertable_depth.flag()
            
            watertable_blue.color('b')
            watertable_blue.alpha(0.2)
            watertable_blue.scale([1,1,z_scale])
            watertable_blue.legend('Water table')
            plt += watertable_blue.flag()  
            
            nan_loc = ~np.isnan(surface_flow.celldata['Surfaceflow_log'])
            surface_flow = surface_flow.extractCellsByID([i for i, x in enumerate(nan_loc) if x])
            surface_flow = surface_flow.tomesh()
            surface_flow.cmap('jet','Surfaceflow_log', on='cells')
            surface_flow.addScalarBar(pos=cloc, title='Flow (log)', horizontal=False, titleFontSize=20)
            surface_flow.scale([1,1,z_scale])
            
            nan_loc = ~np.isnan(drain_flow.celldata['Drainflow_log'])
            drain_flow = drain_flow.extractCellsByID([i for i, x in enumerate(nan_loc) if x])
            drain_flow = drain_flow.tomesh()
            # cmin = min(drain_flow.pointdata['Drainflow_log'])
            # cmax = max(drain_flow.pointdata['Drainflow_log'])
            if cscale == 'custom':
                mi = 1
                ma = 4
                drain_flow.cmap('jet','Drainflow_log', on='cells',vmin = mi, vmax=ma)
            else:
                drain_flow.cmap('jet','Drainflow_log', on='cells')
            drain_flow.addScalarBar(pos=cloc, title='Seepage rates, log(Q) [mm/y]', horizontal=False, titleFontSize=20)
            drain_flow.scale([1,1,z_scale])
        except:
            print("VTK watertable doesn't exist")
        try:
            pathlines = os.path.join(self.watershed.simulations_folder, self.modelname, '_watershed', 'VTK','VTU_Pathlines.vtk')
            pathlines_mesh = vedo.Mesh(pathlines) #5
            
            #Pathlines
            if cscale == 'default':
                cmin = int(min(pathlines_mesh.pointdata['Time_log']))
                cmax = int(max(pathlines_mesh.pointdata['Time_log']))
            if cscale == 'custom':
                cmin = cmin
                cmax = cmax
            pathlines_mesh.cmap('hot_r',input_array='Time_log',vmin = cmin, vmax=cmax).lw(5)
            pathlines_mesh.addScalarBar(pos=cloc, title='Residence times, log(t) [y]', horizontal=False, titleFontSize=20)
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
        zs = max(watertable_elev.points()[:, 2]) - min(watertable_elev.points()[:, 2])
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
            pos = (max(watertable_elev.points()[:, 0])+ xs ,max(watertable_elev.points()[:,1])+ ys,max(watertable_elev.points()[:, 2])*4)
        if view == 'vertical':
            pos = (np.mean(watertable_elev.points()[:, 0]) ,np.mean(watertable_elev.points()[:,1]), np.mean(watertable_elev.points()[:, 2])*400)

        focal = (min(watertable_elev.points()[:, 0])+(xs/2), min(watertable_elev.points()[:, 1])+(ys/2), zs)
        cam = dict(pos = pos,focalPoint = focal)
        
        for i in range (0,len(object_list)):
            obj = object_list[i]
            if obj == 'grid':
                plt.show(grid_mesh,contour,stream,"Topography elevation", at=i, camera=cam, viewup='z', axes = 13)
            if obj == 'watertable':
                plt.show(grid_wireframe,contour,stream, watertable_elev,"Watertable elevation",camera=cam, viewup ='z', at=i, axes = 13)
            if obj == 'watertable_depth':
                plt.show(grid_wireframe,contour,stream, watertable_depth,"Watertable depth",camera=cam, viewup ='z', at=i, axes = 13)
            if obj == 'pathlines':
                #plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh,"Groundwater flow paths",camera=cam, viewup ='z', at=i, axes = 13)
                #plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh,camera=cam, viewup ='z', at=i, axes = 13)
                #plt.show(grid_mesh, pathlines_mesh,camera=cam, viewup ='z', at=i, axes = 13)
                plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh, "Groundwater flow paths",camera=cam, viewup ='z', at=i, axes = 13)
            if obj == 'surface_flow':
                plt.show(grid_wireframe,contour,stream, watertable_blue, surface_flow,"Surface flow",camera=cam, viewup ='z', at=i, axes = 13)
            if obj == 'drain_flow':
                plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,"Groundwater seepage",camera=cam, viewup ='z', at=i, axes = 13)
                #plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,camera=cam, viewup ='z', at=i, axes = 13)
                #plt.show(grid_mesh,drain_flow,camera=cam, viewup ='z', at=i, axes = 13)
        
        
        if interactive == True:
            plt.show(interactive=1,interactorStyle=6).close()
        else:
            plt.screenshot(os.path.join(self.watershed.simulations_folder, self.modelname, '_figures','3Dvisual.png')).close()

    def visual2D(self, object_list = ['map','grid', 'watertable', 'watertable_depth','drain_flow','surface_flow','pathlines', 'residence_times'] , view = 'south-west', 
                 interactive = False, time_step = 0, lines=100, z_scale=20, render=1, 
                 cscale = 'default', cmin = -1, cmax = 1, cloc=(0.65,0.75) , size=(1500,1080)):
       
        def trim_axs(axs, N):
            """little helper to massage the axs list to have correct length..."""
            axs = axs.flat
            for ax in axs[N:]:
                ax.remove()
            return axs[:N]
        
        modelfolder = os.path.join(self.watershed.simulations_folder, self.modelname)
        fontprop = toolbox.plot_params(8,15,18,20)
        
        contour = gpd.read_file(self.watershed.geographic.watershed_contour_shp)
        crs = contour.crs
        dem = rasterio.open(self.watershed.geographic.watershed_box_buff_dem)
        try:
            streams = gpd.read_file(self.watershed.hydrology.streams)
        except:
            pass
        
        # open the watertable elevation files
        watertable_file = os.path.join(modelfolder,'_watershed','watertable_elevation.npy')
        watertable_elevation = np.load(watertable_file, allow_pickle=True).item()
        
        watertable_depth_file = os.path.join(modelfolder,'_watershed','watertable_depth.npy')
        watertable_depth= np.load(watertable_depth_file, allow_pickle=True).item()
        
        # open the drain flux files
        drain_file = os.path.join(modelfolder,'_watershed','outflow_drain.npy')
        drain_area = np.load(drain_file, allow_pickle=True).item()
        
        # open the surface flux files
        surface_file = os.path.join(modelfolder,'_watershed','accumulation_flux.npy')
        surface_area = np.load(surface_file, allow_pickle=True).item()
        
        N = len(object_list)
        C = int(np.sqrt(N))
        R = int(N/C)+1
        fig, axs = plt.subplots(nrows=R, ncols=C ,figsize=(5*C,R*(5*dem.height/dem.width)), dpi=300)
        axs = trim_axs(axs,N)
        image = []
        basemap = []
        for i in range (0,len(object_list)):
            obj = object_list[i]
            if obj == 'grid':
                axs[i].set_title('Topographic elevation, [m]')
                image_hidden = axs[i].imshow(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), 
                             cmap='terrain')
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                     transform=dem.transform, cmap='terrain', alpha=1, zorder=2, aspect="auto")
                try:
                    streams.plot(ax=axs[i], lw=2, color='b', zorder=4,legend=True, label='Streams')
                except:
                    pass
            if obj == 'watertable':
                axs[i].set_title('Water table elevation, [m]')
                image_hidden = axs[i].imshow(np.ma.masked_where(watertable_elevation[time_step]< -100, watertable_elevation[time_step]), 
                             cmap='jet')
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(watertable_elevation[time_step]< -100, watertable_elevation[time_step]), ax=axs[i], 
                     transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto")
            if obj == 'watertable_depth':
                axs[i].set_title('Water table depth, [m]')
                image_hidden = axs[i].imshow(np.ma.masked_where(watertable_depth[time_step]< -100, watertable_depth[time_step]), 
                             cmap='coolwarm_r')
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(watertable_depth[time_step]< -100, watertable_depth[time_step]), ax=axs[i], 
                     transform=dem.transform, cmap='coolwarm_r', alpha=1, zorder=2, aspect="auto")
            if obj == 'drain_flow':
                axs[i].set_title('Seepage rates, log(Q) [mm/y]')
                drain = np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, drain_area[time_step])
                image_hidden = axs[i].imshow(np.ma.masked_where(drain<= 0, np.log10(drain)), 
                             cmap='jet')
                image.append(image_hidden)
                basemap.append(1)
                show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                     transform=dem.transform, cmap='Greys', alpha=0.5, zorder=2, aspect="auto")
                show(np.ma.masked_where(drain<= 0, np.log10(drain)), ax=axs[i], 
                     transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto")
            if obj == 'surface_flow':
                axs[i].set_title('Cumulate seepage rates, log(Q) [mm/y]')
                surface = np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, surface_area[time_step])
                image_hidden = axs[i].imshow(np.ma.masked_where(surface_area[time_step]<= 0, np.log10(surface)), 
                             cmap='jet')
                image.append(image_hidden)
                basemap.append(1)
                show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                     transform=dem.transform, cmap='Greys', alpha=0.5, zorder=2, aspect="auto")
                show(np.ma.masked_where(surface_area[time_step]<= 0, np.log10(surface)), ax=axs[i], 
                     transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto")
            if obj == 'pathlines':
                axs[i].set_title('Residence times, log(t) [d]')
                pthobj = flopy.utils.PathlineFile(os.path.join(modelfolder,self.modelname+'.mppth'))
                pth_data = pthobj.get_alldata()
                random_indices = np.random.choice(len(pth_data), size=lines)
                geotx_p = self.watershed.geographic.x_coord
                geoty_p = self.watershed.geographic.y_coord
                geot_p = self.watershed.geographic.geodata
                cols = geotx_p.shape[0]
                rows = geoty_p.shape[0]
                ext = []
                xarr = [0, cols]
                yarr = [0, rows]
                for px in xarr:
                    for py in yarr:
                        x = geotx_p[0] + (px * geot_p[1]) + (py * geot_p[2])
                        y = geoty_p[0] + (px * geot_p[4]) + (py * geot_p[5])
                        ext.append([x, y])
                max_time = []
                min_time = []
                for j in random_indices:
                    max_time.append(np.max(np.log10(pth_data[j].time)))
                    min_time.append(np.min(np.log10(pth_data[j].time)))
                for j in random_indices:
                    x = pth_data[j].x + ext[1][0]
                    y = pth_data[j].y + ext[1][1]
                    points = np.array([x, y]).T.reshape(-1, 1, 2)
                    segments = np.concatenate([points[:-1], points[1:]], axis=1)
                    lc = LineCollection(segments, cmap='hot_r')
                    lc.set_array(np.log10(pth_data[j].time))
                    lc.set_linewidth(2)
                    lc.set_clim(1,np.max(max_time))
                    line = axs[i].add_collection(lc)
                image.append(line)
                basemap.append(1)
                   
                
            if obj == 'residence_times':
                axs[i].set_title('Residence times, log(t) [d]')
                res_time = np.zeros(np.shape(dem))
                endobj = flopy.utils.EndpointFile(os.path.join(modelfolder,self.modelname+'.mpend'))
                e = endobj.get_alldata()
                for j in range(len(e)):
                     res_time[e[j].i0,e[j].j0] = np.log10(e[j].time)
                image_hidden = axs[i].imshow(np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, res_time), cmap='hot_r')
                image.append(image_hidden)
                basemap.append(1)
                show(np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, res_time), ax=axs[i], 
                     transform=dem.transform, cmap='hot_r', alpha=1, zorder=2, aspect="auto")
                
            if obj == 'map':
                axs[i].set_title('Watershed boundary')
                basemap.append(1)
                image.append(None)
        compt = 0
        for ax in axs:
            contour.plot(ax=ax, lw=2, color='k', zorder=4,legend=True, label='Watershed')
            bounds = dem.bounds
            xlim = ([bounds[0], bounds[2]])
            ylim = ([bounds[1], bounds[3]])
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
            scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower center')
            ax.add_artist(scalebar)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            if image[compt] != None:
                divider = make_axes_locatable(ax)
                cax = divider.append_axes(size="4%",position='right', pad=0.05)
                fig.add_axes(cax)
                cbar = fig.colorbar(image[compt], cax=cax, orientation="vertical")
                cbar.ax.get_ymajorticklabels()
                list(cbar.get_ticks())
                cbar.ax.tick_params(labelsize=10)
                cbar.ax.yaxis.set_ticks_position('right')
                cbar.ax.tick_params(size=2)
            if basemap[compt] == 1:
                cx.add_basemap(ax,crs=crs,source='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png')
            compt +=1
        
        fig.tight_layout ()
        fig.savefig(os.path.join(modelfolder,'test.png'), dpi=300, bbox_inches='tight', transparent=False)
        
        
        
        