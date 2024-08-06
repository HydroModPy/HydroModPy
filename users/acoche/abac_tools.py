# -*- coding: utf-8 -*-
"""
Created on Mon Aug  5 21:00:23 2024

@author: coche
"""

#%% Imports
import pandas as pd
import numpy as np
import xarray as xr
xr.set_options(keep_attrs = True)
import os
import datetime

import cwatplot as cwp


#%% Correct NetCDF file using reference abaque
def correct(ref_abac_path, lake_nc_file, buffer_nc_file):
    """
    Example
    -------
    import abac_tools as abt
    abt.correct(ref_abac_path = r"D:\2- Postdoc\2- Travaux\1- Veille\1- Biblio locale\14- Barrage\bathymetrie Cheze\Courbe_Capacite_Retenue_CHEZE_2024.csv", 
                lake_nc_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\6- Lacs et reservoirs\Cheze\bathymetry\Cheze_bathy_1m_NGF-elevation_v2.nc", 
                buffer_nc_file = r"D:\2- Postdoc\2- Travaux\1- Veille\4- Donnees\6- Lacs et reservoirs\Cheze\bathymetry\Cheze_bathy_1m_NGF-elevation_v2enlarged.nc")

    Parameters
    ----------
    ref_abac_path : str
        Filepath to the reference abaque that will be used to correct the 
        bathymetric DEM of the lake.
    lake_nc_file : str
        Filepath to the bathymetric DEM of the lake that will be corrected.
    buffer_nc_file : str
        Filepath to the DEM of the area that will be used to compute the stored
        volume but will not be altered.

    Returns
    -------
    None.

    """
    
    
    # ---- Loading   
    print("Loading...")
    # Reference abaque
    ref_abac = pd.read_csv(ref_abac_path, delimiter='\t', names=['time', 'val'])
    # 'time' and 'val' are defaut names for plotting, but they mean here 'elevation' and 'volume'
    
    # Simplification (temp)
    ref_abac = ref_abac.reindex(index = [i for i in range(0, len(ref_abac), 10)])
    
    # Bathymetric DEM NetCDF to correct    
    with xr.open_dataset(lake_nc_file, decode_coords = 'all', 
                         decode_times = True) as lake_ds:
        lake_ds.load() # to unlock the resource
    
    # Extended DEM around lake (will not be altered)
    with xr.open_dataset(buffer_nc_file, 
            decode_coords = 'all', decode_times = True) as buffer_ds:
        buffer_ds.load() # to unlock the resource
    
    
    # ---- Modifs
    cell_area = abs(lake_ds.rio.resolution()[0] * lake_ds.rio.resolution()[1])
    
    # =============================================================================
    # elev_list = lake_ds.bathymetry.values.reshape(lake_ds.bathymetry.size)
    # elev_list = elev_list[np.isnan(elev_list)==False]
    # sort_elev_list = np.sort(elev_list)
    # 
    # for elev in sort_elev_list:
    #     vol = float((elev - lake_ds['bathymetry'].where(lake_ds.bathymetry <= elev)
    #                  ).sum()*cell_area)
    #     
    #     ref_vol = ref_abac[ref_abac.time <= 60].iloc[-1].val
    #     
    #     if vol < ref_vol:
    #         ncells = (lake_ds.bathymetry.values == elev).sum()
    #         lake_ds['bathymetry'].where(lake_ds.bathymetry != elev, elev - (ref_vol-vol)/(cell_area*ncells)) 
    #         print(elev, 'm')
    #         
    #     elif vol > ref_vol:
    #         ncells = (lake_ds.bathymetry.values == elev).sum()
    #         lake_ds['bathymetry'].where(lake_ds.bathymetry != elev, elev + (ref_vol-vol)/(cell_area*ncells))
    #         print(elev, 'm')
    # =============================================================================
    
    # Update area DEM with lake DEM:
# =============================================================================
#     lake_ds = lake_ds.reindex(x = buffer_ds.x, y = buffer_ds.y)
#     buffer_ds['bathymetry'] = buffer_ds.bathymetry.where(
#         lake_ds.bathymetry.isnull(), lake_ds.bathymetry)
# =============================================================================
    # buffer_ds = buffer_ds.update(lake_ds)
    
    # Creating the abaque for the previous lake_ds (for graphical verification)
    print("Generating the initial abac to correct...")
    old_abac = pd.DataFrame(index = ref_abac.index)
    old_abac['time'] = ref_abac.time
    for idx in old_abac.index:
        el = old_abac.loc[idx].time
        old_abac.loc[idx, 'val'] = float((el - buffer_ds['bathymetry'].where(buffer_ds.bathymetry <= el)
                     ).sum()*cell_area)
        print(f'\r   {el} m', end='\r')
    
    print("Correcting the DEM...")
    for a in range(0, 10):
        print(f"\n. Batch {a}/9")
        for idx in ref_abac.index:
            idx_up = min(idx+50, ref_abac.index[-1])
            elev_dn = ref_abac.loc[idx].time
            elev_up = ref_abac.loc[idx_up].time
            ref_vol = ref_abac.loc[idx_up].val - ref_abac.loc[idx].val
            
            vol = float((elev_up - buffer_ds['bathymetry'].where(buffer_ds.bathymetry <= elev_up)
                         ).sum()*cell_area) - \
                float((elev_dn - buffer_ds['bathymetry'].where(buffer_ds.bathymetry <= elev_dn)
                             ).sum()*cell_area)
            
            if vol != ref_vol:
                ncells = (buffer_ds.bathymetry.values <= elev_up).sum() - \
                    (buffer_ds.bathymetry.values <= elev_dn).sum()
                
                if ncells > 0:
                    # correc = 1*(vol-ref_vol)/(cell_area*ncells)
                    correc = (vol/ref_vol)**(1/10)
                else:
                    correc = 0
                buffer_ds['bathymetry'] = xr.where((buffer_ds.bathymetry >= elev_dn) & \
                                                 (buffer_ds.bathymetry <= elev_up), 
                                               # buffer_ds.bathymetry + correc, 
                                               buffer_ds.bathymetry * correc,
                                               buffer_ds.bathymetry) 
                print(f"   slice {elev_dn} - {elev_up} m : correction {correc}")
                  
            # Update area DEM with lake DEM:
# =============================================================================
#             buffer_ds['bathymetry'] = buffer_ds.bathymetry.where(
#                 lake_ds.bathymetry.isnull(), lake_ds.bathymetry)
# =============================================================================
            # buffer_ds = buffer_ds.update(lake_ds)
            
            vol_c = float((elev_up - buffer_ds['bathymetry'].where(buffer_ds.bathymetry <= elev_up)
                         ).sum()*cell_area) - \
                float((elev_dn - buffer_ds['bathymetry'].where(buffer_ds.bathymetry <= elev_dn)
                             ).sum()*cell_area)
            print(f"    ref_vol = {ref_vol} | prev vol = {vol} | corr vol = {vol_c}")
        
    # ---- Export
    print("Exporting...")
    export_path = os.path.splitext(buffer_nc_file)[0] + '_v5.nc'
    buffer_ds.to_netcdf(export_path)
    
    
    #%% Graphical verification
    print("Graphical verification...")
    # ---- Creating the abaque from corrected lake_ds
    print("   Generating the abac from the corrected DEM")
    res = pd.DataFrame(index = ref_abac.index)
    res['time'] = ref_abac.time
    for idx in res.index:
        el = res.loc[idx].time
        res.loc[idx, 'val'] = float((el - buffer_ds['bathymetry'].where(buffer_ds.bathymetry <= el)
                     ).sum()*cell_area)
        print(f'\r   {el} m', end='\r')
    
    # ---- Parameters
    _cmap_catalog = [
        [1.000, 0.500, 0.000, 0.9],  # 0. orange
        [0.980, 0.691, 0.168, 0.9],  # 1. orange-jaune (pour *.html)
        [0.973, 0.392, 0.420, 0.9],  # 2. orange-rose
        [0.847, 0.000, 0.035, 0.9],  # 3. rouge royal
        [0.471, 0.000, 0.118, 0.9],  # 4. blackred
        [1.000, 0.557, 0.827, 0.9],  # 5. rose bonbon
        [0.949, 0.000, 0.784, 0.9],  # 6. fuschia
        [0.655, 0.204, 0.886, 0.9],  # 7. pourpre
        [0.404, 0.059, 0.902, 0.9],  # 8. violet fugace
        [0.000, 0.000, 0.470, 0.9],  # 9. bleu marine - noir
        [0.000, 0.318, 0.910, 0.9],  # 10. bleu
        [0.000, 0.707, 0.973, 0.9],  # 11. bleu ciel
        [0.000, 0.757, 0.757, 0.9],  # 12. bleu-vert émeraude
        [0.625, 0.777, 0.027, 0.9],  # 13. vert
        [0.824, 0.867, 0.141, 0.9],  # 14. vert-jaune (ou l'inverse)
        [1.000, 0.784, 0.059, 0.9],  # 15. jaune-orangé
        [1.000, 0.941, 0.059, 0.9],  # 16. jaune
        [0, 0, 0, 1],                # 17. noir
        [0.37, 0.37, 0.37, 1],       # 18. gris sombrero
        [0.70, 0.70, 0.70, 1],       # 19. gris clairero
        ]
    color_map = np.array(_cmap_catalog)[[14, 0, 11, 8, 12, 10, 13, 18,], :]

    # ---- Figure
    [_, _, figweb] = cwp.plot_time_series(
        dataframes = [ref_abac, 
                      old_abac,
                      res], 
        labels = ['Abaque de référence EBR', 
                  'abaque simulée (v2)',
                  'abaque simulée corrigée (v5)'], 
        title = 'Comparaison des abaques Chèze', 
        # figweb = figweb,
        color_map = color_map, # cumul = False, 
        lstyle = ['-', '--', '--'],
        # date_ini_cumul = None, reference = None,
        # ref_norm = None, mean_norm = False, 
        # mean_center = False
        # legendgroup = "group" + str(c),
        # legendgrouptitle_text = f"{shortnames[1]}={p1val}",
        )

    y_text = "Volume [m3]"

    #%%% Formating the *.html plot (figweb)
    # ------------------------------------
    figweb.update_layout(#font_family = 'Open Sans',
    # =============================================================================
    #                            title = {'font': {'size': 20},
    #                                     'text': f"{shortnames[2]}={p2val}",
    #                                     'xanchor': 'center',
    #                                     'x': 0.5,
    #                                     },
    # =============================================================================
                       # annotations = {'xanchor': 'middle',
                       #                'yanchor': 'top',
                       #                'size': 20,
                       #                'text': add_title + "\nK = 5e-6 m/s   Poro = 0.1%   e = 25 m"},
                       xaxis = {'title': {'font': {'size': 16},
                                          'text': 'Elevation [m]'},
                                # 'range': dates_lim,
                                },
                       yaxis = {'title': {'font': {'size': 16},
                                           'text': y_text},
                                          # 'text': field_title + ' [m3/s]'},
                                # 'type': yscale,
                                # 'range': _ylim_figweb,
                                },
                       legend = {'title': {'text': 'Légende'},
                                 'xanchor': 'left',
                                 'y': 0.9,
                                 'yanchor': 'top',
                                 # 'groupclick': 'toggleitem',
                                 },
                       plot_bgcolor = "white",
                       # legend = {'groupclick': 'togglegroup'},
                       width = 800,
                       height = 700,
                       )

    #%%% Export to *.html  
    fig_path = os.path.splitext(lake_nc_file)[0] + '_v5_' \
        + datetime.datetime.now().strftime("%Y-%m-%d_%Hh%M") + '.html'
    
    figweb.write_html(fig_path)

    