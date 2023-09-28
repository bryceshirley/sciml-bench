#!/bin/bash
set -e
set -x

# Create new environment
ENV_NAME=sciml-bench-mnist_torch
conda remove -n $ENV_NAME --all -y --quiet
conda create -n $ENV_NAME python=3.9 -y --quiet
ENV_PATH=$(dirname $(dirname $(which conda)))/envs/$ENV_NAME

# Install conda requirements
conda install -n $ENV_NAME -y --quiet pytorch==1.13.1 torchvision==0.14.1 pytorch-cuda=11.6 -c pytorch -c nvidia

# Install pip requirements
conda run -n $ENV_NAME python -m pip install -q --upgrade pip
conda run -n $ENV_NAME python -m pip install -q scikit-image torchmetrics
conda run -n $ENV_NAME python -m pip install -q -e .
echo $ENV_NAME