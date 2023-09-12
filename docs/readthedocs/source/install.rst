HydroModPy Installation Procedure
======================

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
Open conda command window through anaconda navigator or command prompt (cmd).

Go to the folder where you want to install HydroModPy:

.. code-block::
    cd "path/where/you/want/clone/Hydromodpy"

Clone HydroModPy repository:

.. code-block::
    git clone https://gitlab.com/Alex-Gauvain/HydroModPy.git

Go to stable branch:

.. code-block::
    git checkout "v0.1"

Go to install folder:

.. code-block::
    cd HydroModPy/install

HydroModPy can be installed for Windows and Linux with bash file in the "install" directory :
For Linux :

.. code-block::
    ./install.sh


For Windows : double clik on install.sh

Or alternatively, HydroModPy can be installed with conda using .yml file in the "install" directory :

.. code-block::
    conda env create -f environment.yml -n hydromodpy 

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
    
Spyder advices:

The launch code is divided into different "blocks" visible on Spyder:
- Check the "Outline" option in View ==> Panes

Spyder and keyboard shortcuts:
- Run the script "block by block", using the "Run current cell" button
- “Ctrl + Enter" to run a block
- “Shift + Enter" to run and move on to the next block
- “F9" to run selected lines or 1 line only
- “Ctrl + 1": activates or deactivates the # in front of the line


Find, open and run notebook or script
