
import gdal, osr

class dem:
	def __init__(self, dem_path):
		self.dem_path = dem_path
		self.load_dem()
		self.extract_data()
		self.extract_geodata()
		self.extract_coord()

	def load_dem(self):
		self.dem = gdal.Open(self.dem_path)

	def extract_data(self):
		self.data = self.dem.GetRasterBand(1).ReadAsArray()

	def extract_geodata(self):
		self.geodata = self.dem.GetGeoTransform()
		self.resolution = abs(self.geodata[2])
		self.pixel = abs(self.geodata[1])

	def extract_coord(self):
		proj = osr.SpatialReference(wkt=self.dem.GetProjection())
		self.crs = 'EPSG:'+str(proj.GetAttrValue('AUTHORITY',1)) 
		self.xmin = self.geodata[0]
		self.xmax = self.geodata[0] + self.data.shape[1] * self.geodata[1]
		self.ymin = self.geodata[3] + self.data.shape[0] * self.geodata[5]
		self.ymax = self.geodata[3]
        





