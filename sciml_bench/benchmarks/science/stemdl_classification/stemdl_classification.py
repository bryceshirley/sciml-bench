
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# stemdl_classification.py

# SciML-Bench
# Copyright © 2021 Scientific Machine Learning Research Group
# Scientific Computing Department, Rutherford Appleton Laboratory
# Science and Technology Facilities Council, UK. 
# All rights reserved.

# Copyright © 2021 Oak Ridge National Laboratory
# P.O. Box 2008, Oak Ridge, TN 37831 USA. 
# All rights reserved.

import yaml
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader
from torch.utils.data import random_split
from torchvision import transforms
import pytorch_lightning as pl
#from pytorch_lightning.plugins import DDPPlugin
from pytorch_lightning.strategies import DDPStrategy

# imports from stemdl
import time
import sys
import os
import math
import glob
import argparse
import torch.backends.cudnn as cudnn
import torch.multiprocessing as mp
import torch.nn.functional as F
import torch.optim as optim
import torch.utils.data.distributed
from torch.utils.tensorboard import SummaryWriter
from torchvision import datasets, transforms, models
from tqdm import tqdm
from sklearn.metrics import f1_score
import torch.nn as nn
import numpy as np

from pathlib import Path
from torch.utils.data import Dataset
from torchvision import datasets
from torchvision.transforms import ToTensor
import torchmetrics as tm

# Integration into sciml-bench framework
from sciml_bench.core.runtime import RuntimeIn, RuntimeOut
from sciml_bench.core.utils import MultiLevelLogger
from sciml_bench.core.config import ProgramEnv
from sciml_bench.core.utils import SafeDict


# Custom dataset class
class NPZDataset(Dataset):
    def __init__(self, npz_root):
        self.files = glob.glob(npz_root + "/*.npz")

    def __getitem__(self, index):
        sample = np.load(self.files[index])
        x = torch.from_numpy(sample["data"])
        y = sample["label"][0]
        return (x, y)

    def __len__(self):
        return len(self.files)

class StemDLClassifier(pl.LightningModule):
    def __init__(self):
        super().__init__()
        self.input_size = 128
        self.num_classes = 231
        self.model_name = "resnet50"
        self.model = models.resnet50(pretrained=False)
        self.num_ftrs = self.model.fc.in_features
        self.model.fc = nn.Linear(self.num_ftrs, self.num_classes)
        self.feature_extract = False
        
        self.accuracy = tm.classification.MulticlassAccuracy(num_classes=self.num_classes)
        self.f1_score = tm.classification.F1Score(task='multiclass', num_classes=self.num_classes, average='macro')

        # To store outputs for later use
        self.test_outputs = []

    def forward(self, x):
        return self.model(x)

    def configure_optimizers(self):
        optimizer = torch.optim.AdamW(self.parameters(), lr=0.001, weight_decay=0.00005)
        return optimizer

    def training_step(self, train_batch, batch_idx):
        x, y = train_batch
        x_hat = self.model(x)
        loss = F.cross_entropy(x_hat, y)
        self.log('train_loss', loss)
        return loss

    def validation_step(self, val_batch, batch_idx):
        x, y = val_batch
        logits = self.model(x)
        loss = F.cross_entropy(logits, y)
        self.log('val_loss', loss)
        y_hat = F.softmax(logits, dim=-1)
        self.accuracy(y_hat, y)
        self.f1_score(y_hat, y)
        return loss

    def on_validation_epoch_end(self) -> None:
        avg_accuracy = self.accuracy.compute()
        avg_f1 = self.f1_score.compute()
        self.log('valid_accuracy', avg_accuracy, prog_bar=True, sync_dist=True)
        self.log('valid_f1', avg_f1, prog_bar=True, sync_dist=True)

    def test_step(self, test_batch, batch_idx):
        x, y = test_batch
        logits = self.model(x)
        y_hat = F.softmax(logits, dim=-1)
        loss = F.cross_entropy(logits, y)
        self.log('loss', loss)
        self.accuracy(y_hat, y)
        self.f1_score(y_hat, y)

        # Collect test outputs for later use
        self.test_outputs.append({
            'loss': loss,
            'accuracy': self.accuracy.compute(),
            'f1': self.f1_score.compute()
        })

    def on_test_epoch_end(self) -> None:
        # Calculate averages of the collected metrics
        avg_accuracy = torch.mean(torch.tensor([out['accuracy'] for out in self.test_outputs], dtype=torch.float))
        avg_f1 = torch.mean(torch.tensor([out['f1'] for out in self.test_outputs], dtype=torch.float))

        self.log('accuracy', avg_accuracy * 100, sync_dist=True)
        self.log('f1', avg_f1 * 100, sync_dist=True)

    def predict_step(self, batch, batch_idx, dataloader_idx=0):
        x, _ = batch
        y_hat = self.model(x)
        return y_hat

#####################################################################
# Training mode                                                     #
#####################################################################
# For training use this command:
# sciml-bench run stemdl_classification --mode training -b epochs 1 -b batchsize 32 -b nodes 1 -b gpus 1

def sciml_bench_training(params_in: RuntimeIn, params_out: RuntimeOut):
    # Entry point for the training routine to be called by SciML-Bench
    default_args = {
        'batchsize': 32,
        'epochs': 10,
        'nodes': 1,
        'gpus': 1
    }    

    # Log top-level process
    log = params_out.log.console
    log.begin(f'Running benchmark stemdl_classification on training mode')

    # Parse input arguments against default ones 
    with log.subproc('Parsing input arguments'):
        args = params_in.bench_args.try_get_dict(default_args=default_args)

    # Set data paths
    with log.subproc('Set data paths'):
        basePath = params_in.dataset_dir
        trainingPath = os.path.expanduser(basePath / 'training')
        validationPath = os.path.expanduser(basePath / 'validation')
        testingPath = os.path.expanduser(basePath / 'testing')

    # Create datasets
    with log.subproc('Create datasets'):
        train_dataset = NPZDataset(trainingPath)
        val_dataset = NPZDataset(validationPath)
        test_dataset = NPZDataset(testingPath)

    # Get command line arguments
    with log.subproc('Get command line arguments'):
        bs = int(args["batchsize"])
        epochs = int(args["epochs"])
        nodes = int(args["nodes"])
        gpus = int(args["gpus"])

    # Create data loaders
    with log.subproc('Create data loaders'):
        train_loader = DataLoader(train_dataset, batch_size=bs, num_workers=4, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=bs, num_workers=4, shuffle=False)
        test_loader = DataLoader(test_dataset, batch_size=bs, num_workers=4, shuffle=False)

    # Model
    with log.subproc('Create model'):
        model = StemDLClassifier()

    # Training
    with log.subproc('Start training'):
        trainer = pl.Trainer(
            devices=gpus,  # Specify number of devices (GPUs)
            num_nodes=nodes,  # Number of nodes to use
            precision='16-mixed',  # Use mixed precision
            strategy=DDPStrategy(),  # Distributed strategy for training
            max_epochs=epochs,  # Number of epochs
            default_root_dir=params_in.output_dir  # Root directory for saving logs and checkpoints
        )
        start_time = time.time()
        trainer.fit(model, train_loader, val_loader)
        end_time = time.time()
        time_taken = end_time - start_time
        log.message('End training')

    # Testing
    with log.subproc('Start testing'):
        try:
            # Ensure that the test method returns metrics
            metrics = trainer.test(model, test_loader)
            if not metrics or not isinstance(metrics, list) or len(metrics) == 0:
                raise ValueError("Metrics list is empty or not in expected format.")
            metrics = metrics[0]  # Get the first set of metrics
            log.message('End testing')
        except Exception as e:
            log.error(f"Error during testing or metric retrieval: {e}")
            raise

    # Save model
    model_path = params_in.output_dir / 'stemdlModel.h5'
    with log.subproc('Save model'):
        torch.save(model.state_dict(), model_path)
        log.message('Model saved')

    # Save metrics
    metrics = {key: float(value) for key, value in metrics.items()}
    metrics['time'] = time_taken
    metrics_file = params_in.output_dir / 'metrics.yml'
    with log.subproc('Saving inference metrics to a file'):
        with open(metrics_file, 'w') as handle:
            yaml.dump(metrics, handle)

    # End top level
    log.ended(f'Running benchmark stemdl_classification on training mode')


#####################################################################
# Inference mode                                                    #
#####################################################################
# The "--model" key in inference commandline is not read.
'''
For inference run this command: 
sciml-bench run stemdl_classification --mode inference \
    --model ~/sciml_bench/outputs/stemdl_classification/stemdlModel.h5 \
    --dataset_dir ~/sciml_bench/datasets/stemdl_ds1/inference \
    -b epochs 1 -b batchsize 32 -b nodes 1 -b gpus 1 
'''
def sciml_bench_inference(params_in: RuntimeIn, params_out: RuntimeOut):
    default_args = {
        'batchsize': 32,
        'nodes': 1,
        'gpus': 1
    }    

    # Entry point for the inference routine to be called by SciML-Bench
    log = params_out.log

    # Parse input arguments against default ones 
    with log.subproc('Parsing input arguments'):
        args = params_in.bench_args.try_get_dict(default_args=default_args)

    log.begin('Running benchmark stemdl_classification on inference mode')
    # Set data paths
    with log.subproc('Set data paths'):
        basePath = params_in.dataset_dir
        model_path = params_in.model
        inferencePath = os.path.expanduser(basePath)

    # Get command line arguments
    with log.subproc('Get command line arguments'):
        bs = int(args["batchsize"])
        nodes = int(args["nodes"])
        gpus = int(args["gpus"])

    # Create datasets
    with log.subproc('Create datasets'):
        predict_dataset = NPZDataset(inferencePath)

    # Create data loaders
    with log.subproc('Create data loaders'):
        predict_loader = DataLoader(predict_dataset, batch_size=bs, num_workers=4)

    # Load model
    with log.subproc('Load model'):
        model = StemDLClassifier()
        model.load_state_dict(torch.load(model_path))

    # Start inference
    with log.subproc('Inference on the model'):
        trainer = pl.Trainer(
            devices=gpus,  # Specify number of devices (GPUs)
            num_nodes=nodes,  # Number of nodes to use
            precision='16-mixed',  # Use mixed precision
            strategy=DDPStrategy(),  # Distributed strategy for training
            default_root_dir=params_in.output_dir  # Root directory for saving logs and checkpoints
        )
        start_time = time.time()
        metrics = trainer.test(model, dataloaders=predict_loader)
        end_time = time.time()
        time_taken = end_time - start_time
        metrics = metrics[0]
        metrics['time'] = time_taken
        metrics['throughput'] = len(predict_dataset) / time_taken

    # Save metrics
    metrics = {key: float(value) for key, value in metrics.items()}
    metrics_file = params_in.output_dir / 'metrics.yml'
    with log.subproc('Saving inference metrics to a file'):
        with open(metrics_file, 'w') as handle:
            yaml.dump(metrics, handle)

    # End top level
    log.ended('Running benchmark stemdl_classification on inference mode')
