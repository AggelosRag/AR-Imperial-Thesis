import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader

from base.epoch_trainer_base import EpochTrainerBase
from utils import SimplerMetricTracker


class XY_Tree_Epoch_Trainer(EpochTrainerBase):
    """
    Trainer Epoch class using Tree Regularization
    """

    def __init__(self, arch, epochs, writer, metric_ftns, config, device,
                 data_loader, valid_data_loader=None, lr_scheduler=None):

        super(XY_Tree_Epoch_Trainer, self).__init__()

        # Extract the configuration parameters
        self.tree_reg_mode = config['regularisation']['tree_reg_mode']
        self.writer = writer
        self.epochs = epochs
        self.config = config
        self.device = device
        self.train_loader = data_loader
        self.val_loader = valid_data_loader
        self.lr_scheduler = lr_scheduler
        self.model = arch.model
        self.epochs_warm_up = config['regularisation']['warm_up_epochs']
        self.criterion = arch.criterion
        self.criterion_sr = arch.criterion_sr
        self.optimizer = arch.optimizer
        self.optimizer_mn = arch.optimizer_mn
        self.optimizer_sr = arch.optimizer_sr
        self.reg_strength = config['regularisation']['reg_strength']
        self.mse_loss_strength = config['regularisation']['mse_loss_strength']
        self.min_samples_leaf = config['regularisation']['min_samples_leaf']
        self.metric_ftns = metric_ftns

        self.do_validation = self.val_loader is not None
        self.log_step = int(np.sqrt(data_loader.batch_size))

        # if we use tree regularisation in sequential mode, we need to store
        # all intermediate APL values and the corresponding predictions
        if self.tree_reg_mode == 'Sequential':
            self.sr_training_freq = config['regularisation']['sequential']['sr_training_freq']
            self.APLs_truth = []
            self.all_preds = []

        # Define the metric trackers
        self.train_metrics = SimplerMetricTracker(self.epochs, metric_ftns,
                                                  writer=self.writer, mode='Train')
        self.valid_metrics = SimplerMetricTracker(self.epochs, metric_ftns,
                                                  writer=self.writer, mode='Valid')


    def _train_epoch(self, epoch):

        self.model.feed_forward.train()
        self.model.surrogate_network.train()

        for (X_batch, y_batch), (X_rest, y_rest) in self.train_loader:
            X_batch = X_batch.to(self.device)
            y_batch = y_batch.to(self.device)

            # Forward pass
            y_pred = self.model(X_batch)

            # if we do warm-up, detach the gradient for the surrogate training
            if epoch <= self.epochs_warm_up:
                y_hat_sr = y_pred.flatten().detach()
            else:
                y_hat_sr = y_pred.flatten()

            if y_pred.shape[1] == 1:
                y_hat_pred = torch.where(y_pred > 0.5, 1, 0).cpu()
            elif y_pred.shape[1] >= 3:
                y_hat_pred = torch.argmax(y_pred, 1).cpu()
                y_batch = y_batch.long()
            else:
                raise ValueError('Invalid number of output classes')

            loss_label = self.criterion(y_pred, y_batch)

            # Track target training loss and accuracy
            self.train_metrics.append_batch_result('target_loss', loss_label.item())

            total_train = y_batch.size(0)
            correct_train = (y_hat_pred == y_batch).sum().item()
            self.train_metrics.append_batch_result('correct', correct_train)
            self.train_metrics.append_batch_result('total', total_train)

            # if we operate in SGD mode, then X_batch + X_rest = X
            # We still need the complete dataset to compute the APL
            # In full-batch GD, X_batch = X and X_rest = None
            if X_rest is not None:
                X_rest = X_rest.to(self.device)

                self.model.freeze_model()
                self.model.eval()
                y_pred_rest = self.model(X_rest)
                y_hat_sr_rest = y_pred_rest.flatten()
                self.model.unfreeze_model()
                self.model.train()

                X_batch = torch.vstack([X_batch, X_rest])
                y_pred = torch.vstack([y_pred, y_pred_rest])
                y_hat_sr = torch.cat([y_hat_sr, y_hat_sr_rest])

        # Update the epoch metrics
        self.train_metrics.update_epoch(epoch)

        # Calculate the APL
        self.model.feed_forward.eval()
        APL, self.train_metrics, tree = self._calculate_APL(
            self.min_samples_leaf, X_batch, y_pred)
        self.model.feed_forward.train()

        # Calculate the APL prediction and store results if in sequential tree mode
        # only for usefull APL predictions
        omega = self.model.surrogate_network(y_hat_sr)
        print(f'APL Prediction: {omega.item()}')
        self.train_metrics.append_epoch_result(epoch, 'APL_predictions', omega.item())
        if (APL > 1 or epoch == 0) and self.tree_reg_mode == 'Sequential':
            self.APLs_truth.append(APL)
            self.all_preds.append(y_hat_sr)

        # Calculate the surrogate loss
        sr_loss = self.criterion_sr(input=omega, target=torch.tensor(APL, dtype=torch.float))

        # Optimise either the two losses separately in warm-up mode or the total loss
        if epoch <= self.epochs_warm_up:
            loss = loss_label
            self.optimizer_mn.zero_grad()
            loss.backward()
            self.optimizer_mn.step()

            self.optimizer_sr.zero_grad()
            sr_loss.backward()
            self.optimizer_sr.step()
        else:
            if self.tree_reg_mode == 'Sequential':
                loss = loss_label + self.reg_strength * omega
            else:
                loss = loss_label + self.reg_strength * omega + self.mse_loss_strength * sr_loss

            # Backward pass and optimize
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

        self.train_metrics.append_epoch_result(epoch, 'total_loss', loss.item())

        log = self.train_metrics.result(epoch)

        # in sequential mode, train the surrogate model
        if self.tree_reg_mode == 'Sequential':
            if epoch % self.sr_training_freq == 0:
                self._train_surrogate_sequential_mode(epoch)

        if self.do_validation:
            val_log = self._valid_epoch(epoch)
            log.update(**{'val_'+k : v for k, v in val_log.items()})

        if self.lr_scheduler is not None:
            self.lr_scheduler.step()

        #visualize tree
        if epoch % self.config['regularisation']['snapshot_epochs'] == 0:
            self._visualize_tree(tree, self.config, epoch, APL, train_acc,
                                 val_acc)

        return log

    def _valid_epoch(self, epoch):

        self.model.feed_forward.eval()
        self.model.surrogate_network.eval()

        with torch.no_grad():
            for (X_batch, y_batch) in self.val_loader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                # Only full-batch training is currently supported
                assert X_batch.size(0) == len(self.val_loader.dataset)

                y_pred = self.model(X_batch)

                y_hat_sr = y_pred.flatten()
                omega = self.model.surrogate_network(y_hat_sr)

                if y_pred.shape[1] == 1:
                    y_hat_pred = torch.where(y_pred > 0.5, 1, 0).cpu()
                elif y_pred.shape[1] >= 3:
                    y_hat_pred = torch.argmax(y_pred, 1).cpu()
                    y_batch = y_batch.long()
                else:
                    raise ValueError('Invalid number of output classes')

                loss_label = self.criterion(y_pred, y_batch)

                # Track training loss and accuracy
                self.valid_metrics.append_batch_result('target_loss',
                                                       loss_label.item())

                total_val = y_batch.size(0)
                correct_val = (y_hat_pred == y_batch).sum().item()
                self.valid_metrics.append_batch_result('correct', correct_val)
                self.valid_metrics.append_batch_result('total', total_val)

        # Update the epoch metrics
        self.valid_metrics.update_epoch(epoch)

        APL_test, self.valid_metrics = self._calculate_APL(
            self.min_samples_leaf, X_batch, y_pred)
        print(f'APL Prediction: {omega.item()}')

        sr_loss = self.criterion_sr(input=omega, target=torch.tensor(APL_test, dtype=torch.float))

        if epoch <= self.epochs_warm_up:
            loss = loss_label
        else:
            if self.tree_reg_mode == 'Sequential':
                loss = loss_label + self.reg_strength * omega
            else:
                loss = loss_label + self.reg_strength * omega + self.mse_loss_strength * sr_loss

        self.valid_metrics.append_epoch_result(epoch,'APL_predictions', omega.item())
        self.valid_metrics.append_epoch_result(epoch, 'total_loss', loss.item())

        # add histogram of model parameters to the tensorboard
        for name, p in self.model.named_parameters():
            self.writer.add_histogram(name, p, bins='auto')
        return self.valid_metrics.result(epoch)

    def _train_surrogate_sequential_mode(self, epoch):
        """
        Train the surrogate model in sequential mode
        """
        self.model.unfreeze_surrogate()
        self.model.surrogate_network.train()
        self.model.freeze_model()
        self.model.reset_surrogate_weights()
        if epoch > 0:
            surrogate_training_loss = self.train_surrogate_model(self.all_preds,
                                                            self.APLs_truth,
                                                            self.criterion_sr,
                                                            # optimizer,
                                                            self.optimizer_sr,
                                                            self.model)
            print(f'Surrogate Training Loss: {surrogate_training_loss[-1]:.4f}')

        self.model.unfreeze_model()
        self.model.freeze_surrogate()


    def train_surrogate_model(self, X, y, criterion, optimizer, model):

        # X_train = torch.vstack(X)
        X_train = torch.vstack(X).detach()
        y_train = torch.tensor([y], dtype=torch.float).T.to(self.device)

        model.surrogate_network.to(self.device)

        num_epochs = self.config['regularisation']['sequential']['sr_epochs']
        batch_size = self.config['regularisation']['sequential']['sr_batch_size']

        data_train = TensorDataset(X_train, y_train)
        data_train_loader = DataLoader(dataset=data_train,
                                       batch_size=batch_size, shuffle=True)

        training_loss = []

        model.surrogate_network.train()

        for epoch in range(num_epochs):
            batch_loss = []

            for (x, y) in data_train_loader:
                y_hat = model.surrogate_network(x)
                loss = criterion(input=y_hat, target=y)
                optimizer.zero_grad()
                # loss.backward()
                loss.backward()
                optimizer.step()

                batch_loss.append(
                    loss.item() / (torch.var(y_train).item() + 0.01))

            training_loss.append(np.array(batch_loss).mean())

            if epoch == 0 or (epoch + 1) % 10 == 0:
                # if epoch:
                print(
                    f'Surrogate Model: Epoch [{epoch + 1}/{num_epochs},'
                    f' Loss: {np.array(batch_loss).mean():.4f}]')

        del X
        del y

        return training_loss
