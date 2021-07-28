Installation procedure

1-Install Anconda or Miniconda

2-Create conda environment
Open conda command window through anaconda navigator, for example
Go to this directory so that the following command finds the environment.yml file
Execute the command: conda env create -f environment.yml -n hydromodpy 
Check that environment exists: conda env list

3-Install ChromeDriver for Selenium library
Selenium is a library that manages interaction with files in the web
It requires the following file to be downloaded: https://chromedriver.chromium.org/downloads
The .exe should be stored in a file
The directory name of the file should be added to the user path of the environment variables (configuration pannel -> system -> variables)

4-Go into conda environment 
Execute in command window: activate hydromodpy
Check that libraries are installed: conda list

5-Go to Ipython Notebook
Go to folder of Ipython Notebook to run 
Execute: jupyter lab
Find and open notebook