# Root Directory of Results
##Sarah
ROOT_DIRECTORY_RESULTS="C:\\DATA\\results\\PyAge\\"
#ROOT_DIRECTORY_RESULTS="C:\\Users\\Chinita\\Documents\\GitHub\\trac-2-age\\python\\results"

# Root Directory of Application
##Sarah
ROOT_DIRECTORY_SRC="C:\\DATA\\codes-github-public\\trac-2-age\\python\\sources\\"
#ROOT_DIRECTORY_SRC="C:\\Users\\Chinita\\Documents\\GitHub\\trac-2-age\\python"

# Directory of chemical data
DIRECTORY_TRACER_DATA =  ROOT_DIRECTORY_SRC + "tracer_data\\"

# Directory of test data
DIRECTORY_TEST = ROOT_DIRECTORY_SRC + "tests_data\\"

# Defaut Directory of lpm data
directory_lpm_data = ROOT_DIRECTORY_SRC + "LPM_data\\"

# Resolution of the quadrature for the evaluation of the convolution
RESOLUTION_CONVOLUTION = 200

# Reference organization of columns
REFERENCE_COLUMNS = ["element","concentration","error","unit","date"]
CONCENTRATION = REFERENCE_COLUMNS.index("concentration")
ERROR = REFERENCE_COLUMNS.index("error")
