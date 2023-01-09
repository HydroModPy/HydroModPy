# -*- coding: utf-8 -*-
"""
Created on Sat Jan  7 16:08:40 2023

@author: jdedreuz
"""

# -*- coding: utf-8 -*-
"""


"""

from copy import deepcopy
from enum import Enum 


# lxml :  more efficient and convenient (implements XPath), 
#         but somewhat less general than xml.etree.ElementTree
#         lxml shoul be installed with conda install
import lxml.etree  


class EXPLOPT(Enum): 
    """
    Options of exploration of XML file 
    """
    FIND = 1
    REPLACE = 2
    DIFF = 3 


def list_to_string(path): 
    """ 
    translates list to string with '::'
    """
    res = ''
    for p in path : 
        res = res + p + '::' 
    # Removes the last '::' and returns 
    return res[:-2]


def string_to_list(path): 
    """ 
    translates list to string with '::'
    """
    return path.split("::")


def file_exist(file_name):
    try:
        with open(file_name): pass
        return True
    except IOError:
        print ('Erreur! Le fichier ', file_name, ' n\'a pas pu être ouvert')
        return False
        

class Parameter: 
    """  
    Parameter structure 

    Attributes, public
    ----------
    path : list of strings
        path of parameter within the XML structure 

    Attributes, private
    ----------
    xml : lxml.etree
        loaded xml (from file)
    
    current_path : string
        current path of current xml root 
    
    Methods (principal)
    -------
    __init__(self, path, parameter_xml)
        Constructor: constructs xml from parameter structure
    get(self): 
        Gets parameter value with the right type of value 
    
    """

    def __init__(self, path, parameter_xml):
        """
        Initialization from xml parameter structure 

        Parameters
        ----------
        path : list of strings
            path of parameter 
        parameter_xml : XML parameter structure
            XML structure from which parameter should be initialized

        """
        self.path = path
        self.value = parameter_xml.find('value').text
        self.name = parameter_xml.get('name')
        self.description = parameter_xml.find('description').text
        self.type = parameter_xml.find('type').text
        self.default_value = parameter_xml.find('default_value').text
        
        
    def get_value(self): 
        """ 
        Gets parameter value 
        
        Returns
        ------
        Parameter value with the right type 
        """
        if self.type == 'bool': 
            return bool(int(self.value))
        elif (self.type == 'string'): 
            return str (self.value)
        elif (self.type == 'double'): 
            return float (self.value)
        else: 
            return eval(self.type) (self.value)
    
    def set_value(self,value):
        """ 
        Sets parameter value 
        
        """
        self.value = value
    
    
    def display(self): 
        """ 
        Displays the parameter 
        
        """
        print(list_to_string(self.path)+'::'+self.name, '\t', self.get_value()) 
    
        
        

class ParametersGroup: 
    """
    ParametersGroup structure loading XML files  


    Attributes, public
    ----------
    file_name : string
        file_name from which xml file has been read

    Attributes, private
    ----------
    xml : lxml.etree
        loaded xml (from file)
    
    current_path : string
        current path of current xml root 
    
    Methods (principal)
    -------
    __init__(file_name)
        Constructor:loads xml from file 
    
    """

    def __init__(self,file_name):
        """
        ParametersGroup Constructor from an XML file
        
        Args:
            file_name: string
                file name to be read
        """
        self.file_name = file_name
        if (file_exist(file_name)):
            # Loads file 
            xml = lxml.etree.parse(file_name)
            #JR:TODO Should check the format of the XML with the corresponding DTD
            # Gets the root of the tree structure 
            self.root = xml.getroot()
            # Sets current path to the name of the ParametersGroup
            self.current_path = [self.root.get('name')]
        else: 
            self.root = None
            self.current_path = None 
            
            
    def exists(self): 
        """ 
        Tests if ParametersGroup is correctly loaded and formatted
        
        Returns 
        -------
        True or False
        """
        return self.root != None 
    
    
    def getgroup(self,group_name,option_copy=False):
        """
        Gets the subgroup of name "group_name" as a direct descendant
        
        Args: 
        ----------
        group_name : string
            Name of the Group
   
        Returns
        -------
        exists : bool 
            existence of the subgroup
        subgroup : ParametersGroup
            the subgroup 
        option_copy : string
            True : deep copy of the result
            False : address (pointer) to the result
   
        """
        # Gets the hierarchical levels to explore to get the targeted group
        path_temp = string_to_list(group_name)
        if not bool(path_temp) : 
            exists = False
        else :
            root = self.root
            current_path = self.current_path
            for level in path_temp: 
                # Gets child of ParametersGroup identified by its name
                temp = root.xpath('ParametersGroup[@name="'+level+'"]')
                if(bool(temp)): 
                    root = temp[0]
                    current_path.append(root.get('name'))
                    exists = True
                else: 
                    exists = False
                    break

        # Prepares ParametersGroup structure to return 
        if(exists): 
            if option_copy : 
                subgroup = deepcopy(self)
            else : 
                subgroup = self
            subgroup.root = root
            subgroup.current_path = current_path  
            # print(subgroup.root.tag, '\t', subgroup.root.get('name')) 
        else: 
            subgroup = None 
            print('ParametersGroup ', group_name, ' not found')

        return exists, subgroup
    
    
    def getparam(self,param_name): 
        """
        Gets the parameter of name "param_name" as a direct descendant
        
        Args: 
        ----------
        param_name : string
            Name of the Parameters
   
        Returns
        -------
        exists : bool 
            existence of the subgroup
        param : Parameter
            the parameter 
   
        """
        # Gets child of ParametersGroup identified by its name
        temp = self.root.xpath('Parameter[@name="'+param_name+'"]')
        
        exists = bool(temp)
        if(exists): 
            param = Parameter(self.current_path, temp[0])
            # param.display()
        else: 
            param = None
            print('Parameter ', param_name, ' not found in direct descendants')
        
        return exists, param
    
    
    def set_default_value(self): 
        """
        Exploration all parameters and set default values to those of not defined field "value"
        """
        # Stores the name of the not defined values 
        undefined = []
        # Explores all "Parameter" in the XML tree with .//Parameter identification 
        for param in self.root.iterfind('.//Parameter'): 
            value = param.find('value').text
            if bool(value) == False : 
                undefined.append(param.attrib['name'])
                # Sets Parameter Value 
                param.find('value').text = param.find('default_value').text
        print('List of not defined values replaced by their default values\n', undefined, '\n')
        # print(i.tag, '\t', i.text)


    def write(self, file_name): 
        """
        Exports ParametersGroup to file_name
        
        Args
        ----
        file_name : string
            output to the file of name "file_name"
        
        """
        et=lxml.etree.ElementTree(self.root)
        et.write(file_name,pretty_print=True)
        
    
    @staticmethod
    def exploration_recursive(usr, ref, func, func_param1=None, func_param2=None, level=0, path=''):
        """
        Template recursive exploration of XML structure
            function 'func' to apply to each of the Parameter
            All Parameter are explored as terminal nodes of the ParameterGroup    
            usr is not modified (in no case)
            ref will be modified    

        Parameters
        ----------
        usr : XML derived structure
            Structure over which structure is explored
            usr will be recursively modified to point to all parts of the xml (ParametersGroup & Parameters)
        ref : ParametersGroup (instance of class)
            Structure that will be modified to give the merged structure
        func : function 
            Function that should be applied to modify ref 
        level : int
            Depth of the reccurence
            The default starting value is 0.
        path : string
            name of the path within the xml structure of the current location
            The default strating value is ''.
        func_param1 : to be defined by 'func'
            First parameter of function 'func'
        func_param2 : to be defined by 'func' 
            Second parameter of function 'func'

        Modifies
        -------
        ref : PatrametersGroup
            Reference ParametersGroup is modified with the values of usr 

        """
        # Updates path name to the current location within the xml structure
        if(usr.get('name') != None):
            path.append(usr.get('name'))
        # Recursive exploration of the Subgroups of current node 
        if(usr.tag == 'ParametersGroup'): 
            for child in list(usr):
                ParametersGroup.exploration_recursive(child, ref, func, func_param1, func_param2, level+1, path)
        # Application of function 'func' to the parameters
        if(usr.tag == 'Parameter'): 
            func(ref,usr,path,func_param1,func_param2)  
        # Updates path name when getting up (echo of the first instruction)
        #   Placed here, it ensures that we have as much removes as appends
        del path[-1]
        # print(level, '\t', list_to_string(path))

        
    @staticmethod
    def find_and_replace_param(pgroup,param,path,option,not_in_ref): 
        """
        Finds Parameters of name param.name in pggroup and performs function given by 'explot' options
            replaces its value with the param value
            "pgroup[param.name].value=param.value"

        Parameters
        ----------
        pgroup : ParametersGroup
            XML structure that will be modified
        param : XML node
            value of parameter that will be used to modify pggroup
        param_path : string (---::---::----)
            path of parameter within the XML structure
        options : enum ('explot')
            options of function 
            1: only finds
            2: finds and replaces
            3: finds, takes the difference and replaces value by the difference 

        Returns
        -------
        success : bool 
            True  : Parameter has been found and is modified 
            False : Parameter has not been found or cannot be modified 
        Modified pg_group 
        
        """
        # print(list_to_string(path),'\n')
        
        # FIND: Gets adress of parameter 
        if path[0] != pgroup.get('name') : 
            exists = False
        else: 
            # root : pointer to the current location of the xml structure within the exploration to the Parameter location
            root = pgroup
            # iterative exploration of ParametersGroup in pgroup along path
            for count, level in enumerate(path[1:]): 
                if(count==len(path)-2) : tag = 'Parameter' 
                else : tag = 'ParametersGroup'
                # Gets child of current node identified by its name "level"
                temp = root.xpath(tag+'[@name="'+level+'"]')
                exists = bool(temp)
                if(exists): 
                    root = temp[0]
                else: 
                    break
        
        # PROCESS: find report (if negative), replace, difference, 
        if exists :
            if option == EXPLOPT.REPLACE : 
                # Replaces value of pgroup at the right position pointed by root by the value of param
                root.find('value').text = param.find('value').text
            elif option == EXPLOPT.DIFF : 
                # Takes the difference of the values 
                root.find('value').text = param.find('value').text - root.find('value').text
        else : 
            # Whatever the option, this 'error' structure will be filled and reported
            not_in_ref.append(list_to_string(path))

            
    @staticmethod
    def explore_and_process(file_ref, file_user, option): 
        """
        Compares Refeference Parameters (file_ref) with User Parameters (file_usr)

        Parameters
        ----------
        file_ref : string
            File of the reference parameters
        file_user : string
            File of the user parameters
        option : EXPLOPT
            process option: FIND, REPLACE or DIFF

        Returns
        -------
        pg_result : ParametersGroup
            Merged ParametersGroup
        not_in_ref : list of strings
            Elements in user file but not in reference file

        """
        # Loads reference and user ParametersGroup
        pg_ref = ParametersGroup(file_ref)
        pg_usr = ParametersGroup(file_user)
        # Resulting ParamemetersGroup is separated from the reference ParametersGroup
        pg_res = deepcopy(pg_ref)
        
        # Elements in user file but not in reference file
        not_in_ref = []
        # Compares the two ParametersGroup, pg_res may be modified with the values of the 'usr' (REPLACE) or with the difference between both (DIFF)
        ParametersGroup.exploration_recursive(pg_res.root, pg_usr.root, ParametersGroup.find_and_replace_param, option, not_in_ref, level=0, path=[])
        
        # Output report 
        return pg_res, not_in_ref


    @staticmethod
    def test_load_and_get():
        # Tests Load ParametersGroup
        success = True 
        file_short = 'test_short(PARADIS).xml'
        paramgroup_short = ParametersGroup(file_short)
        file_extensive = 'test_extensive(PARADIS).xml'
        paramgroup_extensive = ParametersGroup(file_extensive)
        if not paramgroup_short.exists() or not paramgroup_extensive.exists() : 
            success = False 
            if not paramgroup_short.exists(): 
                print('ParametersGroup not loaded, probably a pb of file locations for file ', file_short)
            if not paramgroup_extensive.exists(): 
                print('ParametersGroup not loaded, probably a pb of file locations for file ', file_short)
        else: 
            # --------------------------------
            # Tests on test_short(PARADIS).xml
            # --------------------------------
            
            # Test Explores Parameters and set default values to the undefined values
            paramgroup_short.set_default_value()
            
            # Test gets subgroup
            exists, subgroup = paramgroup_short.getgroup('simulation')
            if exists : exists, subgroup = subgroup.getgroup('grid')
            if exists : exists, subgroup = subgroup.getgroup('output')
            
            if not exists : 
                print('ERROR for ParametersGroup::get on test_extensive(PARADIS).xml file processing')
            else: 
                # Test gets parameter
                if exists : exists, param = subgroup.getparam("nodes_position")
                    
                if not exists or param.get_value()!=False : 
                    success = False
                    print('ERROR for Parameter::get or Parameter::get on test_short(PARADIS).xml file processing')

            # --------------------------------
            # Tests on test_extensive(PARADIS).xml
            # --------------------------------

            # Test gets subgroup
            exists, subgroup = paramgroup_extensive.getgroup('run_global::run_general::outputs')
            # Test gets parameter
            if not exists : 
                print('ERROR for ParametersGroup::get on test_extensive(PARADIS).xml file processing')
            else : 
                exists, param = subgroup.getparam("directory_prefix")
                if param.get_value() != 'RUN1001': 
                    success = False 
                    print('ERROR for Parameter::get on test_extensive(PARADIS).xml file processing')
            
            if(success): 
                print('SUCCESS Test Loads and Gets Parameter and ParametersGroup')
            
        
    
    @staticmethod
    def test_merge_and_diff(): 
        file_ref = 'PARADIS_reference.xml'
        file_usr = 'PARADIS_user.xml'
        
        # Replace user Parameters in reference Parameters to get fully functional Parameter file
        option = EXPLOPT.REPLACE
        pg_res, not_in_ref = ParametersGroup.explore_and_process(file_ref, file_usr, option)
        # Outputs in file 
        pg_res.write('PARADIS_merged.xml')
        # Elements in reference but not in user file 
    
    
    
if __name__ == "__main__":
    
    # Tests simple on ParametersGroup and Parameter
    ParametersGroup.test_load_and_get()    
    
    # Tests advanced on merge and differences operations 
    ParametersGroup.test_merge_and_diff()
    
    