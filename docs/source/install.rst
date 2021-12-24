Installation Procedure
======================

HydroModPy installation procedure

1. GitLab Repository
-----------------

Download HydroModPy from GitLab repository at this link
https://gitlab.com/Alex-Gauvain/HydroModPy/-/archive/master/HydroModPy-master.zip

2. Conda Environment
-----------------

2.1. Install Anaconda or Miniconda
********************************
Download and install at the following link:
https://docs.conda.io/en/latest/miniconda.html

2.2. Create conda environment
***************************

Open conda command window through anaconda navigator, for example.
Go to this directory so that the following command finds the environment.yml file

Execute the command: 

.. code-block::

	conda env create -f environment.yml -n hydromodpy 

The environment.yml file contains the following packages:

.. literalinclude:: ../../CORE_COMM/readme/environment.yml

Check that environment exists:

.. code-block::

    conda env list

2.3. Install ChromeDriver for Selenium library (Optional)
*******************************************************
| Optional : Only if you want recover automatically the data of watershed. Only for french data for the time being.
| Selenium is a library that manages interaction with files in the web
| It requires the following file to be downloaded:
| https://chromedriver.chromium.org/downloads
| The .exe should be stored in a local folder.
| The directory name of the file should be added to the user path of the environment variables ("configuration pannel" -> "system" -> "system parameter" -> "environment variables")
Click on "Path" -> "modify" -> "add path" of the .exe

2.4. Go into conda environment
****************************
Execute in command window: 

.. code-block::

	activate hydromodpy

Check that libraries are installed: 

.. code-block::

	conda list

2.5. Go to Ipython Notebook or Spyder
***********************************
Go to folder of Ipython Notebook or spyder to run 
Execute: 

.. code-block::

	jupyter lab 

or

.. code-block::

	spyder

Find, open and run notebook or script
