import asyncio
import datetime
import joblib
import pandas as pd
from prisma import Prisma
import shap
import warnings

# Suppress noisy SHAP conversion warnings in the terminal
warnings.filterwarnings("ignore", category=UserWarning, module="shap")

async def run_batch_predictions():
    db = Prisma()
    await db.connect()
    
    # Load the trained model and features
    model = joblib.load('lgbm_project_health.pkl')
    features = model.booster_.feature_name()
    
    with open('optimal_threshold.txt', 'r') as f:
        threshold = float(f.read().strip())

    # Initialize SHAP explainer
    explainer = shap.TreeExplainer(model)
    
    # 1. Load the latest WSR dataset
    df_wsr = pd.read_csv('../data/09. 260624_Project_Weekly_Status_Details.csv') 
    
    # Simulate grabbing the latest status for each project
    latest_projects = df_wsr.drop_duplicates(subset=['project_id_masked'], keep='last').copy()
    
    # Preprocess string categories into clean integers on the full DataFrame
    status_map = {'NO_COLOR': 0, 'GREEN': 1, 'AMBER': 2, 'RED': 3}
    for f in features:
        if f in latest_projects.columns:
            latest_projects[f] = latest_projects[f].astype(str).str.strip().map(status_map).fillna(0).astype(int)
    
    # Isolate a pure numeric matrix for LightGBM features upfront to preserve dtypes
    X_matrix = latest_projects[features].astype(int)
    
    print(f"🚀 Running automated risk prediction for {len(latest_projects)} projects...")
    success_count = 0
    
    for idx, row in latest_projects.iterrows():
        try:
            # Pull directly from the pure numeric matrix using the current row's dataframe index
            X_input = X_matrix.loc[[idx]] 
            
            # Predict Risk Probability
            risk_prob = model.predict_proba(X_input)[0][1]
            is_at_risk = bool(risk_prob > threshold)
            
            # Extract SHAP values robustly across versions
            raw_shap = explainer.shap_values(X_input)
            
            # Handle list-of-arrays vs raw-array shapes in binary classification
            if isinstance(raw_shap, list):
                shap_contributions = raw_shap[1][0]  # Class 1 (Positive Risk) contributions
            elif len(raw_shap.shape) == 3:
                shap_contributions = raw_shap[0, :, 1]
            else:
                shap_contributions = raw_shap[0]
            
            # Map features to their absolute SHAP importance value
            feature_importance = pd.DataFrame({
                'feature': features,
                'importance': shap_contributions
            })
            
            # Sort to find the highest driver pushing the score toward risk
            feature_importance['abs_importance'] = feature_importance['importance'].abs()
            feature_importance = feature_importance.sort_values(by='abs_importance', ascending=False)
            
            primary_driver = feature_importance.iloc[0]['feature']
            
            # Construct a pristine ISO-8601 string containing the trailing UTC specifier 'Z'
            current_timestamp_iso = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
            
            # Upsert directly into the database matching our schema.prisma structure
            await db.projectriskscore.upsert(
                where={"project_id": str(row['project_id_masked'])},
                data={
                    "create": {
                        "project_id": str(row['project_id_masked']),
                        "risk_probability": float(risk_prob),
                        "is_at_risk": is_at_risk,
                        "primary_driver": f"Degradation in {primary_driver}" if is_at_risk else "Stable",
                        "calculated_at": current_timestamp_iso
                    },
                    "update": {
                        "risk_probability": float(risk_prob),
                        "is_at_risk": is_at_risk,
                        "primary_driver": f"Degradation in {primary_driver}" if is_at_risk else "Stable",
                        "calculated_at": current_timestamp_iso
                    }
                }
            )
            success_count += 1
            
        except Exception as e:
            print(f"⚠️ Failed on project {row.get('project_id_masked', 'Unknown')}: {e}")
            continue
            
    print(f"\n✅ Batch prediction complete. Successfully persisted {success_count}/{len(latest_projects)} risk scores to the database.")
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(run_batch_predictions())
    
    
    
    
    
    