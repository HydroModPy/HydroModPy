Installation Procedure
======================

HydroModPy installation procedure

GitLab Repository
-----------------

Download HydroModPy from GitLab repository at this link:
https://gitlab.com/Alex-Gauvain/HydroModPy/-/archive/master/HydroModPy-master.zip
Or clone it using Git:
https://gitlab.com/Alex-Gauvain/HydroModPy.git

Conda Environment
-----------------

Install Anaconda or Miniconda
********************************
Download and install at the following link:
https://docs.conda.io/en/latest/miniconda.html

Create conda environment
***************************

Open conda command window or command prompt (cmd) through anaconda navigator, for example.
Go to the directory (/cd HydroModPy/CORR_COMM/readme) so that the following command finds the environment.yml file

Execute the command: 

.. code-block::

	conda env create -f environment.yml -n hydromodpy 

The environment.yml file contains the following packages:

.. literalinclude:: ../../CORE_COMM/readme/environment.yml

Check that environment exists:

.. code-block::

    conda env list

Install ChromeDriver for Selenium library (Optional)
*******************************************************
| Optional : Only if you want recover automatically the data of watershed. Only for french data for the time being.
| Selenium is a library that manages interaction with files in the web
| It requires the following file to be downloaded:
| https://chromedriver.chromium.org/downloads
| The .exe should be stored in a local folder.
| The directory name of the file should be added to the user path of the environment variables ("configuration pannel" -> "system" -> "system parameter" -> "environment variables")
Click on "Path" -> "modify" -> "add path" of the .exe

Go into conda environment
****************************
Execute in command window: 

.. code-block::

	activate hydromodpy

Check that libraries are installed: 

.. code-block::

	conda list

Go to Ipython Notebook or Spyder
***********************************
Go to folder of Ipython Notebook or spyder to run 
Execute: 

.. code-block::

	jupyter lab 

or

.. code-block::

	spyder

Find, open and run notebook or script
