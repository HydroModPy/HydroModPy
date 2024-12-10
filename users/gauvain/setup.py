import sys, platform
import setuptools

with open('README.md', 'r') as file:
    long_desc = file.read()

setuptools.setup(
    name='HydroModPy',
    version='0.1',
    author='Alexandre Gauvain','Ronan Abhervé'
    author_email='alexandre.gauvain.ag@gmail.com','ronan.abherve@gmail.com'
    description='Hydrogeological modelling',
    long_description=long_desc,
    long_description_content_type='text/markdown',
    url = 'https://gitlab.com/Alex-Gauvain/HydroModPy',
    install_requires=[
                      'numpy==1.24.3',
                      'pandas==1.5.3',
                      'geopandas==0.12.2',
                      'matplotlib==3.7.1',
                      'GDAL==3.0.2',
                      'rasterio==1.2.10',
                      'deepdish==0.3.7',
                      'flopy==3.3.4',
                      'imageio==2.31.1',
                      'whitebox==2.3.1',
                      'vedo==2023.4.6',
                      'hydroeval==0.1.0',
                      'xarray==2023.1.0',
                      'netCDF4==1.6.4',
                      'matplotlib_scalebar==0.8.1',
                      'contextily==1.3.0',
                      'pyproj==3.5.0',
                      'selenium==4.10.0',
                      'pyshp==2.3.1',
                      'jupyter==1.0.0',
                      'spyder',
                      'notebook'],
    python_requires='==3.8.10',
    packages=setuptools.find_packages(),
    include_package_data=True,
    #data_files=[("lib\\site-packages\\ArchPy\\libraries", ["ArchPy\\libraries\\cov_facies.dll"])],
    license=open('LICENSE', encoding='utf-8').read()
)
