from sklearn.tree import DecisionTreeClassifier
from torch import nn
import torch
import numpy as np
from torch.nn.utils import parameters_to_vector, vector_to_parameters

class MNISTCBMTreeArchitecture:
    def __init__(self, config):

        self.concept_predictor = ConceptPredictor()
        self.sr_model = SurrogateNetwork(
            input_dim=config["dataset"]["train_size"] * config["dataset"]["num_classes"]
        )
        self.label_predictor = LabelPredictor(concept_size=config["dataset"]["num_concepts"],
                                              num_classes=config["dataset"]["num_classes"])
        self.mn_model = MainNetwork(self.concept_predictor, self.label_predictor)
        self.model = TreeNet(self.mn_model, self.sr_model)

        # Define loss functions and optimizers
        self.criterion_concept = nn.BCELoss(reduction='none')  # BCE Loss for binary concepts
        self.criterion_label = nn.CrossEntropyLoss()
        self.criterion_sr = nn.MSELoss()

        self.optimizer = torch.optim.Adam(self.model.parameters(),
                                          lr=config["model"]['lr'],
                                          weight_decay=config["model"]['weight_decay'])
        self.optimizer_sr = torch.optim.Adam(self.sr_model.parameters(), lr=0.001)
        self.optimizer_mn = torch.optim.Adam(self.mn_model.parameters(), lr=0.001)

class MNISTCBMArchitecture:
    def __init__(self, config):

        self.concept_predictor = ConceptPredictor()
        self.label_predictor = LabelPredictor(concept_size=config["dataset"]["num_concepts"],
                                              num_classes=config["dataset"]["num_classes"])
        self.model = MainNetwork(self.concept_predictor, self.label_predictor)

        # Define loss functions and optimizers
        self.criterion_concept = nn.BCELoss(reduction='none')  # BCE Loss for binary concepts
        self.criterion_label = nn.CrossEntropyLoss()

        # only apply regularisation (if any) to the label predictor,
        # for a fair comparison with Tree Regularisation
        params_to_update = [
            {'params': self.model.concept_predictor.parameters(), 'weight_decay': 0},
            {'params': self.model.label_predictor.parameters(), 'weight_decay': config["model"]['weight_decay']},
        ]

        self.optimizer = torch.optim.Adam(params_to_update,
                                          lr=config["model"]['lr'])

class MNISTCBMSelectiveNetArchitecture:
    def __init__(self, config):

        # define the main network
        self.concept_predictor = ConceptPredictor()
        self.label_predictor = LabelPredictor(concept_size=config["dataset"]["num_concepts"],
                                              num_classes=config["dataset"]["num_classes"])
        self.model = MainNetwork(self.concept_predictor, self.label_predictor)

        # define the selector network
        self.selector = torch.nn.Sequential(
            torch.nn.Linear(config["dataset"]["num_concepts"], config["dataset"]["num_concepts"]),
            torch.nn.ReLU(True),
            torch.nn.BatchNorm1d(config["dataset"]["num_concepts"]),
            torch.nn.Linear(config["dataset"]["num_concepts"], 1),
            torch.nn.Sigmoid(),
        )
        self.aux_model = LabelPredictor(concept_size=config["dataset"]["num_concepts"],
                                        num_classes=config["dataset"]["num_classes"])

        # Define loss functions and optimizers
        self.criterion_concept = nn.BCELoss(reduction='none')  # BCE Loss for binary concepts
        self.criterion_label = nn.CrossEntropyLoss()

        # only apply regularisation (if any) to the label predictor,
        # for a fair comparison with Tree Regularisation
        params_to_update = [
            {'params': self.model.concept_predictor.parameters(), 'weight_decay': 0},
            {'params': self.model.label_predictor.parameters(), 'weight_decay': config["model"]['weight_decay']},
        ]

        self.optimizer = torch.optim.Adam(params_to_update,
                                          lr=config["model"]['lr'])

class MNISTCYArchitecture:
    def __init__(self, config):

        self.model = LabelPredictor(concept_size=config["dataset"]["num_features"],
                                    num_classes=config["dataset"]["num_classes"])

        # Define loss functions and optimizers
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = torch.optim.Adam(self.model.parameters(),
                                          lr=config["model"]['lr'],
                                          weight_decay=config["model"]['weight_decay'])

# Define the models
class ConceptPredictor(nn.Module):
    def __init__(self):
        super(ConceptPredictor, self).__init__()
        self.fc1 = nn.Linear(28 * 28, 512)
        self.fc2 = nn.Linear(512, 256)
        self.fc3 = nn.Linear(256, 12)  # 6 binary outputs

    def forward(self, x):
        x = x.view(-1, 28 * 28)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        #x = self.fc3(x)
        x = torch.sigmoid(self.fc3(x))  # Sigmoid activation for binary concepts
        return x

class LabelPredictor(nn.Module):
    def __init__(self, concept_size, num_classes):
        super(LabelPredictor, self).__init__()
        self.fc1 = nn.Linear(concept_size, 100)
        self.fc2 = nn.Linear(100, 100)
        self.fc3 = nn.Linear(100, 100)
        self.fc4 = nn.Linear(100, num_classes)

    def forward(self, c):
        c = torch.relu(self.fc1(c))
        c = torch.relu(self.fc2(c))
        c = torch.relu(self.fc3(c))
        c = self.fc4(c)
        return c

class MainNetwork(nn.Module):
    def __init__(self, concept_predictor, label_predictor):
        super(MainNetwork, self).__init__()

        self.concept_predictor = concept_predictor
        self.label_predictor = label_predictor

    def unfreeze_model(self):
        """
        Enable model updates by gradient-descent by unfreezing the model parameters.
        """
        for param in self.parameters():
            param.requires_grad = True

    def freeze_model(self):
        """
        Disable model updates by gradient-descent by freezing the model parameters.
        """
        for param in self.parameters():
            param.requires_grad = False

class SurrogateNetwork(nn.Module):
    def __init__(self, input_dim):
        super(SurrogateNetwork, self).__init__()

        self.feed_forward = nn.Sequential(
            nn.Linear(input_dim, 100),
            nn.ReLU(),
            #nn.Dropout(0.05),
            nn.Linear(100, 25),
            nn.ReLU(),
            nn.Linear(25, 1),
            nn.Softplus()
        )

    def forward(self, x):
        return self.feed_forward(x)

class TreeNet(nn.Module):
    def __init__(self, mn_model, sr_model):
        super(TreeNet, self).__init__()

        self.mn_model = mn_model
        self.sr_model = sr_model

    def unfreeze_model(self):
        """
        Enable model updates by gradient-descent by unfreezing the model parameters.
        """
        for param in self.mn_model.parameters():
            param.requires_grad = True

    def freeze_model(self):
        """
        Disable model updates by gradient-descent by freezing the model parameters.
        """
        for param in self.mn_model.parameters():
            param.requires_grad = False

    def freeze_surrogate(self):
        """
        Disable model updates by gradient-descent by freezing the model parameters.
        """

        for param in self.sr_model.parameters():
            param.requires_grad = False

    def unfreeze_surrogate(self):
        """
        Enable model updates by gradient-descent by unfreezing the model parameters.
        """
        for param in self.sr_model.parameters():
            param.requires_grad = True
