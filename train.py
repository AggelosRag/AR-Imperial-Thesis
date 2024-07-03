import argparse
import collections
import torch
import numpy as np
import model.loss as module_loss
import model.metric as module_metric
import model.model as module_arch
from experimentation.tree_final import perform_leakage_visualization
from parse_config import ConfigParser
from trainer import Trainer
from utils import prepare_device
import importlib


# fix random seeds for reproducibility
SEED = 42
torch.manual_seed(SEED)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
np.random.seed(SEED)

def main(config):
    logger = config.get_logger('train')

    # setup data_loader instances
    dataloaders_module = importlib.import_module("data_loaders")
    data_loader, valid_data_loader = config.init_obj('data_loader', dataloaders_module)
    #valid_data_loader = data_loader.split_validation()

    # build model architecture, then print to console
    arch_module = importlib.import_module("architectures")
    arch = config.init_obj('arch', arch_module, config)
    logger.info(arch.model)

    # prepare for (multi-device) GPU training
    device, device_ids = prepare_device(config['n_gpu'])
    model = arch.model.to(device)
    if len(device_ids) > 1:
        model = torch.nn.DataParallel(model, device_ids=device_ids)

    if 'explainer' in config.config.keys():
        perform_leakage_visualization(data_loader, arch, config)
        return 0
    # get function handles of loss and metrics
    # criterion = getattr(module_loss, config['loss'])
    # metrics = [getattr(module_metric, met) for met in config['metrics']]
    metrics = config['metrics']
    reg = config['regularisation']["type"]

    # build optimizer, learning rate scheduler. delete every lines containing lr_scheduler for disabling scheduler
    # trainable_params = filter(lambda p: p.requires_grad, model.parameters())
    # optimizer = config.init_obj('optimizer', torch.optim, trainable_params)
    # lr_scheduler = config.init_obj('lr_scheduler', torch.optim.lr_scheduler, optimizer)

    trainers = importlib.import_module("trainers")
    trainer = config.init_obj('trainer', trainers,
                              arch=arch,
                              metric_ftns=metrics,
                              config=config,
                              device=device,
                              data_loader=data_loader,
                              valid_data_loader=valid_data_loader,
                              reg=reg)
    # trainer = Trainer(arch=arch, metric_ftns=metrics,
    #                   config=config,
    #                   device=device,
    #                   data_loader=data_loader,
    #                   valid_data_loader=valid_data_loader,
    #                   reg=reg)

    trainer.train()


if __name__ == '__main__':
    args = argparse.ArgumentParser(description='Imperial Diploma Project')
    args.add_argument('-c', '--config', default=None, type=str,
                      help='config file path (default: None)')
    args.add_argument('-r', '--resume', default=None, type=str,
                      help='path to latest checkpoint (default: None)')
    args.add_argument('-d', '--device', default=None, type=str,
                      help='indices of GPUs to enable (default: all)')

    # custom cli options to modify configuration from default values given in json file.
    CustomArgs = collections.namedtuple('CustomArgs', 'flags type target')
    options = [
        CustomArgs(['--lr', '--learning_rate'], type=float, target='optimizer;args;lr'),
        CustomArgs(['--bs', '--batch_size'], type=int, target='data_loader;args;batch_size')
    ]
    config = ConfigParser.from_args(args, options)
    main(config)
