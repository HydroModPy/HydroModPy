# -*- coding: utf-8 -*-
"""
 * Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
 * which is available at https://www.apache.org/licenses/LICENSE-2.0.
 *
 * SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

#%% LIBRAIRIES

# Python
import numpy as np
from collections.abc import Sequence
from datetime import datetime
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib_scalebar.scalebar import ScaleBar
from matplotlib.collections import LineCollection
import rasterio
from rasterio.plot import show
import geopandas as gpd
import flopy
import os, sys
import contextily as cx
import matplotlib as mpl
from matplotlib import rcsetup

# HydroModPy
from hydromodpy.tools import toolbox, get_logger

logger = get_logger(__name__)


def _require_vedo():
    """
    Import vedo only when 3D visualizations are requested.

    Raises a clear error when the VTK stack is missing instead of
    crashing on module import.
    """
    try:
        import vedo  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "3D visualization requires the 'vedo' dependency (VTK stack). "
            "Install it with 'pip install vedo' or use the full HydroModPy "
            "install (not the 'light' extra)."
        ) from exc
    except OSError as exc:
        raise ImportError(
            "The VTK runtime used by vedo could not start. Install the "
            "system libraries for VTK/Qt (e.g. libgl1, libx11-6) or run "
            "inside an image that bundles them."
        ) from exc

    return vedo

#%% CLASS

class Visualization():
    """
    Class to plot results by default.
    """
    
    def __init__(self, watershed, modelname):
        """
        Parameters
        ----------
        watershed : object
            Variable object of the model domain (watershed). Created by geographic.
        modelname : str
            Name of the model simulation.
        """
        self.watershed = watershed
        self.modelname = modelname

    #%% 2D
            
    def visual2D(self, 
                 object_list: list=['map','grid',
                                    'watertable', 'watertable_depth',
                                    'drain_flow','surface_flow',
                                    'pathlines','residence_times'], 
                 color_scale = None, time_step = 0, lines = 100, structure = 'v'):
        """
        

        Parameters
        ----------
        object_list : list
            Select the simulation results you wish to plot. 
        color_scale : list, optional
            Boundary limits for color scale. The default is None.
        time_step : int, optional
            Choice the stress period to plot. The default is 0.
        lines : int, optional
            Number of randomly selected pathlines to be traced. The default is 100.
        structure : str, optional
            Structure of the frame figures 'h':horizontal or 'v': vertical. The default is 'v'.
        """
       
        logger.info("Plotting 2D map visualizations for model %s", self.modelname)
       
        if len(object_list) == len(color_scale):
            pass
        elif color_scale is None:
            color_scale = [(None,None),(None,None),
                           (None,None),(None,None),
                           (None,None),(None,None),
                           (None,None),(None,None)]
        else:
            logger.error("object_list and color_scale must have the same length.")
            sys.exit(1)
        
        def trim_axs(axs, N):
            """Help to manage the axs list in order to have correct lenght/height"""
            axs = axs.flat
            for ax in axs[N:]:
                ax.remove()
            return axs[:N]
        
        modelfolder = os.path.join(self.watershed.simulations_folder, self.modelname)
        fontprop = toolbox.plot_params(8,15,18,20)
        
        path_res = os.path.join(modelfolder,'_postprocess')
        
        try:
            contour = gpd.read_file(self.watershed.geographic.watershed_contour_shp)
            crs = contour.crs
        except:
            pass
        
        try:
            dem = rasterio.open(self.watershed.geographic.watershed_box_buff_dem)
        except:
            pass
        
        try:
            streams = gpd.read_file(self.watershed.hydrography.streams)
        except:
            pass
        
        # open the watertable elevation files
        try:
            watertable_file = os.path.join(path_res,'watertable_elevation.npy')
            watertable_elevation = np.load(watertable_file, allow_pickle=True).item()
        except:
            pass
        
        # open the watertable depth files
        try:
            watertable_depth_file = os.path.join(path_res,'watertable_depth.npy')
            watertable_depth= np.load(watertable_depth_file, allow_pickle=True).item()
        except:
            pass
        
        # open the drain flux files
        try:
            drain_file = os.path.join(path_res,'outflow_drain.npy')
            drain_area = np.load(drain_file, allow_pickle=True).item()
        except:
            pass
        
        # open the surface flux files
        try:
            surface_file = os.path.join(path_res,'accumulation_flux.npy')
            surface_area = np.load(surface_file, allow_pickle=True).item()
        except:
            pass
        
        N = len(object_list)
        if structure == 'v':
            C = int(np.sqrt(N))
            R = int(N/C)+1
        if structure == 'h':
            R = int(np.sqrt(N))
            C = int(N/R)+1
            
        fig, axs = plt.subplots(nrows=R, ncols=C ,figsize=(5*C,R*(5*dem.height/dem.width)), dpi=300)
        axs = trim_axs(axs,N)
        image = []
        basemap = []
        for i in range (0,len(object_list)):
            obj = object_list[i]
            
            if obj == 'grid':
                axs[i].set_title('Topographic elevation [m]')
                image_hidden = axs[i].imshow(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), 
                             cmap='terrain', vmin=color_scale[i][0], vmax=color_scale[i][1])
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                     transform=dem.transform, cmap='terrain', alpha=1, zorder=2, aspect="auto", vmin=color_scale[i][0], vmax=color_scale[i][1])
                try:
                    streams.plot(ax=axs[i], lw=2, color='b', zorder=4, legend=False,
                                 # label='Hydrography'
                                 )
                except:
                    pass
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=False,
                                 # label='Watershed'
                                 )
                except:
                    pass
                
            if obj == 'watertable':
                axs[i].set_title('Watertable elevation [m]')
                image_hidden = axs[i].imshow(np.ma.masked_where((watertable_elevation[time_step]< -100), watertable_elevation[time_step]), 
                             cmap='Blues_r', vmin=color_scale[i][0], vmax=color_scale[i][1])
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(watertable_elevation[time_step]< -100, watertable_elevation[time_step]), ax=axs[i], 
                     transform=dem.transform, cmap='Blues_r', alpha=1, zorder=2, aspect="auto", vmin=color_scale[i][0], vmax=color_scale[i][1])
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=False)
                except:
                    pass
                
            if obj == 'watertable_depth':
                axs[i].set_title('Watertable depth [m]')
                image_hidden = axs[i].imshow(np.ma.masked_where((watertable_depth[time_step]< -100) | (dem.read(1) < -100), watertable_depth[time_step]), 
                             cmap='coolwarm_r', vmin=color_scale[i][0], vmax=color_scale[i][1])
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where((watertable_depth[time_step]< -100) | (dem.read(1) < -100), watertable_depth[time_step]), ax=axs[i], 
                     transform=dem.transform, cmap='coolwarm_r', alpha=1, zorder=2, aspect="auto", vmin=color_scale[i][0], vmax=color_scale[i][1])
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=False)
                except:
                    pass
                
            if obj == 'drain_flow':
                # axs[i].set_title('Seepage rates, log(Q) [m/d]')
                axs[i].set_title('Seepage outflow [m$^3$/d]')
                # axs[i].set_title('Seepage outflow [m3/d]')
                drain = np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, drain_area[time_step])
                # image_hidden = axs[i].imshow(np.ma.masked_where(drain<= 0, np.log10(drain)), 
                #              cmap='jet', vmin=color_scale[i][0], vmax=color_scale[i][1])
                image_hidden = axs[i].imshow(np.ma.masked_where(drain<= 0, (drain)), 
                              cmap='RdYlGn_r', vmin=color_scale[i][0], vmax=color_scale[i][1])
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                     transform=dem.transform, cmap='Greys', alpha=0.3, zorder=2, aspect="auto")
                # show(np.ma.masked_where(drain<= 0, np.log10(drain)), ax=axs[i], 
                #       transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=color_scale[i][0],
                #       vmax=color_scale[i][1])
                show(np.ma.masked_where(drain<= 0, (drain)), ax=axs[i], 
                     transform=dem.transform, cmap='RdYlGn_r', alpha=1, zorder=2, aspect="auto", vmin=color_scale[i][0],
                     vmax=color_scale[i][1])
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=False)
                except:
                    pass
                
            if obj == 'surface_flow':
                # axs[i].set_title('Cumulate seepage rates, log(Q) [m/d]')
                axs[i].set_title('Accumulated outflow [m$^3$/d]')
                # axs[i].set_title('Accumulated outflow [m3/d]')
                surface = np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, surface_area[time_step])
                # image_hidden = axs[i].imshow(np.ma.masked_where(surface_area[time_step]<= 0, np.log10(surface)), 
                image_hidden = axs[i].imshow(np.ma.masked_where(surface_area[time_step]<= 0, (surface)), 
                              cmap='jet', vmin=color_scale[i][0], vmax=color_scale[i][1])
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                     transform=dem.transform, cmap='Greys', alpha=0.3, zorder=0, aspect="auto")
                # show(np.ma.masked_where(surface_area[time_step]<= 0, np.log10(surface)), ax=axs[i], 
                #      transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=color_scale[i][0], 
                #      vmax=color_scale[i][1])
                show(np.ma.masked_where(surface_area[time_step]<= 0, (surface)), ax=axs[i], 
                     transform=dem.transform, cmap='jet', alpha=1, zorder=2, aspect="auto", vmin=color_scale[i][0], 
                     vmax=color_scale[i][1])
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=False)
                except:
                    pass
                
            if obj == 'pathlines':
                # show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                #          transform=dem.transform, cmap='Greys', alpha=0.3, zorder=0, aspect="auto")
                # axs[i].set_title('Pathlines, log(t) [d]')
                axs[i].set_title('Time pathlines [y]')
                pthobj = flopy.utils.PathlineFile(os.path.join(modelfolder,self.modelname+'.mppth'))
                pth_data = pthobj.get_alldata()
                if lines != None:
                    random_indices = np.random.choice(len(pth_data), size=lines) # RANDOM LINES
                if lines == None:
                    random_indices = np.arange(len(pth_data))
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
                    # max_time.append(np.max(np.log10(pth_data[j].time)))
                    # min_time.append(np.min(np.log10(pth_data[j].time)))
                    max_time.append(np.max((pth_data[j].time)))
                    min_time.append(np.min((pth_data[j].time)))
                for j in random_indices:
                    x = pth_data[j].x + ext[1][0]
                    y = pth_data[j].y + ext[1][1]
                    points = np.array([x, y]).T.reshape(-1, 1, 2)
                    segments = np.concatenate([points[:-1], points[1:]], axis=1)
                    lc = LineCollection(segments, cmap='plasma_r', alpha=0.8)
                    # lc.set_array(np.log10(pth_data[j].time/365)) # log(t) in days
                    lc.set_array(pth_data[j].time / 365) # t in years
                    lc.set_linewidth(2)
                    if color_scale[i][0] == None:
                        lc.set_clim(1,np.max(max_time))
                    else:
                        lc.set_clim(color_scale[i][0],color_scale[i][1])
                    line = axs[i].add_collection(lc)
                image.append(line)
                basemap.append(0)
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=False)
                except:
                    pass
                
            if obj == 'residence_times':
                axs[i].set_title('Residence times [y]')
                res_time = np.zeros(np.shape(dem))
                endobj = flopy.utils.EndpointFile(os.path.join(modelfolder,self.modelname+'.mpend'))
                e = endobj.get_alldata()
                for j in range(len(e)):
                    # time_out = pth_data[j].time[0] # explore pathlines
                    # res_time[e[j].i0,e[j].j0] = np.log10(e[j].time) # where infiltrated
                    res_time[e[j].i,e[j].j] = (e[j].time) /365 # where outputed
                res_time = np.ma.masked_where(res_time <= 0, res_time)
                image_hidden = axs[i].imshow(np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, res_time),
                                             cmap='cool', vmin=color_scale[i][0], vmax=color_scale[i][1])
                # show(np.ma.masked_where(dem.read(1) < -100, dem.read(1)), ax=axs[i], 
                #      transform=dem.transform, cmap='Greys', alpha=0.3, zorder=0, aspect="auto")
                image.append(image_hidden)
                basemap.append(0)
                show(np.ma.masked_where(self.watershed.geographic.dem_clip<= 0, res_time), ax=axs[i], 
                     transform=dem.transform, cmap='cool', alpha=1, zorder=2, aspect="auto",
                     vmin=color_scale[i][0], vmax=color_scale[i][1])                
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=False)
                except:
                    pass
                
            if obj == 'map':
                axs[i].set_title('Watershed boundary')
                basemap.append(1)
                image.append(None)
                try:
                    contour.plot(ax=axs[i], lw=2, edgecolor='k', facecolor='None', zorder=4, legend=True, label='Watershed')
                except:
                    pass
                try:
                    streams.plot(ax=axs[i], lw=2, color='b', zorder=4, legend=True, label='Hydrography')
                except:
                    pass
            
        compt = 0
        for ax in axs:
            ## Rajouter ici if 'conceptal' then do not display watershed boundary
            # contour.plot(ax=ax, lw=2, color='k', zorder=4,legend=True, label='Watershed')
            bounds = dem.bounds
            xlim = ([bounds[0], bounds[2]])
            ylim = ([bounds[1], bounds[3]])
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
            ax.set_aspect('equal')
            scalebar = ScaleBar(1,box_alpha=0, scale_loc = 'top', location='lower right', rotation='horizontal-only')
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
                try:
                    cx.add_basemap(ax,crs=crs,source='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png')
                except:
                    pass
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(loc='best', framealpha=0.8)
            compt +=1
        
        name = self.modelname
        fig.suptitle(name.upper(), fontsize=12, y=1.0)
        fig.tight_layout()
        now = datetime.now()
        #name = now.strftime("%d_%m_%Y_%Hh%M")
        fig.savefig(os.path.join(modelfolder,'_postprocess','_figures', '2D_' + str(name)+'.png'), dpi=300, 
                    bbox_inches='tight', transparent=False)
        plt.show()

    #%% 3D
    
    def visual3D(self, object_list=['grid', 'watertable'] ,
                 view = 'south-west', bg = 'lb', interactive = False,
                 lines=100, z_scale=20, render=1,
                 cscale = 'default', cmin=-1, cmax=1,
                 cloc=(0.65,0.75) , size=(1500,1080)):
        
        """
        3Dvisual shows the vtk objects from an interactive windows or a screenshot.

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
        cloc : tuple, optional
            Scalar bar location either as legacy (x, y) anchor or as ((x0, y0), (x1, y1)) bounding box.
        """
        
        logger.info("Plotting 3D visualization for model %s", self.modelname)
        vedo = _require_vedo()
        
        def _normalize_scalarbar_pos(raw_pos):
            """Keep backward compatibility with legacy scalarbar coordinates."""
            if raw_pos is None or isinstance(raw_pos, str):
                return raw_pos

            if not isinstance(raw_pos, Sequence):
                return raw_pos

            try:
                if len(raw_pos) == 4 and not any(isinstance(v, Sequence) and not isinstance(v, str) for v in raw_pos):
                    x0, y0, width, height = map(float, raw_pos)
                    x0 = max(0.0, min(x0, 0.99))
                    y0 = max(0.0, min(y0, 0.99))
                    x1 = max(x0 + 0.01, min(x0 + width, 0.999))
                    y1 = max(y0 + 0.01, min(y0 + height, 0.999))
                    return ((x0, y0), (x1, y1))

                if len(raw_pos) == 2:
                    first, second = raw_pos
                    if isinstance(first, Sequence) and not isinstance(first, str):
                        if isinstance(second, Sequence) and not isinstance(second, str):
                            return (
                                (float(first[0]), float(first[1])),
                                (float(second[0]), float(second[1])),
                            )
                    if not isinstance(first, Sequence) and not isinstance(second, Sequence):
                        x0, y0 = float(first), float(second)
                        width, height = 0.1, 0.45
                        x0 = max(0.0, min(x0, 0.99))
                        y0 = max(0.0, min(y0, 0.99))
                        x1 = max(x0 + 0.01, min(x0 + width, 0.999))
                        y1 = max(y0 + 0.01, min(y0 + height, 0.999))
                        return ((x0, y0), (x1, y1))
            except (TypeError, ValueError, IndexError):
                return raw_pos

            return raw_pos

        scalarbar_pos = _normalize_scalarbar_pos(cloc)

        vedo.settings.default_backend= 'vtk'
        
        #vedo.settings.screeshot_scale = render
        plt = vedo.Plotter(N=len(object_list), axes=dict(xtitle='m', ytitle='m', ztitle='m', 
                                          yzGrid=False), size=size)

        # Load files
        try:
            contour = vedo.Mesh(os.path.join(self.watershed.simulations_folder, self.modelname,
                                             '_postprocess', '_vtuvtk','watershed_contour.vtk'))
            contour.scale([1,1,z_scale])
            contour.color('k').lw(2)
            contour.render_lines_as_tubes(value=True)
        except:
            pass
            
        try:
            stream = vedo.Mesh(os.path.join(self.watershed.simulations_folder, self.modelname,
                                            '_postprocess', '_vtuvtk','streams.vtk'))
            stream.scale([1,1,z_scale])
            stream.color('b').lw(5)
            stream.render_lines_as_tubes(value=True)
        except:
            stream=None
            pass
        
        try:
            grid = os.path.join(self.watershed.simulations_folder, self.modelname,
                                '_postprocess', '_vtuvtk', 'grid.vtu')
            grid_mesh = vedo.load(grid) #grid_mesh
            grid_wireframe = vedo.load(grid).wireframe() #grid_wireframe
            if bg == 'white':
                grid_wireframe.color('black')
            else:
                grid_wireframe.color('white')
            grid_wireframe.scale([1,1,z_scale])
            grid_wireframe.alpha(0.1)
            #plt += grid_wireframe.flag()
            
            zvals = grid_mesh.points[:, 2]
            # grid_mesh.add_elevation_scalars(lowPoint=(0,0,min(zvals)),highPoint=(0,0,max(zvals)), vrange=(min(zvals), max(zvals)))
            grid_mesh.cmap('terrain',zvals, vmin=min(zvals))
            # grid_mesh.add_scalarbar(pos=cloc, title='Topographic elevation [m]',
            #                        horizontal=False, titleFontSize=20)
            grid_mesh.add_scalarbar(pos=scalarbar_pos, 
                                   horizontal=False)
            grid_mesh.scale([1,1,z_scale])
            
    
            grid_mesh.alpha(1)
            #plt += grid_mesh     
            #plt += grid_mesh.isolines(5).lw(1).c('k')
    
        except Exception:
            logger.warning("VTU grid mesh missing for 3D visualization: %s", grid, exc_info=True)
            
        #try: 
        watertable = os.path.join(self.watershed.simulations_folder, self.modelname,
                                  '_postprocess', '_vtuvtk', 'watertable_0.vtu')
        watertable_elev = vedo.load(watertable) # 1 Elevation
        watertable_depth = vedo.load(watertable) # 3 Depth
        if 'surface_flow' in object_list:
            surface_flow = vedo.UnstructuredGrid(watertable) # 3 Surface Flow
        if 'drain_flow' in object_list:
            drain_flow = vedo.UnstructuredGrid(watertable) # 3 Drain Flow
        watertable_blue = vedo.load(watertable) # 4 blue
        
        zvals = watertable_elev.points[:, 2]
        watertable_elev.cmap('Blues_r',zvals, vmin=min(zvals))
        # watertable_elev.add_scalarbar(pos=cloc, title='Watertable elevation [m]', horizontal=False, titleFontSize=20)
        watertable_elev.add_scalarbar(pos=scalarbar_pos, horizontal=False)
        watertable_elev.scale([1,1,z_scale])
        #plt += watertable_elev
        
        watertable_depth = watertable_depth.map_cells_to_points()
        watertable_depth.cmap('coolwarm_r',input_array='Drawdown', vmin=0, vmax=10)
        # watertable_depth.add_scalarbar(pos=cloc, title='Watertable depth [m]', horizontal=False, titleFontSize=20)
        watertable_depth.add_scalarbar(pos=scalarbar_pos, horizontal=False)
        watertable_depth.scale([1,1,z_scale])
        #plt += watertable_depth
        
        watertable_blue.color('b')
        watertable_blue.alpha(0.2)
        watertable_blue.scale([1,1,z_scale])
        watertable_blue.legend('Watertable')
        #plt += watertable_blue  
        
        if 'surface_flow' in object_list:
            surface_flow = surface_flow.tomesh()
            nan_loc = ~np.isnan(surface_flow.celldata['Surfaceflow_log'])
            surface_flow = surface_flow.extract_cells([i for i, x in enumerate(nan_loc) if x])
            surface_flow.cmap('jet', 'Surfaceflow_log', on='cells')
            # surface_flow.add_scalarbar(pos=cloc, title='Flow (log)', horizontal=False, titleFontSize=20)
            surface_flow.add_scalarbar(pos=scalarbar_pos, horizontal=False)
            surface_flow.scale([1,1,z_scale])
            
        if 'drain_flow' in object_list:
            drain_flow = drain_flow.tomesh()
            nan_loc = ~np.isnan(drain_flow.celldata['Drainflow_log'])
            drain_flow = drain_flow.extract_cells([i for i, x in enumerate(nan_loc) if x])
            # cmin = min(drain_flow.pointdata['Drainflow_log'])
            # cmax = max(drain_flow.pointdata['Drainflow_log'])
            try:
                if cscale == 'custom':
                    mi = 1
                    ma = 4
                    drain_flow.cmap('RdYlGn_r', 'Drainflow_log', on='cells', vmin=mi, vmax=ma)
                else:
                    drain_flow.cmap('RdYlGn_r', 'Drainflow_log', on='cells')
                # drain_flow.add_scalarbar(pos=cloc, title='Seepage outflow log [m$^3$/d]', horizontal=False, titleFontSize=20)
                drain_flow.add_scalarbar(pos=scalarbar_pos,
                                         horizontal=False)
                drain_flow.scale([1,1,z_scale])
            except Exception:
                logger.warning("VTK drain_flow mesh missing or failed to process for 3D visualization", exc_info=True)
            
        #try:
        pathlines = os.path.join(self.watershed.simulations_folder, self.modelname,
                                 '_postprocess', '_vtuvtk', 'pathlines.vtk')
        pathlines_mesh = vedo.Mesh(pathlines) #5
        #Pathlines
        if cscale == 'default':
            cmin = int(min(pathlines_mesh.pointdata['Time_log']))
            cmax = int(max(pathlines_mesh.pointdata['Time_log']))
        if cscale == 'custom':
            cmin = cmin
            cmax = cmax
        pathlines_mesh.cmap('plasma_r', input_array='Time_log', vmin=cmin, vmax=cmax).lw(5)
        # pathlines_mesh.add_scalarbar(pos=cloc, title='Residence times log [y]', horizontal=False, titleFontSize=20)
        pathlines_mesh.add_scalarbar(pos=scalarbar_pos, horizontal=False)
        pathlines_mesh.scale([1,1,z_scale])
        pathlines_mesh.render_lines_as_tubes(value=True)
        pathlines_mesh.legend('Pathlines')
        n = lines
        # try:
        #     x = pathlines_mesh.lines
        #     length = max(map(len, x))
        #     y=np.array([xi+[None]*(length-len(xi)) for xi in x])
        #     number_of_rows = y.shape[0]
        #     random_indices = np.random.choice(number_of_rows, size=len(x)-n, replace=False)
        #     y1 = y[random_indices, :].flatten()
        #     pts =  y1[y1 != np.array(None)]
        #     pathlines_mesh.delete_cells(pts)
        #     pathlines_mesh = pathlines_mesh.subsample(0.5)
        # except:
        #     print("VTK pathlines doesn't exist")
        #     pass
        # 

        #View
        xs = max(watertable_elev.points[:, 0]) - min(watertable_elev.points[:, 0])
        ys = max(watertable_elev.points[:, 1]) - min(watertable_elev.points[:, 1])
        zs = max(watertable_elev.points[:, 2]) - min(watertable_elev.points[:, 2])
        if view == 'north':
            pos = (min(watertable_elev.points[:, 0])+ xs ,max(watertable_elev.points[:,1])+ ys,max(watertable_elev.points[:, 2])*10)
        if view == 'north-east':
            pos = (max(watertable_elev.points[:, 0])+ xs ,max(watertable_elev.points[:,1])+ ys,max(watertable_elev.points[:, 2])*10)
        if view == 'east':
            pos = (max(watertable_elev.points[:, 0])+ xs ,min(watertable_elev.points[:,1])+ ys,max(watertable_elev.points[:, 2])*10)
        if view == 'south-east':
            pos = (max(watertable_elev.points[:, 0])+ xs ,max(watertable_elev.points[:,1])- ys,max(watertable_elev.points[:, 2])*10)
        if view == 'south':
            pos = (min(watertable_elev.points[:, 0])+ xs ,min(watertable_elev.points[:,1])- ys,max(watertable_elev.points[:, 2])*10)
        if view == 'south-west':
            pos = (min(watertable_elev.points[:, 0])- xs ,min(watertable_elev.points[:,1])- ys,max(watertable_elev.points[:, 2])*10)
        if view == 'west':
            pos = (min(watertable_elev.points[:, 0])- xs ,min(watertable_elev.points[:,1])+ ys,max(watertable_elev.points[:, 2])*10)
        if view == 'north-west':
            pos = (min(watertable_elev.points[:, 0])- xs ,max(watertable_elev.points[:,1])+ ys,max(watertable_elev.points[:, 2])*10)
        if view == 'custom':
            pos = (max(watertable_elev.points[:, 0])+ xs ,max(watertable_elev.points[:,1])+ ys,max(watertable_elev.points[:, 2])*4)
        if view == 'vertical':
            pos = (np.mean(watertable_elev.points[:, 0]) ,np.mean(watertable_elev.points[:,1]), np.mean(watertable_elev.points[:, 2])*400)

        focal = (min(watertable_elev.points[:, 0])+(xs/2), min(watertable_elev.points[:, 1])+(ys/2), zs)
        cam = dict(pos = pos,focalPoint = focal)
        
        for i in range(len(object_list)):
            obj = object_list[i]
            logger.info("Processing object %s", obj)
            if obj == 'grid':
                plt.show(grid_mesh,contour,stream,"Topographic elevation [m]", at=i,
                         camera=cam, viewup='z', axes = 13, bg=bg)
            if obj == 'watertable':
                plt.show(grid_wireframe,contour,stream, watertable_elev,"Watertable elevation [m]",
                         camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
            if obj == 'watertable_depth':
                plt.show(grid_wireframe,contour,stream, watertable_depth,"Watertable depth [m]",
                         camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
            if obj == 'pathlines':
                #plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh,"Groundwater flow paths",camera=cam, viewup ='z', at=i, axes = 13)
                plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh, "Time pathlines log [d]",
                         camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
                #plt.show(grid_wireframe,contour,stream, watertable_blue, pathlines_mesh,camera=cam, viewup ='z', at=i, axes = 13)
                #plt.show(grid_mesh, pathlines_mesh,camera=cam, viewup ='z', at=i, axes = 13)
            if obj == 'surface_flow':
                plt.show(grid_wireframe,contour, watertable_blue, surface_flow, "Accumulated outflow log [m3/d]",
                         camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
            if obj == 'drain_flow':
                #plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,"Groundwater seepage",camera=cam, viewup ='z', at=i, axes = 13)
                plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,"Seepage outflow log [m3/d]",
                         camera=cam, viewup ='z', at=i, axes = 13, bg=bg)
                #plt.show(grid_wireframe,contour,stream, watertable_blue, drain_flow,camera=cam, viewup ='z', at=i, axes = 13)
                #plt.show(grid_mesh,drain_flow,camera=cam, viewup ='z', at=i, axes = 13)
        if interactive == True:
            plt.show(interactive=1)
            plt.close()
        else:
            plt += __doc__
            plt.screenshot(os.path.join(self.watershed.simulations_folder, self.modelname,
                                        '_postprocess', '_figures', '3D_'+self.modelname+'.png')).close()
    
    #%% CROSS
    
    def interactive_cross_section(self, dem_data, wt_data, river_data, interactive):
        logger.info("Plotting 2D cross-section for model %s", self.modelname)
        
        # Modules
        mpl.rcParams.update(mpl.rcParamsDefault)
        original_backend = plt.get_backend()
        backend_supports_events = original_backend in rcsetup.interactive_bk
        backend_switched = False

        if interactive and not backend_supports_events:
            try:
                plt.switch_backend("QtAgg")
            except Exception:
                backend_supports_events = False
                logger.warning(
                    "Unable to activate QtAgg; falling back to static cross-section output at %s",
                    f"_postprocess/_figures/CROSS_{self.modelname}.png",
                )
            else:
                backend_supports_events = True
                backend_switched = True
                logger.info("Matplotlib interactive backend enabled: QtAgg")
        elif backend_supports_events:
            logger.info("Matplotlib interactive backend active: %s", original_backend)
        else:
            logger.warning(
                "Current Matplotlib backend is not interactive; saving static cross-section to %s",
                f"_postprocess/_figures/CROSS_{self.modelname}.png",
            )

        effective_interactive = interactive and backend_supports_events
        
        # Figure params
        fig, main_ax = plt.subplots(figsize=(5, 5))
        divider = make_axes_locatable(main_ax)
        top_ax = divider.append_axes("top",1.1, pad=0.2, sharex=main_ax)
        right_ax = divider.append_axes("right",1.1, pad=0.2, sharey=main_ax)
        
        # Axis names
        top_ax.xaxis.set_tick_params(labelbottom=False)
        right_ax.yaxis.set_tick_params(labelleft=False)
        main_ax.set_xlabel('X [pixel]')
        main_ax.set_ylabel('Y [pixel]')
        top_ax.set_ylabel('Z [m]')
        right_ax.set_xlabel('Z [m]')
        
        # Dimensions
        xvalues = np.linspace(-1,1,dem_data.shape[1])
        yvalues = np.linspace(-1,1,dem_data.shape[0])
        xx, yy = np.meshgrid(xvalues,yvalues)
        
        if interactive == True:
            cur_x = dem_data.shape[1] - 1
            cur_y = dem_data.shape[0] - 1
        else:
            cur_x = dem_data.shape[1] /2
            cur_y = dem_data.shape[0] /2
        
        # Data DEM
        dem_prof = dem_data.astype(float)
        dem_prof[dem_prof<0] = np.nan
        
        main_ax.imshow(
            np.ma.masked_array(dem_data, mask=(dem_data<0)),
            origin='lower', cmap='terrain', alpha=0.5
        )
        
        # Plot contour
        try:
            with rasterio.open(self.watershed.geographic.watershed_contour_tif) as src:
                cont = src.read(1)
            main_ax.imshow(np.ma.masked_where(cont<0, cont), cmap=mpl.colors.ListedColormap(['k']), interpolation='none')
        except Exception:
            logger.warning("No contour raster available for cross-section overlay")
            pass
        
        try:
            river_plot = np.ma.masked_array(river_data, mask=(river_data<=0))
            main_ax.imshow(river_plot, origin='lower', cmap=mpl.colors.ListedColormap('navy'), interpolation='none')
        except Exception:
            logger.warning("No river raster available for cross-section overlay")
            pass
        
        main_ax.invert_yaxis()
        
        # Data wt
        wt_prof = wt_data.astype(float)
        wt_prof[wt_prof<0] = np.nan
        
        # Scaling axis
        main_ax.autoscale(enable=False)
        right_ax.autoscale(enable=False)
        top_ax.autoscale(enable=False)
        
        dem_max = np.nanmax(dem_prof)  # Calculate the maximum dem value
        
        right_ax.set_xlim(np.nanmin(wt_prof), dem_max)
        top_ax.set_ylim(np.nanmin(wt_prof), dem_max)
        
        right_ax.set_ylim(0, dem_data.shape[0])
        right_ax.invert_yaxis()
        top_ax.set_xlim(0, dem_data.shape[1])
        
        v_line = main_ax.axvline(cur_x, color='k', lw=2)
        h_line = main_ax.axhline(cur_y, color='k', lw=2)
        
        # Create initial data
        lw = 1.5 if interactive else 1
        dem_v = dem_prof[:, int(cur_x)]; dem_v[dem_v==0] = np.nan
        wt_v = wt_prof[:, int(cur_x)]; wt_v[wt_v==0] = np.nan
        dem_h = dem_prof[int(cur_y), :]; dem_h[dem_h==0] = np.nan
        wt_h = wt_prof[int(cur_y), :]; wt_h[wt_h==0] = np.nan
        
        # Create initial plots
        dem_v_prof, = right_ax.plot(dem_v, np.arange(xx.shape[0]), c='saddlebrown', lw=lw)
        wt_v_prof, = right_ax.plot(wt_v, np.arange(xx.shape[0]), c='dodgerblue', lw=lw)
        dem_h_prof, = top_ax.plot(np.arange(xx.shape[1]), dem_h, c='saddlebrown', lw=lw)
        wt_h_prof, = top_ax.plot(np.arange(xx.shape[1]), wt_h, c='dodgerblue', lw=lw)
        
        # Store references to the fill collections
        water_fill_v = [right_ax.fill_betweenx(np.arange(xx.shape[0]), 0, wt_v,
                                color='deepskyblue', alpha=0.5, lw=0)]
        soil_fill_v = [right_ax.fill_betweenx(np.arange(xx.shape[0]), wt_v, dem_v,
                                color='saddlebrown', alpha=0.5, lw=0)]
        water_fill_h = [top_ax.fill_between(np.arange(xx.shape[1]), 0, wt_h,
                                color='deepskyblue', alpha=0.5, lw=0)]
        soil_fill_h = [top_ax.fill_between(np.arange(xx.shape[1]), wt_h, dem_h,
                                color='saddlebrown', alpha=0.5, lw=0)]
        
        plt.tight_layout()
        
        # Animation interactive
        def on_move(event):
            if event.inaxes is main_ax:
                try:
                    x, y = int(event.xdata), int(event.ydata)
                    
                    # Check bounds
                    if x < 0 or x >= dem_prof.shape[1] or y < 0 or y >= dem_prof.shape[0]:
                        return
                    
                    v_line.set_xdata([x, x])
                    h_line.set_ydata([y, y])
                    
                    # Extract new profile data
                    new_dem_v = dem_prof[:, x].copy()
                    new_wt_v = wt_prof[:, x].copy()
                    new_dem_h = dem_prof[y, :].copy()
                    new_wt_h = wt_prof[y, :].copy()
                    
                    new_dem_v[new_dem_v==0] = np.nan
                    new_wt_v[new_wt_v==0] = np.nan
                    new_dem_h[new_dem_h==0] = np.nan
                    new_wt_h[new_wt_h==0] = np.nan
                    
                    # Update line data
                    dem_v_prof.set_xdata(new_dem_v)
                    wt_v_prof.set_xdata(new_wt_v)
                    dem_h_prof.set_ydata(new_dem_h)
                    wt_h_prof.set_ydata(new_wt_h)
                    
                    # Remove old fill areas
                    for collection in water_fill_v + soil_fill_v + water_fill_h + soil_fill_h:
                        if collection in right_ax.collections or collection in top_ax.collections:
                            collection.remove()
                    
                    water_fill_v.clear()
                    soil_fill_v.clear()
                    water_fill_h.clear()
                    soil_fill_h.clear()
                    
                    # Create new fill areas
                    water_fill_v.append(right_ax.fill_betweenx(np.arange(xx.shape[0]), 0, new_wt_v,
                                    color='deepskyblue', alpha=0.5, lw=0))
                    soil_fill_v.append(right_ax.fill_betweenx(np.arange(xx.shape[0]), new_wt_v, new_dem_v,
                                    color='saddlebrown', alpha=0.5, lw=0))
                    water_fill_h.append(top_ax.fill_between(np.arange(xx.shape[1]), 0, new_wt_h,
                                    color='deepskyblue', alpha=0.5, lw=0))
                    soil_fill_h.append(top_ax.fill_between(np.arange(xx.shape[1]), new_wt_h, new_dem_h,
                                    color='saddlebrown', alpha=0.5, lw=0))
                    
                    # Force a redraw
                    fig.canvas.draw()
                    fig.canvas.flush_events()
                    
                except Exception as e:
                    pass
        
        if effective_interactive:
            cid = fig.canvas.mpl_connect('motion_notify_event', on_move)
        elif interactive:
            logger.warning("Matplotlib backend lacks interactivity; displaying static cross-section")
        
        # Save and display
        fig.savefig(os.path.join(
            self.watershed.simulations_folder, self.modelname,
            '_postprocess','_figures',
            f'CROSS_{self.modelname}.png'
        ))
        plt.show(block=effective_interactive)

        if backend_switched:
            plt.close(fig)
            try:
                plt.switch_backend(original_backend)
            except Exception:
                pass
#%% NOTES        
        
