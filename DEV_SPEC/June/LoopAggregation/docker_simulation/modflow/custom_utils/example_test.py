import os, sys
#lib_path = os.path.abspath(os.path.join(__file__, 'docker_simulation', 'modflow', 'custom_utils'))
#print(lib_path)
#sys.path.append(lib_path)

import InputFileManipulation




InputFileManipulation.generate_custom_input_file(model_name=None, approx=0, rate=5000, chronicle=12, steady=False)