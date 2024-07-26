import os
import pickle

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader,TensorDataset
from torchvision import datasets, transforms
from base import TwoBatchTripletDataLoader, TwoBatchDataLoader
from PIL import Image
from torch.utils.data import BatchSampler

CUB_PROCESSED_DIR = "/Users/gouse/PycharmProjects/AR-Imperial-Thesis/datasets/CUB/class_attr_data_10"
CUB_DATA_DIR = "/Users/gouse/PycharmProjects/AR-Imperial-Thesis/datasets/CUB/CUB_200_2011"
N_ATTRIBUTES = 312

def get_cub_dataLoader(data_dir='./datasets/parabola',
                       type='Full-GD',
                       batch_size=None):

    num_classes = 200
    TRAIN_PKL = CUB_PROCESSED_DIR + "/train.pkl"
    TEST_PKL = CUB_PROCESSED_DIR + "/test.pkl"
    normalizer = transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[2, 2, 2])
    train_loader = load_cub_data([TRAIN_PKL], use_attr=True, no_img=False,
                                 batch_size=batch_size,
                                 uncertain_label=False, image_dir=CUB_DATA_DIR,
                                 resol=224, normalizer=normalizer,
                                 n_classes=num_classes, resampling=True)

    test_loader = load_cub_data([TEST_PKL], use_attr=True, no_img=False,
                                batch_size=batch_size,
                                uncertain_label=False, image_dir=CUB_DATA_DIR,
                                resol=224, normalizer=normalizer,
                                n_classes=num_classes, resampling=True)

    classes = open(os.path.join(CUB_DATA_DIR, "classes.txt")).readlines()
    classes = [a.split(".")[1].strip() for a in classes]
    idx_to_class = {i: classes[i] for i in range(num_classes)}
    classes = [classes[i] for i in range(num_classes)]
    print(len(classes), "num classes for cub")
    print(len(train_loader.dataset), "training set size")
    print(len(test_loader.dataset), "test set size")

    # return train_loader, test_loader, idx_to_class, classes
    return train_loader, test_loader

def load_cub_data(pkl_paths, use_attr, no_img, batch_size,
                  uncertain_label=False, n_class_attr=2, image_dir='images',
                  resampling=False, resol=299,
                  normalizer=transforms.Normalize(mean=[0.5, 0.5, 0.5],
                                                  std=[2, 2, 2]),
                  n_classes=200):
    """
    Note: Inception needs (299,299,3) images with inputs scaled between -1 and 1
    Loads data with transformations applied, and upsample the minority class if there is class imbalance and weighted loss is not used
    NOTE: resampling is customized for first attribute only, so change sampler.py if necessary
    """
    is_training = any(['train.pkl' in f for f in pkl_paths])
    if is_training:
        transform = transforms.Compose([
            transforms.ColorJitter(brightness=32 / 255,
                                   saturation=(0.5, 1.5)),
            transforms.RandomResizedCrop(resol),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            normalizer
        ])
    else:
        transform = transforms.Compose([
            transforms.CenterCrop(resol),
            transforms.ToTensor(),
            normalizer
        ])

    dataset = CUBDataset(pkl_paths, use_attr, no_img, uncertain_label,
                         image_dir, n_class_attr, n_classes, transform)

    if is_training:
        drop_last = True
        shuffle = True
    else:
        drop_last = False
        shuffle = False
    if resampling:
        sampler = BatchSampler(ImbalancedDatasetSampler(dataset),
                               batch_size=batch_size, drop_last=drop_last)
        loader = DataLoader(dataset, batch_sampler=sampler)
    else:
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=shuffle,
                            drop_last=drop_last)
    return loader

class CUBDataset(Dataset):
    """
    Returns a compatible Torch Dataset object customized for the CUB dataset
    """

    def __init__(self, pkl_file_paths, use_attr, no_img, uncertain_label,
                 image_dir, n_class_attr, num_classes, transform=None,
                 pkl_itself=None):
        """
        Arguments:
        pkl_file_paths: list of full path to all the pkl data
        use_attr: whether to load the attributes (e.g. False for simple finetune)
        no_img: whether to load the images (e.g. False for A -> Y model)
        uncertain_label: if True, use 'uncertain_attribute_label' field (i.e. label weighted by uncertainty score, e.g. 1 & 3(probably) -> 0.75)
        image_dir: default = 'images'. Will be append to the parent dir
        n_class_attr: number of classes to predict for each attribute. If 3, then make a separate class for not visible
        transform: whether to apply any special transformation. Default = None, i.e. use standard ImageNet preprocessing
        """
        self.data = []
        self.is_train = any(["train" in path for path in pkl_file_paths])
        if not self.is_train:
            assert any([("test" in path) or ("val" in path) for path in
                        pkl_file_paths])
        if pkl_itself is None:

            for file_path in pkl_file_paths:
                self.data.extend(pickle.load(open(file_path, 'rb')))
        else:
            self.data = pkl_itself
        self.transform = transform
        self.use_attr = use_attr
        self.no_img = no_img
        self.uncertain_label = uncertain_label
        self.image_dir = image_dir
        self.n_class_attr = n_class_attr
        self.num_classes = num_classes

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        img_data = self.data[idx]
        img_path = img_data['img_path']
        # Trim unnecessary paths

        idx = img_path.split('/').index('CUB_200_2011')
        img_path = '/'.join([self.image_dir] + img_path.split('/')[idx + 1:])
        img = Image.open(img_path).convert('RGB')

        class_label = img_data['class_label']
        if self.transform:
            img = self.transform(img)

        if self.use_attr:
            if self.uncertain_label:
                attr_label = img_data['uncertain_attribute_label']
            else:
                attr_label = img_data['attribute_label']
            if self.no_img:
                if self.n_class_attr == 3:
                    one_hot_attr_label = np.zeros(
                        (N_ATTRIBUTES, self.n_class_attr))
                    one_hot_attr_label[np.arange(N_ATTRIBUTES), attr_label] = 1
                    return one_hot_attr_label, class_label
                else:
                    return attr_label, class_label
            else:
                return img, torch.tensor(attr_label).float(), class_label
        else:
            return img, class_label

    def get_all_data_in_tensors(self, batch_size, shuffle):
        all_C = []
        all_y = []
        for i in self.data:
            all_C.append(i["attribute_label"])
            all_y.append(i["class_label"])
        all_C = torch.tensor(all_C).float()
        all_y = torch.tensor(all_y).long()
        all_data = TensorDataset(all_C, all_y)
        dataloader = DataLoader(all_data, batch_size=batch_size, shuffle=shuffle)
        return dataloader

class ImbalancedDatasetSampler(torch.utils.data.sampler.Sampler):
    """Samples elements randomly from a given list of indices for imbalanced dataset
    Arguments:
        indices (list, optional): a list of indices
        num_samples (int, optional): number of samples to draw
    """

    def __init__(self, dataset, indices=None):
        # if indices is not provided,
        # all elements in the dataset will be considered
        self.indices = list(range(len(dataset))) \
            if indices is None else indices

        # if num_samples is not provided,
        # draw `len(indices)` samples in each iteration
        self.num_samples = len(self.indices)

        # distribution of classes in the dataset
        label_to_count = {}
        for idx in self.indices:
            label = self._get_label(dataset, idx)
            if label in label_to_count:
                label_to_count[label] += 1
            else:
                label_to_count[label] = 1

        # weight for each sample
        weights = [1.0 / label_to_count[self._get_label(dataset, idx)]
                   for idx in self.indices]
        self.weights = torch.DoubleTensor(weights)

    def _get_label(self, dataset, idx):  # Note: for single attribute dataset
        return dataset.data[idx]['class_label']  # [0]

    def __iter__(self):
        idx = (self.indices[i] for i in torch.multinomial(
            self.weights, self.num_samples, replacement=True))
        return idx

    def __len__(self):
        return self.num_samples