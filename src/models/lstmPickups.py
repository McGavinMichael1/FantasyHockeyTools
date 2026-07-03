# PARKED (July 2026): experimental sequence model, not on the product path.
# Kept for learning; XGBoost (src/models/pickups.py) is the product model.
# Note: loadLSTMData in lstmFeatures.py still uses the old G/A/SOG-only
# scoring — align it with fantasyPoints.SKATER_WEIGHTS before un-parking.

import pandas as pd
import torch
import torch.nn as nn
import numpy as np
import os
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader
from src.features.lstmFeatures import buildSequences, HockeySequenceDataset, SEQUENCE_FEATURES, loadLSTMData
from sklearn.preprocessing import StandardScaler
import pickle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'lstm', 'model.pt')
SCALER_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'lstm', 'scaler.pkl')

class LSTMPickupModel(nn.Module):
    def __init__(self, input_size, hidden_size=128, num_layers=2, dropout=0.3):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, 
                           batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_size, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        _, (hidden, _) = self.lstm(x)
        out = self.fc(hidden[-1])
        return out.squeeze(1)
    
def train(epochs=30, batch_size=512, hidden_size=64, num_layers=2, dropout=0.3):
    from src.features.mlFeatures import buildLabel
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Training on: {device}")

    best_auc = 0
    patience = 5
    epochs_without_improvement = 0

    lstm_df = loadLSTMData()
    lstm_df = buildLabel(lstm_df)
    lstm_df = lstm_df[lstm_df['season'] <= 2024]

    train_df = lstm_df[lstm_df['season'] <= 2022]
    val_df = lstm_df[lstm_df['season'] == 2023]

    
    X_train, y_train, _ = buildSequences(train_df)
    X_val, y_val, _ = buildSequences(val_df)
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train.reshape(-1, X_train.shape[-1])).reshape(X_train.shape)
    X_val = scaler.transform(X_val.reshape(-1, X_val.shape[-1])).reshape(X_val.shape)
    
    train_loader = DataLoader(HockeySequenceDataset(X_train, y_train), 
                              batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(HockeySequenceDataset(X_val, y_val), 
                            batch_size=batch_size, shuffle=False)

    model = LSTMPickupModel(input_size=len(SEQUENCE_FEATURES), 
                            hidden_size=hidden_size, 
                            num_layers=num_layers, 
                            dropout=dropout).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.BCEWithLogitsLoss()

    for epoch in range(epochs):
        model.train()
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            optimizer.zero_grad()
            preds = model(X_batch)
            loss = criterion(preds, y_batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        # Validation
        model.eval()
        all_preds, all_labels = [], []
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                X_batch = X_batch.to(device)
                preds = model(X_batch).cpu().numpy()
                all_preds.extend(preds)
                all_labels.extend(y_batch.numpy())

        val_auc = roc_auc_score(all_labels, all_preds)
        print(f"Epoch {epoch+1}/{epochs} — Val AUC: {val_auc:.4f}")

        if val_auc > best_auc:
            best_auc = val_auc
            epochs_without_improvement = 0
            save(model, hidden_size, num_layers)  # only save when improved
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                print(f"Early stopping at epoch {epoch+1}, best AUC: {best_auc:.4f}")
                break

    with open(SCALER_PATH, 'wb') as f:
        pickle.dump(scaler, f)

def predict(df):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = load().to(device)

    X, _, player_ids = buildSequences(df, has_label=False)
    
    with open(SCALER_PATH, 'rb') as f:
        scaler = pickle.load(f)
    X = scaler.transform(X.reshape(-1, X.shape[-1])).reshape(X.shape)
    dummy_y = np.zeros(len(X), dtype=np.float32)  # Placeholder since we don't have labels for prediction
    dataset = HockeySequenceDataset(X, dummy_y)
    loader = DataLoader(dataset, batch_size=512, shuffle=False)

    all_preds = []
    model.eval()
    with torch.no_grad():
        for X_batch, _ in loader:
            X_batch = X_batch.to(device)
            preds = torch.sigmoid(model(X_batch)).cpu().numpy()
            all_preds.extend(preds)

    preds_series = pd.Series(all_preds, index=player_ids)
    return preds_series.groupby(level=0).last()

def save(model, hidden_size, num_layers):
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    torch.save({'state_dict': model.state_dict(), 
                'hidden_size': hidden_size, 
                'num_layers': num_layers}, MODEL_PATH)


def load():
    checkpoint = torch.load(MODEL_PATH, weights_only=True)
    model = LSTMPickupModel(input_size=len(SEQUENCE_FEATURES),
                            hidden_size=checkpoint['hidden_size'],
                            num_layers=checkpoint['num_layers'])
    model.load_state_dict(checkpoint['state_dict'])
    model.eval()
    return model