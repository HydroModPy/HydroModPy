# coding:utf-8

import os

import geopandas as gpd
import gdal, osr
from shutil import copyfile

### Method 1
import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_verbose_mode(False)
### Method 2
# from WBT.whitebox_tools import WhiteboxTools
# wbt = WhiteboxTools()

class extract_watershed:
	def __init__(self, dem_path, outlet, snap_dist=150, buff_dist=1000, tmp_path=os.path.dirname(os.getcwd())+'\\tmp\\', 
                 save_dem=True, out_path=os.path.dirname(os.getcwd())+'\\output\\'):
		self.ws = os.getcwd()
		self.dem_path = dem_path 
		self.out_path = out_path
		self.tmp_path = tmp_path
		self.save_dem = save_dem
		self.fill = self.tmp_path + 'fill.tif'
		self.direc = self.tmp_path + 'direct.tif'
		self.acc = self.tmp_path + 'acc.tif'
		self.outlet_shp = self.tmp_path + 'outlet.shp'
		self.outlet_snap_shp = self.tmp_path + 'outlet_snap.shp'
		self.watershed_shp = self.tmp_path + 'watershed.shp'
		self.watershed_contour_shp = self.tmp_path + 'watershed_contour.shp'
		self.watershed = self.tmp_path + 'watershed.tif'
		self.watershed_fill = self.tmp_path + 'watershed_fill.tif'
		self.watershed_direc = self.tmp_path + 'watershed_direc.tif'
		self.buffer = self.tmp_path + 'buff.shp'
		self.watershed_buff = self.tmp_path + 'watershed_buff.tif'
		self.watershed_buff_fill = self.tmp_path + 'watershed_buff_fill.tif'
		self.watershed_buff_direc = self.tmp_path + 'watershed_buff_direc.tif'
		self.snap_dist = snap_dist
		self.buff_dist = buff_dist
		self.outlet = outlet
		self.generate_watershed_dem()

	def generate_watershed_dem(self):
		self.dem = gdal.Open(self.dem_path)
		proj = osr.SpatialReference(wkt=self.dem.GetProjection())
		self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1))
		wbt.fill_depressions(self.dem_path, self.fill)
		wbt.d8_pointer(self.fill, self.direc, esri_pntr=False)
		wbt.d8_flow_accumulation(self.fill, self.acc, log=True)
		df = self.outlet
		df.columns = ['id','x','y']
		gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['x'], df['y']), crs=self.crs)
		gdf.to_file(self.outlet_shp)
		wbt.snap_pour_points(self.outlet_shp, self.acc, self.outlet_snap_shp, self.snap_dist)
		wbt.watershed(self.direc, self.outlet_snap_shp, self.watershed, esri_pntr=False)
		wbt.raster_to_vector_polygons(self.watershed, self.watershed_shp)
		wbt.multi_part_to_single_part(self.watershed_shp, self.watershed_shp, exclude_holes=True)
		wbt.clean_vector(self.watershed_shp, self.watershed_shp)
		wbt.dissolve(self.watershed_shp, self.watershed_shp, field=None)
		wbt.polygons_to_lines(self.watershed_shp, self.watershed_contour_shp)
		site_polyg = gpd.read_file(self.watershed_shp)
		site_polyg['geometry'] = site_polyg.geometry.buffer(self.buff_dist)
		site_polyg.to_file(self.buffer)
		wbt.clip_raster_to_polygon(self.dem_path,self.buffer,self.watershed_buff)
		wbt.clip_raster_to_polygon(self.fill,self.buffer,self.watershed_buff_fill)
		wbt.clip_raster_to_polygon(self.direc,self.buffer,self.watershed_buff_direc)
		wbt.clip_raster_to_polygon(self.dem_path,self.watershed_shp,self.watershed)
		wbt.clip_raster_to_polygon(self.fill,self.watershed_shp,self.watershed_fill)
		wbt.clip_raster_to_polygon(self.direc,self.watershed_shp,self.watershed_direc)
		if self.save_dem == True:
			self.save_path = self.out_path + df.id.values[0]
			if not os.path.exists(self.save_path):
				os.makedirs(self.save_path)
			copyfile(self.watershed_fill, self.save_path + '\\' + df.id.values[0] + '_fill.tif')
		return self, os.chdir(self.ws)
	
# df = pd.DataFrame(np.reshape(np.asarray(self.outlet),(1,2)), columns=['x','y'])