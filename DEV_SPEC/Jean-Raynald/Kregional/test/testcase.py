# -*- coding: utf-8 -*-
"""
Created on Thu Sep 15 21:00:55 2022

@author: jdedreuz
"""

import numpy as np
import os
import random



class BuildTestCase: 
    """     
    """

    def __init__(self,nrows,ncols):
        """ 
        Constructor
        """
        print()
        self.nrows = nrows
        self.ncols = ncols
        
        
    def build(self):
        # System representing the proportion of each of the lithologies
        self.A = np.random.rand(self.nrows,self.ncols)
        # Normalization of all columns to 1
        row_sums = self.A.sum(axis=1)
        for i, (row, row_sum) in enumerate(zip(self.A, row_sums)):
            self.A[i,:] = row / row_sum
        # Parameters of the distribution 
        NPARAM_DISTRIBUTION=2
        PARAM_GAUSSIAN_MU=0
        PARAM_GAUSSIAN_SIGMA=1
        self.distribution_type="Gaussian"
        self.param=np.zeros((self.ncols,NPARAM_DISTRIBUTION))
        for i in range(self.ncols): 
            self.param[i][PARAM_GAUSSIAN_MU]=10
            self.param[i][PARAM_GAUSSIAN_SIGMA]=2
        # Random sampling of distributions
        self.X = np.zeros((self.nrows,self.ncols))
        for i in range(self.ncols):
            self.X[:,i] = np.random.normal(self.param[i][PARAM_GAUSSIAN_MU], self.param[i][PARAM_GAUSSIAN_SIGMA], self.nrows)
        # Computes second member of system
        self.b = (self.A * self.X).sum(axis=1)
        
        
    def benchmark_results(self,x):
        mean=np.mean(x,axis=0)
        std=np.std(x,axis=0)
        print("mean ratios = ", mean/self.param[:,0])
        print("std ratios = ", std/self.param[:,1]/np.sqrt(2*np.pi))
        print("mean ratios = ", np.mean(mean/self.param[:,0]))
        print("std ratios = ", np.mean(std/self.param[:,1])/np.sqrt(2*np.pi))
        
        
    def display(self): 
        print("full system of equations")
        print("A", self.A)
        print("second member")
        print("b", self.b)
        
        

class MatrixProblem:
    """     
    """

    def __init__(self,A,b):
        """ 
        Constructor
        """
        self.A = A
        self.b = b
        
        
    def display(self): 
        print("full system of equations")
        print(self.A)
        print("second member")
        print("b", self.b)
        
    
    def n_unknowns(self): 
        return len(self.A[1,:])
    
    
    def n_equations(self): 
        return len(self.A[:,1])

    
    def solve_systems(self,nsystems): 
        """ 
        solves nsystems randomly sampled
        """
        index_list=list(range(0,self.n_equations()))
        n_un = self.n_unknowns()
        x = np.zeros((nsystems,n_un))
        i=0
        while i < nsystems : 
            index = random.sample(index_list,n_un)
            Ar=self.A[index,:]
            br=self.b[index]
            xr=np.linalg.solve(Ar,br)
            if(np.linalg.cond(Ar)<10): 
                if sum(abs((Ar*xr).sum(axis=1)-br)) > 1e-18 : 
                    # print("worst residue=", sum(abs((Ar*xr).sum(axis=1)-br)))
                    # if (xr[0] < 0): 
                    #     print(xr)
                    #     print(np.linalg.cond(Ar))
                    # else: 
                    #     print(np.linalg.cond(Ar))
                    x[i,:] = xr
                    i=i+1
        self.x = x
        

if __name__ == "__main__":  
    n_unknowns=4
    n_equations=40
    n_systems=10000
    tc = BuildTestCase(n_equations,n_unknowns)
    tc.build()
    mp = MatrixProblem(tc.A,tc.b)
    # mp.display()
    mp.solve_systems(n_systems)
    tc.benchmark_results(mp.x)