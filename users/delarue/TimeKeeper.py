
"""
@date: 2025-09-23
@lastMod: 2025-09-23
@author: delarueo
@description: The TimeKeeper class to track processing time
"""

import time


class TimeKeeper():
    def __init__(self,verbose = True):
        self.verbose = verbose
        self.start = time.time()
        self.step = self.start
        self.unit = 's'
    def __str__(self):
        return f' {time.time() - self.start:.2f} s'
    def get_start(self):
        return self.start
    def set_unit(self, unit):
        if unit in ['s', 'm', 'h']:
            self.unit = unit
        else:
            raise ValueError("><TimeKeeper> unit must be 's', 'm' or 'h'")
    def now(self, model = 'relatif'):                
        if model == 'relatif':
            t = time.time() - self.start
        elif model == 'absolute':
            t = time.time()
        else:
            raise ValueError("><TimeKeeper> model must be 'relatif' or 'absolute'")
        
        if self.unit == 's':
            t = t
        elif self.unit == 'm':
            t = t / 60
        elif self.unit == 'h':
            t = t / 3600        
        else:
            raise ValueError("><TimeKeeper> unit must be 's', 'm' or 'h'")
        if self.verbose:
            print(f' {t:.2f} {self.unit}')
        return t
    def step_time(self):
        end = time.time()
        step = end - self.step
        self.step = end
        if self.verbose:
            print(f' {step:.2f} s')

