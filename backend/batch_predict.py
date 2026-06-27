"""
batch_predict.py — JSpark v2 Batch Risk Prediction (FIXED v2)

Additional fixes beyond v1:
  ✅ FIX A: When DB WeeklyStatus is empty, batch_predict now falls back to CSV but
     VALIDATES project IDs against the Project table before attempting FK insert.
     Previously it tried to insert risk scores for ALL 1773 WSR project IDs,
     all of which failed FK because the DB was wiped (db push --force-reset) after ETL ran.
     Now it pre-fetches valid project IDs from DB and filters WSR to only those.

  ✅ FIX B: Clear error message when the Project table itself is empty,
     explaining the required run order: db push → etl_pipeline.py → train_lgbm.py → batch_predict.py

  ✅ FIX C: Model feature count validation — warns if model was trained with schedule/scope
     leakage (3 features expected after fix; 5 = old broken model still on disk).

  ✅ FIX 1 (from v1): calculated_at passes datetime object, not ISO string.
  ✅ FIX 2 (from v1): Sort by date before dedup for true latest status.
  ✅ FIX 3 (from v1): FK misses counted and reported as summary, not per-row spam.
  ✅ FIX 4 (from v1): Timezone-aware datetime stripping.
"""

import asyncio
import datetime
import os
import sys
import joblib
import pandas as pd
from prisma import Prisma
import shap
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="shap")

DATA_DIR = os.environ.get("DATA_DIR", "../data")
_default_cleaned = os.path.join(DATA_DIR, "cleaned")
CLEANED_DIR = os.environ.get("CLEANED_DIR", _default_cleaned if os.path.isdir(_default_cleaned) else None)

EXPECTED_FEATURES = {"quality_status", "csat_status", "team_status"}
LEAKY_FEATURES = {"schedule_status", "scope_status"}


def _load_wsr_from_file() -> pd.DataFrame:
    candidates = []
    if CLEANED_DIR:
        candidates.append(os.path.join(CLEANED_DIR, "09_wsr_clean.csv"))
    candidates += [
        os.path.join(DATA_DIR, "09_260624_Project_Weekly_Status_Details.csv"),
        os.path.join(DATA_DIR, "09. 260624_Project_Weekly_Status_Details.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            print(f"  ℹ️  Loading WSR from: {path}")
            return pd.read_csv(path, encoding="latin1")
    raise FileNotFoundError(f"WSR file not found. Searched: {candidates}")


async def _load_wsr_from_db(db: Prisma) -> pd.DataFrame:
    records = await db.weeklystatus.find_many()
    if not records:
        return pd.DataFrame()
    rows = [
        {
            "project_id_masked": r.project_id,
            "week_start_date": r.week_start_date,
            "schedule_status": r.schedule_status,
            "scope_status": r.scope_status,
            "budget_status": r.budget_status,
            "quality_status": r.quality_status,
            "csat_status": r.csat_status,
            "team_status": r.team_status,
        }
        for r in records
    ]
    return pd.DataFrame(rows)


async def run_batch_predictions(use_db: bool = True):
    db = Prisma()
    await db.connect()

    # ── Load model ────────────────────────────────────────────────────────
    model = joblib.load("lgbm_project_health.pkl")
    features = model.booster_.feature_name()
    print(f"  ℹ️  Model features: {features}")

    # FIX C: Warn if model still uses the leaky features (old model on disk)
    feature_set = set(features)
    if LEAKY_FEATURES.issubset(feature_set):
        print(
            "\n  ⚠️  WARNING: Model was trained with schedule_status and scope_status as features."
            "\n     These columns DEFINE the label — the model has data leakage."
            "\n     Risk scores will be unreliable. Re-run: python train_lgbm.py\n"
        )

    with open("optimal_threshold.txt", "r") as f:
        threshold = float(f.read().strip())
    print(f"  ℹ️  Threshold: {threshold:.4f}")

    if threshold >= 1.0:
        print(
            "  ⚠️  WARNING: Threshold is 1.0 — no project will ever be flagged at-risk."
            "\n     This is caused by data leakage in training. Re-run: python train_lgbm.py"
        )

    explainer = shap.TreeExplainer(model)

    # FIX A: Pre-fetch valid project IDs from DB for FK validation select={"id": True}
    db_projects = await db.project.find_many()
    if not db_projects:
        print(
            "\n❌ Project table is empty. Batch prediction cannot run."
            "\n   Run in this order:"
            "\n     1. prisma db push"
            "\n     2. python etl_pipeline.py"
            "\n     3. python train_lgbm.py"
            "\n     4. python batch_predict.py"
        )
        await db.disconnect()
        sys.exit(1)

    valid_project_ids = {p.id for p in db_projects}
    print(f"  ℹ️  {len(valid_project_ids)} projects in DB available for risk scoring")

    # ── LOAD WSR ──────────────────────────────────────────────────────────
    if use_db:
        df_wsr = await _load_wsr_from_db(db)
        if df_wsr.empty:
            print("  ⚠️  DB WeeklyStatus table is empty — falling back to CSV.")
            print("     (This means db push --force-reset was run after etl_pipeline.py)")
            print("     Re-run etl_pipeline.py to repopulate, or continuing with CSV fallback…")
            df_wsr = _load_wsr_from_file()
    else:
        df_wsr = _load_wsr_from_file()

    # Fix CLIENT_661 dash→underscore
    if "project_id_masked" in df_wsr.columns:
        df_wsr["project_id_masked"] = (
            df_wsr["project_id_masked"]
            .astype(str)
            .str.replace(r"CLIENT_661-", "CLIENT_661_", regex=True)
        )

    # FIX 4: Parse dates (handles both string CSV and datetime DB rows)
    if "week_start_date" in df_wsr.columns:
        df_wsr["week_start_date"] = pd.to_datetime(
            df_wsr["week_start_date"], dayfirst=True, format="mixed", errors="coerce", utc=False
        )
        # Strip timezone if present
        if df_wsr["week_start_date"].dt.tz is not None:
            df_wsr["week_start_date"] = df_wsr["week_start_date"].dt.tz_localize(None)

        before = len(df_wsr)
        df_wsr = df_wsr[df_wsr["week_start_date"].dt.year >= 2000].copy()
        filtered = before - len(df_wsr)
        if filtered > 0:
            print(f"  ✓ Filtered {filtered} epoch artefact rows")

    # FIX 2: Sort by date BEFORE dedup — ensures 'last' = most recent
    df_wsr = df_wsr.sort_values("week_start_date", ascending=True)
    latest_projects = df_wsr.drop_duplicates(subset=["project_id_masked"], keep="last").copy()

    # FIX A: Filter WSR to only project IDs that exist in the DB
    before_filter = len(latest_projects)
    latest_projects = latest_projects[
        latest_projects["project_id_masked"].isin(valid_project_ids)
    ].copy()
    skipped_fk = before_filter - len(latest_projects)
    if skipped_fk > 0:
        print(
            f"  ℹ️  {skipped_fk} WSR projects not in Project table (COMPLETE/CLOSED not ingested) — skipped"
        )

    if latest_projects.empty:
        print(
            "\n❌ No WSR projects match the Project table."
            "\n   If you ran 'prisma db push --force-reset' after 'etl_pipeline.py',"
            "\n   the database was wiped. Re-run etl_pipeline.py first."
        )
        await db.disconnect()
        return

    # Map status strings to integers
    status_map = {"NO_COLOR": 0, "GREEN": 1, "AMBER": 2, "RED": 3}
    for f in features:
        if f in latest_projects.columns:
            latest_projects[f] = (
                latest_projects[f].astype(str).str.strip().map(status_map).fillna(0).astype(int)
            )
        else:
            print(f"  ⚠️  Feature '{f}' not in WSR columns — defaulting to 0")
            latest_projects[f] = 0

    X_matrix = latest_projects[features].astype(int)

    print(f"🚀 Running batch risk prediction for {len(latest_projects)} projects…")
    success_count = 0
    # FIX 1: datetime object, not ISO string
    timestamp = datetime.datetime.now(datetime.timezone.utc)

    for idx, row in latest_projects.iterrows():
        pid = str(row.get("project_id_masked", ""))
        if not pid:
            continue
        try:
            X_input = X_matrix.loc[[idx]]
            risk_prob = model.predict_proba(X_input)[0][1]
            is_at_risk = bool(risk_prob > threshold)

            raw_shap = explainer.shap_values(X_input)
            if isinstance(raw_shap, list):
                shap_contributions = raw_shap[1][0]
            elif len(raw_shap.shape) == 3:
                shap_contributions = raw_shap[0, :, 1]
            else:
                shap_contributions = raw_shap[0]

            feature_importance = pd.DataFrame(
                {"feature": features, "importance": shap_contributions}
            )
            feature_importance["abs_importance"] = feature_importance["importance"].abs()
            feature_importance = feature_importance.sort_values("abs_importance", ascending=False)
            primary_driver = feature_importance.iloc[0]["feature"]

            await db.projectriskscore.upsert(
                where={"project_id": pid},
                data={
                    "create": {
                        "project_id": pid,
                        "risk_probability": float(risk_prob),
                        "is_at_risk": is_at_risk,
                        "primary_driver": (
                            f"Degradation in {primary_driver}" if is_at_risk else "Stable"
                        ),
                        "calculated_at": timestamp,
                    },
                    "update": {
                        "risk_probability": float(risk_prob),
                        "is_at_risk": is_at_risk,
                        "primary_driver": (
                            f"Degradation in {primary_driver}" if is_at_risk else "Stable"
                        ),
                        "calculated_at": timestamp,
                    },
                },
            )
            success_count += 1
        except Exception as e:
            print(f"  ⚠️  Failed on project {pid}: {e}")

    print(f"\n✅ Batch complete: {success_count}/{len(latest_projects)} risk scores persisted.")
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(run_batch_predictions())
