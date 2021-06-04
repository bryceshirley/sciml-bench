#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# config.py

# SciML-Bench
# Copyright © 2021 Scientific Machine Learning Research Group
# Scientific Computing Department, Rutherford Appleton Laboratory
# Science and Technology Facilities Council, UK. 
# All rights reserved.

"""
Configuration for the whole sciml-bench, including
* program configuration, and 
* datasets and benchmarks.
"""

import yaml
from pathlib import Path


class ProgramEnv:
    """ Class to initialize and store program environment """

    def __init__(self, config_file_path):
        # --------------
        # program config
        # --------------
        # read config
        with open(config_file_path) as handle:
            cfg = yaml.load(handle, yaml.SafeLoader)
            cfg = {} if cfg is None else cfg

        # Data Mirrors first
        self.mirrors = cfg['data_mirrors']
        # TODO: Workout the closest mirror 


        #Global download command
        self.download_commands = cfg['download_commands']
        
        # dirs
        cfg_dirs = cfg['directories']
        self.dataset_dir = Path(cfg_dirs['dataset_root_dir']).expanduser()
        self.output_dir  = Path(cfg_dirs['output_root_dir']).expanduser()
        self.model_dir   = Path(cfg_dirs['models_dir']).expanduser()

        # datasets 
        self.datasets = cfg['datasets']

        # benchmarks  
        self.benchmarks = cfg['benchmarks']


        # Now validate the file 
        self.is_valid = False
        self.config_error = None
        self.__validate_config()


    def __validate_config(self):
        """
        Validates the configuration - minimum check
        """
        # At least one mirror
        if self.mirrors == None:
            self.is_valid = False
            self.config_error = 'Missing data mirrors.'
            return

        # At least one dataset
        if self.datasets == None:
            self.is_valid = False
            self.config_error = 'Missing datasets.'
            return

        # At least one benchmark
        if self.benchmarks == None:
            self.is_valid = False
            self.config_error = 'Missing benchmarks.'
            return

        # Check for the existence of download_command
        if self.download_commands == None:
            self.is_valid = False
            self.config_error = 'Missing download-commands.'
            return

        # Check for minimum records in datasets
        # end_points and sensible download_command
        for k, v in self.datasets.items():
            if 'end_point' not in v:
                self.is_valid = False
                self.config_error = 'Missing end-point for at least one dataset.'
                return   
            if 'download_command' in v and v['download_command'] not in self.download_commands:
                self.is_valid = False
                self.config_error = 'Invalid download command for at least one dataset.'
                return   

        # Check for minimum records in benchmarks
        # existence of datasets
        for k, v in self.benchmarks.items():
            if 'datasets' not in v:
                self.is_valid = False
                self.config_error = 'No datasets are linked to at least one benchmark.'
                return  

        self.is_valid = True

    def is_config_valid(self):
        return self.is_valid, self.config_error

    def get_download_command(self, dataset_name):
        cmd = None
        if self.is_valid == True:
            cmd = self.datasets[dataset_name]['download_command']
            cmd = self.download_commands[cmd]
        return cmd 

    # Given a benchmark, returns the sections of the benchmark
    # assigning default values wherever possible.
    def get_bench_sections(self, benchmark_name):

        bench_datasets = self.get_bench_datasets(benchmark_name)
        bench_dependencies = self.get_bench_dependencies(benchmark_name)
        is_bench_example = self.get_bench_example_flag(benchmark_name)
        bench_types = self.get_bench_types(benchmark_name)
        
        return bench_datasets, bench_dependencies, is_bench_example, bench_types


    def get_bench_types(self, benchmark_name):
        
        if (benchmark_name not in self.benchmarks) or self.is_config_valid==False:
            return None

        benchmark = self.benchmarks[benchmark_name]
        if 'types' in benchmark.keys():
            return list(set(filter(''.__ne__, benchmark['types'].split(','))))
        else:
            return  ['training', 'inference']

    def get_bench_example_flag(self, benchmark_name):
        
        if (benchmark_name not in self.benchmarks) or self.is_config_valid==False:
            return None

        benchmark = self.benchmarks[benchmark_name]
        if 'is_example' in benchmark.keys():
            return benchmark['is_example']
        else:
            return  False

    def get_bench_dependencies(self, benchmark_name):
        
        if (benchmark_name not in self.benchmarks) or self.is_config_valid==False:
            return None

        benchmark = self.benchmarks[benchmark_name]
        if 'dependencies' in benchmark.keys():
            return list(set(filter(''.__ne__, benchmark['dependencies'].split(','))))
        else:
            return  None

    def get_bench_datasets(self, benchmark_name):
        
        if (benchmark_name not in self.benchmarks) or self.is_config_valid==False:
            return None

        benchmark = self.benchmarks[benchmark_name]
        if 'datasets' in benchmark.keys():
            return list(set(filter(''.__ne__, benchmark['datasets'].split(','))))
        else:
            return  None