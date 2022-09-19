# -*- coding: utf-8 -*-
"""
Created on Thu Sep 15 21:00:55 2022

@author: jdedreuz
"""

import numpy as np
import os
import random

import time as time    
import multiprocessing as mp  
import matplotlib.pyplot as plt


NPARAM_GAUSSIAN=2
PARAM_GAUSSIAN_MU=0
PARAM_GAUSSIAN_SIGMA=1
NPARAM_LN=2
PARAM_LN_MU=1
PARAM_LN_SIGMA=1


global_x=[]
global_residue=[]
global_cond=[]
global_rate_select=[]

def append_result(result):
    # This is called whenever foo_pool(i) returns a result.
    # result_list is modified only by the main process, not the pool workers.
    global_x.append(result[0])
    global_cond.append(result[1])
    global_residue.append(result[2])
    global_rate_select.append(result[3])


class BuildTestCase: 
    """ 
    Test Case Building and Comparison (Benchmarking)    
    
    Methods
    -------
    build: 
        Builds test case accroding to different types of distributions
    benchmark_results: 
        Compares Target distribution and computed distribution
        
    Several types of distributions: 
        - Gaussian 
        - Lognormal
    """

    def __init__(self,nrows,ncols):
        """ 
        Constructor
        """
        print()
        self.nrows = nrows
        self.ncols = ncols
        self.distribution_type = "Gaussian"
        if(self.distribution_type=="Gaussian"):
            self.nparam = NPARAM_GAUSSIAN
        elif(self.distribution_type == "LogNormal"):
            self.nparam = NPARAM_LN
        
    def build(self):
        """
        Builds Test Case
        
        """
        # System representing the proportion of each of the lithologies (random sampling)
        self.A = np.random.rand(self.nrows,self.ncols)
        # Normalization of all columns to 1
        row_sums = self.A.sum(axis=1)
        for i, (row, row_sum) in enumerate(zip(self.A, row_sums)):
            self.A[i,:] = row / row_sum
            
        self.param=np.zeros((self.ncols,self.nparam))
        for i in range(self.ncols): 
            if(self.distribution_type=="Gaussian"): 
                # Parameters of the distribution 
                self.param[i][PARAM_GAUSSIAN_MU]=10*(1+i)
                self.param[i][PARAM_GAUSSIAN_SIGMA]=self.param[i][PARAM_GAUSSIAN_MU]*0.05*0
            elif(self.distribution_type=="LogNormal"):
                self.param[i][PARAM_LN_MU]=np.log(1e-1)
                self.param[i][PARAM_LN_SIGMA]=2
                
        # Random sampling of distributions
        self.X = np.zeros((self.nrows,self.ncols))
        for i in range(self.ncols):
            if(self.distribution_type=="Gaussian"): 
                self.X[:,i] = np.random.normal(self.param[i][PARAM_GAUSSIAN_MU], self.param[i][PARAM_GAUSSIAN_SIGMA], self.nrows)
            elif(self.distribution_type=="LogNormal"):
                self.X[:,i] = np.random.lognormal(self.param[i][PARAM_LN_MU], self.param[i][PARAM_LN_SIGMA], self.nrows)
        
        # Computes second member of system
        self.b = (self.A * self.X).sum(axis=1)
        
        
    def benchmark_results(self,x,cond,residue,rate_select):
        mean=np.mean(x,axis=0)
        std=np.std(x,axis=0)
        print("selection ration", format(rate_select*100,".2f"))
        print("mean ratios = ", mean/self.param[:,0])
        print("mean of mean rate differences = ", np.mean(mean/self.param[:,0]))
        print("std ratios = ", std/self.param[:,1]/np.sqrt(2*np.pi))
        print("mean of std rate differences = ", np.mean(std/self.param[:,1])/np.sqrt(2*np.pi))
        plt.figure()
        uu=np.histogram(x[:,1],bins='auto')
        plt.hist(x[:,1],bins='auto')
        plt.show()
        
        
    def display(self): 
        print("full system of equations")
        print("A", self.A)
        print("second member")
        print("b", self.b)
        

def perform_parallel(A,b,nsystems): 
    matp=MatrixProblem(A, b)
    return matp.solve_systems_seq(nsystems)
        

class MatrixProblem:
    """
    Over-determined problem Ax=b
    
    Members
    -------
    A: 2D np.array (rows:nequations, columns: nunknowns)
        matrix with more equations than unknowns
    b: 1D np.array
        second member
    x: 2D np.array (rows:systems solved, columns, nunknowns)
        solutions
    cond_max: float
        Maximum condition number for which solution is accepted
    residue_max: float
        Maximum residue for which solution is accepted
        
    Methods
    -------
    solve_systems(nsystems) 
        solves nsystems sub-systems and stores results
    """

    def __init__(self,A,b):
        """ 
        Constructor
        """
        self.A = A
        self.b = b
        if(self.n_equations()<5): 
            self.cond_max = 10
            self.residue_max = 1e-16
        else: 
            self.cond_max = 100
            self.residue_max = 1e-13
        self.nprocessors = 8
        
        
    def display(self): 
        print("full system of equations")
        print(self.A)
        print("second member")
        print("b", self.b)
        
    
    def n_unknowns(self): 
        return len(self.A[1,:])
    
    
    def n_equations(self): 
        return len(self.A[:,1])


    def solve_systems_parallel(self,nsystems): 
        """ 
        solves "nsystems" subsystems randomly sampled from initial over-determined system Ax=b
        parallel version
        """
        pool = mp.Pool(self.nprocessors)
        for i in range(self.nprocessors): 
            pool.apply_async(perform_parallel, args=(self.A,self.b,int(nsystems/self.nprocessors)),callback=append_result)
        pool.close()
        pool.join()
        x = global_x[0]; cond = global_cond[0]; residue = global_residue[0]
        for i in range(1,self.nprocessors): 
            x = np.concatenate((x,global_x[i]))
            cond = np.concatenate((cond,global_cond[i]))
            residue = np.concatenate((residue,global_residue[i]))
        rate_select = np.mean(global_rate_select)
        return x, cond, residue, rate_select

        
    def solve_systems_seq(self,nsystems): 
        """ 
        solves "nsystems" subsystems randomly sampled from initial over-determined system Ax=b
        """
        index_list=list(range(0,self.n_equations()))
        n_un = self.n_unknowns()
        x = np.zeros((nsystems,n_un))
        cond = np.zeros((nsystems,1))
        residue = np.zeros((nsystems,1))
        residue_other=[]; cond_other=[]
        # make a parallel loop
        i=0
        while i < nsystems : 
            # gets subsystem
            index = random.sample(index_list,n_un)
            Ar = self.A[index,:]
            br = self.b[index]
            # solves
            xr = np.linalg.solve(Ar,br)
            # computation of conditions for which solution will be stored or not
            cond_temp = np.linalg.cond(Ar)
            residue_temp = sum(abs((Ar*xr).sum(axis=1)-br))
            # stores solutions depending on the condition number of the system
            if((min(xr)>0) and (cond_temp < self.cond_max) and (residue_temp < self.residue_max)) : 
                x[i,:] = xr
                cond[i] = cond_temp
                residue[i] = residue_temp
                i=i+1
            else: 
                # print("cond = ", cond_temp, "residue = ", residue_temp)
                residue_other.append(residue); cond_other.append(cond)

        # Ratio of selection 
        rate_select = len(residue)/(len(residue_other)+len(residue))
        return x, cond, residue, rate_select        

        

if __name__ == "__main__":  
    # Parameters
    n_unknowns=5
    n_equations=5
    n_systems=1000
    parallel = False
    
    # Build Test Case
    tc = BuildTestCase(n_equations,n_unknowns)
    tc.build()
    matp = MatrixProblem(tc.A,tc.b)
    # mp.display()
    
    # Solving
    st=time.time()
    if parallel == True: 
        x,residue,cond,rate_select = matp.solve_systems_parallel(n_systems)
    else: 
        x,residue,cond,rate_select = matp.solve_systems_seq(n_systems)
    print('time=',time.time()-st,"\n")
    
    # Analyze Results
    tc.benchmark_results(x,cond,residue,rate_select)