"""
train_lgbm.py — JSpark v2 ML Training (FIXED)

ROOT CAUSE OF THRESHOLD=1.0:
  ✅ FIX 1 (CRITICAL): schedule_status and scope_status were used as BOTH the label definition
     AND model features. This created perfect label leakage — the model memorised its own target,
     yielding 1.00 precision/recall. The Precision-Recall curve's optimal point collapsed to the
     final threshold (~1.0). With batch_predict using `risk_prob > 1.0`, no project was ever
     flagged at-risk.

  The fix: schedule_status and scope_status stay as the LABEL (at-risk = either is RED/AMBER)
  but are EXCLUDED from features. The model now predicts risk from the 3 lagging indicators
  (quality, csat, team) — the same signals a PM would see without already knowing the answer.
  This mirrors the original 3-feature design from audit finding 1b, which was conceptually correct.

  ✅ FIX 2: Added CLEANED_DIR auto-detection (consistent with etl_pipeline.py fix).
  ✅ FIX 3: Threshold saved as float with full precision; guard added for degenerate threshold=1.0.
"""

import os
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import classification_report, precision_recall_curve
import joblib
import numpy as np

DATA_DIR = os.environ.get("DATA_DIR", "../data")
# Auto-detect cleaned dir (consistent with etl_pipeline.py)
_default_cleaned = os.path.join(DATA_DIR, "cleaned")
CLEANED_DIR = os.environ.get("CLEANED_DIR", _default_cleaned if os.path.isdir(_default_cleaned) else None)


def load_wsr() -> pd.DataFrame:
    candidates = []
    if CLEANED_DIR:
        candidates.append(os.path.join(CLEANED_DIR, "09_wsr_clean.csv"))
    candidates += [
        os.path.join(DATA_DIR, "09_260624_Project_Weekly_Status_Details.csv"),
        os.path.join(DATA_DIR, "09. 260624_Project_Weekly_Status_Details.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            print(f"  ✓ Loading WSR from: {path}")
            return pd.read_csv(path, encoding="latin1")
    raise FileNotFoundError(f"WSR file not found. Searched: {candidates}")


def train_health_model():
    print("📈 Loading WSR data…")
    df_wsr = load_wsr()

    # ── Filter epoch artefacts ────────────────────────────────────────────
    df_wsr["week_start_date"] = pd.to_datetime(
        df_wsr["week_start_date"], dayfirst=True, format="mixed", errors="coerce"
    )
    before = len(df_wsr)
    df_wsr = df_wsr[df_wsr["week_start_date"].dt.year >= 2000].copy()
    print(f"  ✓ Filtered {before - len(df_wsr)} epoch artefact rows. Valid rows: {len(df_wsr)}")

    # ── Binary target: at-risk if schedule OR scope is RED/AMBER ──────────
    # These two columns DEFINE the label and must NOT appear as features (FIX 1).
    df_wsr["at_risk"] = (
        (df_wsr["schedule_status"].isin(["RED", "AMBER"])) |
        (df_wsr["scope_status"].isin(["RED", "AMBER"]))
    ).astype(int)

    label_dist = df_wsr["at_risk"].value_counts()
    print(f"  ✓ Label distribution: {label_dist.to_dict()}")
    pos_rate = label_dist.get(1, 0) / len(df_wsr)
    scale_pos_weight = (1 - pos_rate) / pos_rate if pos_rate > 0 else 10.0
    print(f"  ✓ scale_pos_weight = {scale_pos_weight:.1f}")

    # ── FEATURE SET ───────────────────────────────────────────────────────
    # FIX 1: Use only the 3 LAGGING indicators as features.
    # schedule_status and scope_status define the label — including them as features
    # causes perfect leakage (model sees the answer → threshold collapses to 1.0 →
    # batch_predict never flags anything as at-risk since risk_prob > 1.0 is impossible).
    #
    # quality_status, csat_status, team_status are the signals a PM observes BEFORE
    # schedule/scope problems surface — exactly what a predictive risk model should use.
    features = [
        "quality_status",
        "csat_status",
        "team_status",
    ]

    status_map = {"NO_COLOR": 0, "GREEN": 1, "AMBER": 2, "RED": 3}
    for f in features:
        df_wsr[f] = df_wsr[f].astype(str).str.strip().map(status_map).fillna(0).astype(int)

    # ── Chronological split — no data leakage ────────────────────────────
    print("  ✓ Sorting chronologically to prevent time-series leakage…")
    df_wsr = df_wsr.sort_values("week_start_date")

    X = df_wsr[features]
    y = df_wsr["at_risk"]

    split_idx = int(len(df_wsr) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"  ✓ Train: {len(X_train)} rows | Test: {len(X_test)} rows")
    print(f"  ✓ Test label distribution: {y_test.value_counts().to_dict()}")

    # ── Train ─────────────────────────────────────────────────────────────
    print("\n🤖 Training LightGBM…")
    model = lgb.LGBMClassifier(
        scale_pos_weight=scale_pos_weight,
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(50)],
    )

    # ── Optimal threshold via Precision-Recall curve ───────────────────────
    print("\n📐 Finding optimal probability threshold…")
    y_probs = model.predict_proba(X_test)[:, 1]
    precisions, recalls, thresholds = precision_recall_curve(y_test, y_probs)
    f1_scores = 2 * (precisions * recalls) / (precisions + recalls + 1e-10)
    # Exclude the last element of precisions/recalls (no corresponding threshold)
    f1_scores_for_thresh = f1_scores[:-1]
    optimal_idx = np.argmax(f1_scores_for_thresh)
    optimal_threshold = float(thresholds[optimal_idx])

    # FIX 3: Guard against degenerate threshold — fall back to 0.5 if model is broken
    if optimal_threshold >= 1.0:
        print(
            f"\n  ⚠️  WARNING: Optimal threshold is {optimal_threshold:.4f} — model may have leakage."
            "\n     Check that label-defining columns are not also used as features."
            "\n     Falling back to threshold=0.5 for safety."
        )
        optimal_threshold = 0.5

    print(f"\n  ✅ OPTIMAL THRESHOLD: {optimal_threshold:.4f}")
    print(f"     Precision: {precisions[optimal_idx]:.2f}  |  Recall: {recalls[optimal_idx]:.2f}")

    y_pred_optimal = (y_probs >= optimal_threshold).astype(int)
    print("\n--- Model Evaluation (Optimal Threshold) ---")
    print(classification_report(y_test, y_pred_optimal, target_names=["Healthy", "At Risk"]))

    # ── Feature importance ────────────────────────────────────────────────
    importance = dict(zip(features, model.feature_importances_))
    print("\n📊 Feature Importance:")
    for feat, imp in sorted(importance.items(), key=lambda x: -x[1]):
        print(f"   {feat:<25} {imp:.0f}")

    # ── Save ──────────────────────────────────────────────────────────────
    joblib.dump(model, "lgbm_project_health.pkl")
    with open("optimal_threshold.txt", "w") as f:
        f.write(str(optimal_threshold))

    print("\n✅ Model and threshold saved.")


if __name__ == "__main__":
    train_health_model()
