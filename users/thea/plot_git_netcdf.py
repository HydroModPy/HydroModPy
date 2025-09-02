#%% LIBRAIRIES
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
from datetime import datetime
from PIL import Image
import os
import rasterio
from matplotlib.colors import LinearSegmentedColormap
import numpy.ma as ma

def create_custom_colormap():
    """Crée une colormap personnalisée"""
    colors = [
        (0.0, (0.0, 0.0, 0.5)),      # Bleu foncé pour les valeurs très négatives
        (0.2, (0.0, 0.3, 0.8)),      # Bleu moyen
        (0.4, (0.0, 0.6, 0.3)),      # Vert
        (0.5, (1.0, 1.0, 1.0)),      # Blanc pour zéro
        (0.6, (0.9, 0.8, 0.2)),      # Jaune pâle
        (0.8, (0.8, 0.4, 0.0)),      # Orange
        (1.0, (0.5, 0.0, 0.0))       # Bordeaux
    ]
    return LinearSegmentedColormap.from_list('custom', colors)

def create_gif_from_netcdf(netcdf_file, dem_file, variable_name, output_gif, 
                          start_date=None, end_date=None,
                          vmin=-50, vmax=50,
                          fps=2):
    """
    Convertit un fichier NetCDF en GIF animé avec MNT en fond.
    
    Parameters:
    -----------
    netcdf_file : str
        Chemin vers le fichier NetCDF
    dem_file : str
        Chemin vers le fichier MNT (format GeoTIFF)
    variable_name : str
        Nom de la variable à visualiser
    output_gif : str
        Chemin pour sauvegarder le GIF
    start_date : str, optional
        Date de début au format 'YYYY-MM-DD'
    end_date : str, optional
        Date de fin au format 'YYYY-MM-DD'
    vmin, vmax : float, optional
        Valeurs min et max pour l'échelle de couleur
    fps : int, optional
        Frames par seconde pour le GIF
    """
    
    # Ouvre le fichier NetCDF
    ds = xr.open_dataset(netcdf_file)
    
    # Ouvre le MNT
    with rasterio.open(dem_file) as dem:
        dem_data = dem.read(1)
        dem_transform = dem.transform
        dem_extent = [dem.bounds.left, dem.bounds.right, 
                     dem.bounds.bottom, dem.bounds.top]
        nodata_value = dem.nodata
        
    # Masque les valeurs NoData
    dem_masked = ma.masked_where(dem_data == nodata_value, dem_data)
    
    # Sélectionne la période si spécifiée
    if start_date and end_date:
        ds = ds.sel(time=slice(start_date, end_date))
    
    # Crée un dossier temporaire pour les images
    temp_dir = 'temp_frames'
    os.makedirs(temp_dir, exist_ok=True)
    
    # Crée la projection Lambert-93
    proj_lamb93 = ccrs.LambertConformal(
        central_longitude=3.0,
        central_latitude=46.5,
        false_easting=700000,
        false_northing=6600000,
        standard_parallels=(44, 49)
    )
    
    # Crée la colormap personnalisée
    cmap = create_custom_colormap()
    
    frames = []
    
    # Créer une figure pour chaque pas de temps
    for i, time in enumerate(ds.time):
        fig = plt.figure(figsize=(12, 10))
        
        # Configure la projection cartographique
        ax = plt.axes(projection=proj_lamb93)
        
        # Affiche le MNT en fond avec une colormap en niveaux de gris
        ax.imshow(dem_masked, extent=dem_extent, transform=proj_lamb93,
                 cmap='gray', alpha=0.5, zorder=1)
        
        # Crée un maillage pour pcolormesh
        X, Y = np.meshgrid(ds.x, ds.y)
        
        # Trace les données avec masque pour les valeurs entre -100 et 100
        data = ds[variable_name].sel(time=time)
        masked_data = ma.masked_where((data > -100) & (data < 100), data)
        
        im = ax.pcolormesh(X, Y, masked_data,
                          transform=proj_lamb93,
                          vmin=vmin, vmax=vmax,
                          cmap=cmap,
                          alpha=0.7,
                          zorder=2)
        
        # Ajoute le... Lire la suite


# %%
