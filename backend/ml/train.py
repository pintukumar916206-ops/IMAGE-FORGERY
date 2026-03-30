import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from torch.utils.data import DataLoader
from sklearn.metrics import roc_auc_score, precision_score, recall_score
import logging
from .dataset import ImageForgeryDataset
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml_pipeline")

class ForgeryCNN(nn.Module):
    def __init__(self):
        super(ForgeryCNN, self).__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2, 2)
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128 * 28 * 28, 512),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(512, 1),
            nn.Sigmoid()
        )

    def forward(self, x):
        x = self.features(x)
        return self.classifier(x)

def create_model():
    return ForgeryCNN()

def train_model(data_dir: str, epochs: int = 10, batch_size: int = 32):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using device: {device}")
    
    if not os.path.exists(data_dir):
        logger.error(f"Dataset directory {data_dir} not found.")
        return None

    train_dataset = ImageForgeryDataset(data_dir, is_train=True)
    val_dataset = ImageForgeryDataset(data_dir, is_train=False)
    
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=4)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    model = create_model().to(device)
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-4)

    logger.info("Starting training loop...")
    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        for inputs, labels in train_loader:
            inputs = inputs.to(device)
            labels = labels.float().unsqueeze(1).to(device)
            
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
            
        logger.info(f"Epoch {epoch+1}/{epochs} Loss: {running_loss/len(train_loader):.4f}")
        
        model.eval()
        all_preds = []
        all_labels = []
        with torch.no_grad():
            for inputs, labels in val_loader:
                outputs = model(inputs.to(device)).cpu().numpy()
                all_preds.extend(outputs)
                all_labels.extend(labels.numpy())
                
        y_true = np.array(all_labels)
        y_scores = np.array(all_preds)
        y_pred = (y_scores > 0.5).astype(int)
        
        if len(np.unique(y_true)) > 1:
            auc = roc_auc_score(y_true, y_scores)
            precision = precision_score(y_true, y_pred, zero_division=0)
            recall = recall_score(y_true, y_pred, zero_division=0)
            logger.info(f"Validation Metrics -> AUC: {auc:.4f} | Precision: {precision:.4f} | Recall: {recall:.4f}")
            
    torch.save(model.state_dict(), "forgery_model.pth")
    logger.info("Training complete. Weights saved to forgery_model.pth")
    return model

if __name__ == "__main__":
    train_model("/path/to/extracted/comofod_dataset")
