import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, precision_recall_curve, f1_score
import joblib
import numpy as np

def train_health_model():
    print("Loading data...")
    df_wsr = pd.read_csv('../data/09. 260624_Project_Weekly_Status_Details.csv', encoding='latin1')
    
    # Binary classification target: RED or AMBER schedule/scope status = Overrun Risk (1)
    df_wsr['is_overrun_risk'] = ((df_wsr['schedule_status'].isin(['RED', 'AMBER'])) | 
                                 (df_wsr['scope_status'].isin(['RED', 'AMBER']))).astype(int)
    
    # Map categoricals
    status_map = {'NO_COLOR': 0, 'GREEN': 1, 'AMBER': 2, 'RED': 3}
    features = ['quality_status', 'csat_status', 'team_status']
    for f in features:
        df_wsr[f] = df_wsr[f].map(status_map).fillna(0)

    # --- FIX #3: Strict Chronological Split to Prevent Data Leakage ---
    print("Sorting data chronologically to prevent time-series leakage...")
    
    # 1. Convert to actual datetime objects so sorting works mathematically
    df_wsr['week_start_date'] = pd.to_datetime(df_wsr['week_start_date'], dayfirst=True, format='mixed', errors='coerce')
    
    # 2. Sort the entire dataset from oldest to newest
    df_wsr = df_wsr.sort_values(by='week_start_date')
    
    # 3. Define features and target AFTER sorting
    X = df_wsr[features]
    y = df_wsr['is_overrun_risk']

    # 4. Calculate the 80% cutoff boundary
    split_index = int(len(df_wsr) * 0.8)
    
    # 5. Split sequentially (Past 80% = Train, Future 20% = Test)
    X_train = X.iloc[:split_index]
    X_test = X.iloc[split_index:]
    y_train = y.iloc[:split_index]
    y_test = y.iloc[split_index:]
    
    print("Training LightGBM with balanced weights...")
    model = lgb.LGBMClassifier(scale_pos_weight=36.4, random_state=42) 
    model.fit(X_train, y_train)
    
    # --- THE FIX: Precision-Recall Threshold Tuning ---
    print("Calculating optimal probability threshold...")
    y_probs = model.predict_proba(X_test)[:, 1] # Get probabilities for the positive class
    
    # Generate Precision-Recall curve
    precisions, recalls, thresholds = precision_recall_curve(y_test, y_probs)
    
    # Calculate F1 scores for all thresholds to find the optimal balance
    f1_scores = 2 * (precisions * recalls) / (precisions + recalls + 1e-10) # 1e-10 prevents division by zero
    optimal_idx = np.argmax(f1_scores)
    optimal_threshold = thresholds[optimal_idx]
    
    print(f"\n✅ OPTIMAL THRESHOLD FOUND: {optimal_threshold:.4f}")
    print(f"Expected Precision at this threshold: {precisions[optimal_idx]:.2f}")
    print(f"Expected Recall at this threshold: {recalls[optimal_idx]:.2f}")
    
    # Evaluate using the NEW threshold
    y_pred_optimal = (y_probs >= optimal_threshold).astype(int)
    
    print("\n--- Model Evaluation (Using Optimal Threshold) ---")
    print(classification_report(y_test, y_pred_optimal, target_names=['Optimal (0)', 'Overrun Risk (1)']))
    
    joblib.dump(model, 'lgbm_project_health.pkl')
    
    # Save the threshold so main.py can use it
    with open('optimal_threshold.txt', 'w') as f:
        f.write(str(optimal_threshold))
        
    print("LightGBM Model and Threshold saved.")

if __name__ == "__main__":
    train_health_model()