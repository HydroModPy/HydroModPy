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
import sys
import os


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
    DIFF_FLOAT = 4


def list_to_string(path, sep='::'): 
    """ 
    translates list to string with '::'
    """
    res = ''
    for p in path : 
        res = res + p + sep 
    # Removes the last '::' and returns 
    return res[:-len(sep)]


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
    
    
def folder_of_file_new(file_name,folder_new): 
    """
    Parameters
    ----------
    file_name : str
        full file name including folder '../../test/parameter.xml'
    folder_new : str
        new folder for file name 

    Returns
    -------
    str : 'folder_new/parameter.xml'

    """
    # Gets file_name without the folder
    pos = file_name.rfind(os.sep)
    if pos != -1 : 
        file_name = file_name[pos+1:]
    # Creates folder if it does not exsit
    make_dir(folder_new)
    return os.path.join(folder_new,file_name)


def make_dir(folder): 
    "Creates folder if does not exist"
    if os.path.exists(folder) == False : 
        os.makedirs(folder)

    
def xml_pre_adder(filename):
    line1 = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    line2 = '<?xml-stylesheet type="text/xsl" href="browser_view.xslt"?>\n'
    line3 = '<?xmlspysps authentic_view.sps?>\n'
    
    with open(filename, 'r+') as file:
       content = file.read()
       file.seek(0)
       file.write(line1 + line2 + line3 + content)
        
       
def test_floatable(type_): 
    """ Tests if type_ is amenable to operation '-'"""
    if type_ == 'float' or type_ == 'double' or type_ == 'int' or type_ == 'short' or type_ == 'bool' : 
       return True 
    else : 
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
        
        
    def getvalue(self): 
        """ 
        Gets parameter value 
        
        Returns
        ------
        Parameter value with the right type 
        """
        if self.type == 'bool': 
            if self.value == 'False' or self.value == '0': 
                return bool(0)
            elif self.value == 'True' or self.value == '1': 
                return bool(1)
            else : 
                print('error parameter', self.name, 'should be a boolean')
                sys.exit(0)
        elif (self.type == 'string'): 
            return str (self.value)
        elif (self.type == 'double'): 
            return float (self.value)
        else: 
            return eval(self.type) (self.value)
    
    def setvalue(self,value):
        """ 
        Sets parameter value 
        
        """
        self.value = value
    
    
    def display(self): 
        """ 
        Displays the parameter 
        
        """
        print(list_to_string(self.path)+'::'+self.name, '\t', self.getvalue()) 
        
        

    @staticmethod
    def comparison(param,value,option): 
        """
        Replaces parameter
            compares param.value with value

        Parameters
        ----------
        param : XML (Parameter)
            XML structure that will be modified
        value : 'string'
            value to which pgroup[param.name] will be compared 
        options : enum ('explot')
            options of function 
            1: only finds
            2: finds and replaces
            3: puts the two values
            4: finds, takes the difference and replaces value by the difference (floats)

        Returns
        -------
        success : bool 
            True  : Parameter has been found and is modified 
            False : Parameter has not been found or cannot be modified 
        
        """
        
        if option == EXPLOPT.REPLACE : 
                param.find('value').text = value 
        elif option == EXPLOPT.DIFF : 
            # Reports both values if differences 
            if param.find('value').text != value :
                param.find('value').text = 'USR=' + param.find('value').text + ' # REF=' + value
            else : 
                param.find('value').text = 'Identical'
        elif option == EXPLOPT.DIFF_FLOAT : 
            # Takes the difference of the values 
            if test_floatable(param.find('type')): 
                if bool(param.find('value').text) and bool(param.find('value').text):
                    param.find('value').text = str(float(param.find('value').text) - float(value))
                else :
                    param.find('value').text = 'DIFF Ref empty'
            else : 
                param.find('value').text = 'NOT COMPARABLE'


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
            parser = lxml.etree.XMLParser(attribute_defaults=True)
            xml = lxml.etree.parse(file_name,parser)
            #JR:TODO Should check the format of the XML with the corresponding DTD
            # Gets the root of the tree structure 
            self.root = xml.getroot()
            # Sets current path to the name of the ParametersGroup
            self.current_path = [self.root.get('name')]
            # Complements XML file
            self.set_default_value()
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
    
    
    def getgroup_safe(self,group_name,option_copy=False):
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
            current_path = deepcopy(self.current_path)
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
            print('ParametersGroup not found : ', group_name, 'in ', list_to_string(self.current_path))

        return exists, subgroup


    def getgroup(self,group_name):
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
        if group_name.find('::') == -1: 
            exists, subgroup = self.getgroup_safe(group_name,option_copy=True)
        else: 
            groups = string_to_list(group_name)
            subgroup = self
            for i in groups[:-1]: 
                subgroup = subgroup.getgroup(i)
                
        return subgroup

    
    
    def getparam_safe(self,param_name): 
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
            print('Parameter not found : ', param_name, ' in ', list_to_string(self.current_path))
        
        return exists, param
    
    
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
        
        if param_name.find('::') == -1: 
            exists, param = self.getparam_safe(param_name)
        else: 
            groups_param = string_to_list(param_name)
            pg = self
            for i in groups_param[:-1]: 
                pg = pg.getgroup(i)
            exists, param = pg.getparam_safe(groups_param[-1])
        return param
    
    
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
        # print('List of not defined values replaced by their default values\n', undefined, '\n')
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
        xml_pre_adder(file_name)

            
    def find_param(self,path): 
        """
        Finds Parameters of path in pggroup 

        Parameters
        ----------
        pgroup : ParametersGroup
            XML structure where param should be found
        path : list of strings
            path of parameter within the XML structure

        Returns
        -------
        exists : bool 
            True  : Parameter has been found and is modified 
            False : Parameter has not been found or cannot be modified 
        """
        # FIND: Gets adress of parameter 
        if path[0] != self.root.get('name') : 
            exists = False
        else: 
            # root : pointer to the current location of the xml structure within the exploration to the Parameter location
            root = self.root
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
        if exists: 
            return exists, root.find('value').text
        else : 
            return exists, ''
        

    def find_and_replace_param(self,path,new_value): 
        """
        Finds Parameters of path in pggroup and replaces it with 'new_value'

        Parameters
        ----------
        pgroup : ParametersGroup
            XML structure where param should be found
        path : list of strings
            path of parameter within the XML structure
        new_value : 
            new value of the parameter

        Returns
        -------
        exists : bool 
            True  : Parameter has been found and is modified 
            False : Parameter has not been found or cannot be modified 
        """
        # FIND: Gets adress of parameter 
        if path[0] != self.root.get('name') : 
            exists = False
        else: 
            # root : pointer to the current location of the xml structure within the exploration to the Parameter location
            root = self.root
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
        if exists: 
            root.find('value').text = str(new_value)
                    

    @staticmethod
    def exploration_recursive(ref, usr, func, options=EXPLOPT.FIND, not_in_ref=[], level=0, path=[]):
        """
        Template recursive exploration of XML structure
            function 'func' to apply to each of the Parameter
            All Parameter are explored as terminal nodes of the ParameterGroup    
            usr is not modified (in no case)
            ref will be modified    

        Parameters
        ----------
        ref : XML derived structure 
            Structure that will be modified to give the merged structure
            XML file with all parameters 
            XML that will be modified with the resulting value
        usr : ParametersGroup
            Structure which is explored to point to all parts of the xml (ParametersGroup & Parameters)
            usr will not be modified 
        func : function 
            Function that should be applied to modify ref 
        options : OPT
            First parameter of function 'func'
        not_in_ref : list of strings 
            Parameters which are in ust but not in ref
        level : int
            Depth of the reccurence
            The default starting value is 0.
        path : list of strings
            name of the path within the xml structure of the current location
            The default strating value is [].

        Modifies
        -------
        ref : PatrametersGroup
            Reference ParametersGroup is modified with the values of usr 

        """
        
        path.append(ref.get('name'))
        # Recursive exploration of the Subgroups of current node 
        if(ref.tag == 'ParametersGroup'): 
            for child in list(ref):
                ParametersGroup.exploration_recursive(child, usr, func, options, not_in_ref, level+1, path)
        # Application of function 'func' to the parameters
        if(ref.tag == 'Parameter'): 
            exists, value = usr.find_param(path)
            if exists : 
                func(ref,value,options)
                # ref.find('value').text = value 
            else : 
                not_in_ref.append(list_to_string(path))
        del path[-1]
            


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
        
        if pg_usr.root==None or pg_ref.root==None: 
            print('User parameter not well defined : ', file_user)
        else: 
            # Compares the two ParametersGroup, pg_res may be modified with the values of the 'usr' (REPLACE) or with the difference between both (DIFF)
            ParametersGroup.exploration_recursive(pg_res.root, pg_usr, Parameter.comparison, option, not_in_ref, level=0, path=[])
        
        # Output report 
        return pg_res, not_in_ref


    @staticmethod
    def merge_diff(file_ref,file_usr,options,folder_res=''): 
        """
        Loads xml files and choose valus of file_usr first, 
                               and values of file_ref by default  

        Parameters
        ----------
        file_ref : str
            File of reference data 
        file_usr : str
            File of user data, chosen first 
        options : EXPLOPT
            merge, diff or diff_float

        Returns
        -------
        pgroup : ParametersGroup
            Results of merged ParametersGroup 
        ref_not_usr : list of str
            Elements in reference file and not in user file
        usr_not_ref : list of str
            Elements in user file and not in reference file
        success : str
            Message on the error or success of the function 
        """

        # Replace user Parameters in reference Parameters to get fully functional Parameter file
        pg_res, usr_not_ref = ParametersGroup.explore_and_process(file_ref, file_usr, options)
        # Replace user Parameters in reference Parameters to get fully functional Parameter file
        ref_not_usr = ParametersGroup.explore_and_process(file_usr, file_ref, EXPLOPT.FIND)[1]
        
        if pg_res.root == None : 
            print('Reference ParametersGroup not loaded, Application cannot go further')
            sys.exit()
        
        # Outputs in file
        if   options == EXPLOPT.REPLACE : append = 'merge'
        elif options == EXPLOPT.DIFF  : append = 'diff_report'
        elif options == EXPLOPT.DIFF_FLOAT  : append = 'diff_float'
    
        # Outputs 
        file_name = folder_of_file_new(file_ref[:-4] + '_' + append,folder_res)
        pg_res.write(file_name + '.xml')
        with open(file_name + '.txt', 'w') as fp: 
            fp.write('usr_not_ref\n'); fp.write('\n'.join(usr_not_ref)); fp.write('\n') 
            fp.write('ref_not_usr\n'); fp.write('\n'.join(ref_not_usr))
        # Returns
        return pg_res, ref_not_usr, usr_not_ref
    
    
    @staticmethod
    def test_load_and_get():
        # Tests Load ParametersGroup
        success = True 
        file_short = '../test_parameters/test_short_ref(PARADIS).xml'
        paramgroup_short = ParametersGroup(file_short)
        file_extensive = '../test_parameters/test_extensive_ref(PARADIS).xml'
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
            exists, subgroup = paramgroup_short.getgroup_safe('simulation')
            if exists : exists, subgroup = subgroup.getgroup_safe('grid')
            if exists : exists, subgroup = subgroup.getgroup_safe('output')
            
            # Test find and replace
            path = ["PARADIS_inputs","simulation","tracker","nb_step_by_mesh"]
            newvalue = str('34')
            exists1 = paramgroup_extensive.find_and_replace_param(path,newvalue)
            exists2,retrievedvalue = paramgroup_extensive.find_param(path)
            if not exists1 or not exists2 or newvalue != retrievedvalue : 
                print('ERROR for find_and_replace method')
            
            if not exists : 
                print('ERROR for ParametersGroup::get on test_extensive(PARADIS).xml file processing')
            else: 
                # Test gets parameter
                if exists : exists, param = subgroup.getparam_safe("nodes_position")
                    
                if not exists or param.getvalue()!=False : 
                    success = False
                    print('ERROR for Parameter::get or Parameter::get on test_short(PARADIS).xml file processing')

            # --------------------------------
            # Tests on test_extensive(PARADIS).xml
            # --------------------------------

            # Test gets subgroup
            exists, subgroup = paramgroup_extensive.getgroup_safe('run_global::run_general::outputs')
            # Test gets parameter
            if not exists : 
                print('ERROR for ParametersGroup::get on test_extensive(PARADIS).xml file processing')
            else : 
                exists, param = subgroup.getparam_safe("directory_prefix")
                if param.getvalue() != 'RUN1001': 
                    success = False 
                    print('ERROR for Parameter::get on test_extensive(PARADIS).xml file processing')
            
            if(success): 
                print('SUCCESS Test Loads and Gets Parameter and ParametersGroup')

    

    @staticmethod
    def test_merge_and_diff(): 
        file_ref = ['../test_parameters/test_short_ref(PARADIS).xml', '../test_parameters/test_extensive_ref(PARADIS).xml']
        file_usr = ['../test_parameters/test_short_usr(PARADIS).xml', '../test_parameters/test_extensive_usr(PARADIS).xml']
        folder_res = '../../../../results/test_parameters/'
        # Assesses performances 
        
        for (ref, usr) in zip(file_ref, file_usr): 
            # Merge the same file: no differences 
            pg_res, ref_not_usr, usr_not_ref = ParametersGroup.merge_diff(usr,usr,EXPLOPT.REPLACE,folder_res)
            if bool(ref_not_usr) or bool(usr_not_ref): print('ERROR merge: should not have any difference for the same file')
            # Merge different files
            pg_res, ref_not_usr, usr_not_ref = ParametersGroup.merge_diff(ref,usr,EXPLOPT.REPLACE,folder_res)
            # Difference between the samle files (report differences)
            pg_res, ref_not_usr, usr_not_ref = ParametersGroup.merge_diff(ref,usr,EXPLOPT.DIFF,folder_res)
            # Difference between the samle files (calculates differences)
            pg_res, ref_not_usr, usr_not_ref = ParametersGroup.merge_diff(ref,usr,EXPLOPT.DIFF_FLOAT,folder_res)
            
    
if __name__ == "__main__":
    
    # Tests simple on ParametersGroup and Parameter
    ParametersGroup.test_load_and_get()    
    
    # Tests advanced on merge and differences operations 
    ParametersGroup.test_merge_and_diff()
    
    