# Dem data
dem_data = BV.geographic.dem_data

# Wt data
wt_data = imageio.imread(simulations_folder+model_name+'/_extraction/'+'watertable_elevation_(000).tif') # buffer size no masked

# River data
river_data = imageio.imread(stable_folder+'/hydrology/'+'sections.tif')

# Function
plots.interactive_cross_section(dem_data, wt_data, river_data, interactive=False)