# Path to the git repositoty home page
git_path ="../../CORE_COMM/"
# Path to the test folder
test_path = os.path.join(git_path,"examples","_example")
# Path where the results will be stored
out_path = os.path.join(test_path,"readthedocs", "out")

# We suggest to store the data in specific folder
dems_path = os.path.join(test_path,'dem')
hydrology_path = os.path.join(test_path,'hydrology') # add hydrographic shapefiles
modflow_path = os.path.join(test_path,'modflow') # add bin/ folder with necessary .exe
climate_path = os.path.join(test_path,'climate')
piezometry_path = None # add piezometry data or nothing for automatic download
geology_path = None # add geologic layers
oceanic_path = None # add specific sea level files
# Specifically designed to process SURFEX data (France scale)
surfex_path =  None # add surfex models in .h5 format

# Indicate the name of the regional DEM
dem_name = "DEM_test_75m_LAMB93.tif"
# dem_name = "DEM_bzh_75m_LAMB93.tif"
dem_path = os.path.join(dems_path,dem_name)

dem = gdal.Open(dem_path)
proj = osr.SpatialReference(wkt=dem.GetProjection())
crs = int(proj.GetAttrValue('AUTHORITY',1))

# Import the library of watersheds to generate
library_path = test_path + 'watershed_library.csv' # each row is a study site
library = pd.read_csv(library_path, sep=';', header=0, engine='python') # explore catchment studied

# Select from the library the interest catchment
watershed_name = 'Watershed' # add manually study site information in map units
mysite = library[library['watershed_name'] == watershed_name] # specific row

# Paths generated automatically but necessary for plots
stable_folder = out_path+'/'+watershed_name+'/'+'results_stable/'
simulations_folder = out_path+'/'+watershed_name+'/'+'results_simulations/'

# Specify the hydrologic layers to clip
types_obs = ['streams','sections'] # list of shapefile name layers
fields_obs = ['FID','Persistanc'] # list of shapefile name columns to translate in a tif
