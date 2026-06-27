"""
main.py — JSpark v2 API
Implements all 5 deliverables from the problem statement:
  ✅ 1a. Resource Recommendation Engine — ranked list, availability gate, skill + competency
  ✅ 1b. Project Health & Efficiency Monitor — ramp-down, overrun, leakage, SHAP root cause
  ✅ 2a. Demand Forecast (NEW) — simulate N new projects → headcount demand by role
  ✅ 2b. 6-Month Pipeline Outlook (FIXED) — monthly Jul–Dec 2026, SOW filter, role breakdown
  ✅ 3.  Current-State Allocation Report — per-person utilisation, billability, roll-off
"""

import difflib
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date, timezone
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import redis.asyncio as redis
import shap
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prisma import Prisma

from ai_engine import build_vector_db, recommend_resource, collection

# ─────────────────────────────────────────────────────────────────────────────
# INFRASTRUCTURE
# ─────────────────────────────────────────────────────────────────────────────

redis_client = redis.Redis(
    host="localhost", port=6379, db=0, decode_responses=True, protocol=2
)

try:
    health_model = joblib.load("lgbm_project_health.pkl")
    explainer = shap.TreeExplainer(health_model)
    MODEL_FEATURES = health_model.booster_.feature_name()
    print(f"✅ ML model loaded. Features: {MODEL_FEATURES}")
except Exception as e:
    print(f"⚠️  ML model not found: {e}. Run train_lgbm.py first.")
    health_model = None
    explainer = None
    MODEL_FEATURES = ["quality_status", "csat_status", "team_status", "schedule_status", "scope_status"]

db = Prisma()

STATUS_MAP = {"NO_COLOR": 0, "GREEN": 1, "AMBER": 2, "RED": 3}

# Role-mix templates: project_type → {role: FTE_ratio}
# Derived from historical allocation + problem statement §D&D template
ROLE_MIX_TEMPLATES: dict[str, dict[str, float]] = {
    "D&D Tactical Build": {
        "Senior Software Engineer": 0.50,
        "Software Engineer": 0.25,
        "Solution Architect": 0.125,
        "Solution Consultant": 0.125,
    },
    "Data Engineering": {
        "Senior Software Engineer": 0.40,
        "Software Engineer": 0.30,
        "Solution Architect": 0.10,
        "Data Analyst": 0.20,
    },
    "Data Science & AI": {
        "Senior Software Engineer": 0.30,
        "Software Engineer": 0.20,
        "Data Scientist": 0.30,
        "Solution Architect": 0.10,
        "Solution Consultant": 0.10,
    },
    "BI & Reporting": {
        "Software Engineer": 0.40,
        "Data Analyst": 0.40,
        "Solution Consultant": 0.20,
    },
    "Consulting": {
        "Solution Consultant": 0.50,
        "Solution Enabler": 0.30,
        "Solution Architect": 0.20,
    },
    "default": {
        "Senior Software Engineer": 0.40,
        "Software Engineer": 0.35,
        "Solution Architect": 0.125,
        "Solution Consultant": 0.125,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN — connect DB; auto-build vector store if empty
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    # Auto-build vector DB if collection is empty
    try:
        count = collection.count()
        if count == 0:
            print("🔄 Vector store is empty — building now…")
            await build_vector_db()
        else:
            print(f"✅ Vector store ready ({count} profiles indexed).")
    except Exception as e:
        print(f"⚠️  Vector store check failed: {e}")
    yield
    await db.disconnect()


app = FastAPI(title="JSpark — Resourcing CoLab API v2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _optimal_threshold() -> float:
    try:
        with open("optimal_threshold.txt", "r") as f:
            return float(f.read().strip())
    except Exception:
        return 0.5


def _status_int(val: str) -> int:
    return STATUS_MAP.get(str(val).strip().upper(), 0)


PLACEHOLDER_DATES = {"2030-12-31", "2035-12-31"}


def _is_placeholder(dt) -> bool:
    if dt is None:
        return False
    try:
        return str(dt.date())[:10] in PLACEHOLDER_DATES or dt.year >= 2030
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# DELIVERABLE 1a — Resource Recommendation Engine
# ═════════════════════════════════════════════════════════════════════════════

class RecommendationRequest(BaseModel):
    requirements: str
    role: str


@app.post("/api/recommend")
async def get_recommendation(req: RecommendationRequest):
    """
    Ranked list of top-3 available employees matched by skill + competency.
    Availability-gated: over-committed staff are excluded.
    Falls back to "Initiate Hire" signal if no match found.
    """
    req_clean = (req.requirements or "").strip()
    role_clean = (req.role or "").strip()

    if not role_clean or len(req_clean) < 10:
        raise HTTPException(
            status_code=400,
            detail="Role cannot be empty and requirements must be > 10 characters.",
        )

    try:
        result = await recommend_resource(req_clean, role_clean, db)

        if result["status"] == "NO_MATCH_FOUND":
            # Strategic Hiring Aggregator with fuzzy deduplication
            existing_gaps = await db.skillgap.find_many(where={"role": role_clean})
            is_duplicate = any(
                difflib.SequenceMatcher(None, req_clean.lower(), g.requirements.lower()).ratio() > 0.80
                for g in existing_gaps
            )
            if not is_duplicate:
                await db.skillgap.create(data={"role": role_clean, "requirements": req_clean})

        elif result["status"] == "MATCH_FOUND":
            # Immutable AI Audit Trail — log each ranked candidate
            for candidate in result["candidates"]:
                await db.airecommendationlog.create(
                    data={
                        "employee_id": candidate["employee_id"],
                        "role_requested": role_clean,
                        "requirements": req_clean,
                        "cosine_distance": candidate["cosine_distance"],
                        "rationale_text": candidate["rationale"],
                        "rank": candidate["rank"],
                    }
                )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vector-db/rebuild")
async def rebuild_vector_db():
    """Manually trigger a rebuild of the ChromaDB vector store."""
    try:
        await build_vector_db()
        return {"status": "ok", "message": "Vector database rebuilt successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/audit-log")
async def get_ai_audit_log(limit: int = 20):
    logs = await db.airecommendationlog.find_many(
        order={"generated_at": "desc"}, take=limit
    )
    return {"audit_trail": logs}


@app.get("/api/dashboard/skill-gaps")
async def get_skill_gaps(limit: int = 20):
    gaps = await db.skillgap.find_many(order={"logged_at": "desc"}, take=limit)
    return {"recent_skill_gaps": gaps, "total": len(gaps)}


# ═════════════════════════════════════════════════════════════════════════════
# DELIVERABLE 1b — Project Health & Efficiency Monitor
# ═════════════════════════════════════════════════════════════════════════════

class HealthRiskRequest(BaseModel):
    quality_status: str
    csat_status: str
    team_status: str
    schedule_status: Optional[str] = "NO_COLOR"
    scope_status: Optional[str] = "NO_COLOR"


@app.post("/api/predict-risk")
async def predict_project_risk(req: HealthRiskRequest):
    """SHAP-explained risk prediction for a single project status snapshot."""
    if not health_model:
        raise HTTPException(status_code=503, detail="ML model not loaded. Run train_lgbm.py.")

    input_data = {
        "quality_status": _status_int(req.quality_status),
        "csat_status": _status_int(req.csat_status),
        "team_status": _status_int(req.team_status),
        "schedule_status": _status_int(req.schedule_status or "NO_COLOR"),
        "scope_status": _status_int(req.scope_status or "NO_COLOR"),
    }
    # Only pass features the model was trained on
    input_df = pd.DataFrame([{f: input_data.get(f, 0) for f in MODEL_FEATURES}])

    risk_prob = health_model.predict_proba(input_df)[0][1]
    BASE_THRESHOLD = _optimal_threshold()

    # SHAP root-cause extraction
    shap_values = explainer.shap_values(input_df)
    target_shap = shap_values[1][0] if isinstance(shap_values, list) else shap_values[0]
    max_feature_idx = int(np.argmax(np.abs(target_shap)))
    root_cause_feature = input_df.columns[max_feature_idx].replace("_", " ").title()
    shap_direction = "worsening" if target_shap[max_feature_idx] > 0 else "improving"

    risk_tier = "LOW"
    action = "On Track"
    root_cause_msg = "No significant risk drivers detected."

    if risk_prob >= BASE_THRESHOLD * 1.5:
        risk_tier = "HIGH"
        action = "Immediate Review Required: Potential Escalation"
        root_cause_msg = f"Primary Driver: {root_cause_feature} is {shap_direction} project health"
    elif risk_prob >= BASE_THRESHOLD:
        risk_tier = "MEDIUM"
        action = "Monitor Closely: Velocity Drift Detected"
        root_cause_msg = f"Primary Driver: Instability in {root_cause_feature}"

    return {
        "risk_probability": round(float(risk_prob), 3),
        "risk_tier": risk_tier,
        "recommended_action": action,
        "root_cause_explainer": root_cause_msg,
        "threshold_used": round(BASE_THRESHOLD, 3),
        "shap_breakdown": {
            f: round(float(v), 4)
            for f, v in zip(input_df.columns, target_shap)
        },
    }


@app.get("/api/risk-scores")
async def get_risk_scores(project_id: Optional[str] = None, at_risk_only: bool = False):
    if project_id:
        score = await db.projectriskscore.find_unique(where={"project_id": project_id})
        if not score:
            raise HTTPException(status_code=404, detail="Risk score not found for that project.")
        return score

    where_clause = {"is_at_risk": True} if at_risk_only else {}
    scores = await db.projectriskscore.find_many(
        where=where_clause, order={"risk_probability": "desc"}
    )
    return {
        "total": len(scores),
        "at_risk_count": sum(1 for s in scores if s.is_at_risk),
        "active_risk_assessments": scores,
    }


@app.get("/api/dashboard/ramp-down")
async def get_ramp_down_candidates():
    """
    Deliverable 1b: Projects approaching natural end (30/60/90 days) AND overrunning projects.
    Surfaces capacity that will be released — enables proactive redeployment.
    """
    now = datetime.now(timezone.utc)
    windows = {
        "30_days": now + timedelta(days=30),
        "60_days": now + timedelta(days=60),
        "90_days": now + timedelta(days=90),
    }

    active_projects = await db.project.find_many(
        where={"status": {"in": ["ACTIVE", "DEAL WON"]}},
        include={"allocations": {"include": {"employee": True}}},
    )

    ramp_down = []
    overrunning = []

    for proj in active_projects:
        end_dt = proj.project_end_date
        if not end_dt or _is_placeholder(end_dt):
            continue

        active_allocs = [a for a in (proj.allocations or []) if a.is_allocation_active]
        ftes_releasing = round(sum(a.percentage / 100 for a in active_allocs), 2)

        if end_dt < now:
            overrunning.append({
                "project_id": proj.id,
                "project_type": proj.type_of_project,
                "project_end_date": end_dt.date().isoformat(),
                "days_overrun": (now - end_dt).days,
                "active_resources": len(active_allocs),
                "ftes_still_committed": ftes_releasing,
                "action": "Immediate review — project past end date but still ACTIVE",
            })
        else:
            window_label = None
            for label, threshold in windows.items():
                if end_dt <= threshold:
                    window_label = label
                    break

            if window_label:
                ramp_down.append({
                    "project_id": proj.id,
                    "project_type": proj.type_of_project,
                    "project_end_date": end_dt.date().isoformat(),
                    "days_until_end": (end_dt - now).days,
                    "window": window_label,
                    "active_resources": len(active_allocs),
                    "billable_resources": sum(1 for a in active_allocs if a.status == "BILLABLE"),
                    "ftes_releasing": ftes_releasing,
                    "rolling_off_employees": [
                        {"employee_id": a.employee_id, "designation": a.employee.designation if a.employee else None}
                        for a in active_allocs[:5]  # top 5 for brevity
                    ],
                })

    ramp_down.sort(key=lambda x: x["days_until_end"])

    return {
        "summary": {
            "overrunning_projects": len(overrunning),
            "ramp_down_30_days": sum(1 for r in ramp_down if r["window"] == "30_days"),
            "ramp_down_60_days": sum(1 for r in ramp_down if r["window"] == "60_days"),
            "ramp_down_90_days": sum(1 for r in ramp_down if r["window"] == "90_days"),
            "total_ftes_releasing_30d": round(sum(r["ftes_releasing"] for r in ramp_down if r["window"] == "30_days"), 2),
        },
        "ramp_down_candidates": ramp_down,
        "overrunning_projects": sorted(overrunning, key=lambda x: -x["days_overrun"]),
    }


# ═════════════════════════════════════════════════════════════════════════════
# DELIVERABLE 2a — Demand Forecast: New Projects
# ═════════════════════════════════════════════════════════════════════════════

class NewProject(BaseModel):
    project_type: str
    start_date: str  # ISO date string
    num_resources: int = 4  # total headcount needed
    duration_weeks: int = 16


class DemandForecastRequest(BaseModel):
    new_projects: list[NewProject]


@app.post("/api/demand-forecast")
async def demand_forecast(req: DemandForecastRequest):
    """
    Deliverable 2a: Simulate N new projects entering the pipeline.
    Returns per-role headcount demand, current availability pool, and shortfall.
    """
    # ── Aggregate demand by role using role-mix templates ─────────────────
    demand_by_role: dict[str, float] = defaultdict(float)
    project_breakdown = []

    for proj in req.new_projects:
        template = ROLE_MIX_TEMPLATES.get(proj.project_type, ROLE_MIX_TEMPLATES["default"])
        role_demand = {role: round(ratio * proj.num_resources, 2) for role, ratio in template.items()}
        project_breakdown.append({
            "project_type": proj.project_type,
            "start_date": proj.start_date,
            "num_resources": proj.num_resources,
            "duration_weeks": proj.duration_weeks,
            "template_used": proj.project_type if proj.project_type in ROLE_MIX_TEMPLATES else "default",
            "role_demand": role_demand,
        })
        for role, count in role_demand.items():
            demand_by_role[role] += count

    # ── Current availability pool ─────────────────────────────────────────
    # Bench = Delivery employees with 0 active billable allocations
    # Rolling off = employees whose allocation ends within 30 days
    today = datetime.now(timezone.utc)
    thirty_days = today + timedelta(days=30)

    employees = await db.employee.find_many(
        where={"is_recommended_pool": True},
        include={"allocations": True},
    )

    bench: dict[str, list] = defaultdict(list)           # role → [employee_ids]
    rolling_off: dict[str, list] = defaultdict(list)

    for emp in employees:
        desig = emp.designation or "Unknown"
        active_billable = [
            a for a in (emp.allocations or [])
            if a.is_allocation_active and a.status == "BILLABLE" and not a.is_placeholder_date
        ]

        if not active_billable:
            bench[desig].append(emp.id)
        else:
            # Check if they roll off within 30 days
            rolling = [
                a for a in active_billable
                if a.allocated_end_date and today <= a.allocated_end_date <= thirty_days
            ]
            if rolling:
                rolling_off[desig].append(emp.id)

    # ── Shortfall analysis ────────────────────────────────────────────────
    shortfall_analysis = []
    total_shortfall_fte = 0.0

    for role, needed in sorted(demand_by_role.items(), key=lambda x: -x[1]):
        on_bench = len(bench.get(role, []))
        rolling = len(rolling_off.get(role, []))
        available = on_bench + rolling
        gap = max(0.0, needed - available)
        total_shortfall_fte += gap

        redeployment_candidates = []
        if gap > 0:
            # Find partially available employees in this role
            for emp in employees:
                if (emp.designation or "") != role:
                    continue
                committed = sum(
                    a.percentage for a in (emp.allocations or [])
                    if a.is_allocation_active and a.status == "BILLABLE"
                )
                if 0 < committed < 100:
                    redeployment_candidates.append({
                        "employee_id": emp.id,
                        "available_pct": 100 - committed,
                    })
            redeployment_candidates.sort(key=lambda x: -x["available_pct"])

        shortfall_analysis.append({
            "role": role,
            "demand_fte": round(needed, 2),
            "bench_available": on_bench,
            "rolling_off_30d": rolling,
            "total_available": available,
            "shortfall_fte": round(gap, 2),
            "status": "SHORTFALL" if gap > 0 else ("TIGHT" if available <= needed * 1.1 else "SUFFICIENT"),
            "redeployment_candidates": redeployment_candidates[:3],
            "hire_signal": gap > 0.5,
        })

    return {
        "summary": {
            "new_projects_simulated": len(req.new_projects),
            "total_headcount_demand": round(sum(demand_by_role.values()), 1),
            "total_shortfall_fte": round(total_shortfall_fte, 2),
            "can_absorb": total_shortfall_fte == 0,
            "hiring_roles": [s["role"] for s in shortfall_analysis if s["hire_signal"]],
        },
        "project_breakdown": project_breakdown,
        "role_demand_summary": dict(sorted(demand_by_role.items(), key=lambda x: -x[1])),
        "shortfall_analysis": shortfall_analysis,
    }


# ═════════════════════════════════════════════════════════════════════════════
# DELIVERABLE 2b — 6-Month Pipeline Outlook (FIXED)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard/pipeline-outlook")
async def get_pipeline_outlook(sow_filter: str = Query("confirmed", description="confirmed | speculative | all")):
    """
    Deliverable 2b: Month-by-month Jul–Dec 2026 demand + supply outlook.
    sow_filter=confirmed → SOW Signed=Yes (hard gate)
    sow_filter=speculative → SOW Signed=No
    sow_filter=all → no filter
    """
    # Monthly buckets: Jul–Dec 2026
    MONTHS = [
    (
        datetime(2026, m, 1, tzinfo=timezone.utc), 
        datetime(2026, m + 1, 1, tzinfo=timezone.utc) if m < 12 else datetime(2027, 1, 1, tzinfo=timezone.utc)
    )
    for m in range(7, 13)
    ]
    MONTH_LABELS = [f"2026-{m:02d}" for m in range(7, 13)]

    # ── Pipeline demand ───────────────────────────────────────────────────
    where_clause = {}
    if sow_filter == "confirmed":
        where_clause["sow_signed"] = True
    elif sow_filter == "speculative":
        where_clause["sow_signed"] = False

    pipeline = await db.pipelinerequest.find_many(where=where_clause)

    # Map pipeline requests to monthly demand by role
    monthly_demand: dict[str, dict[str, float]] = {m: defaultdict(float) for m in MONTH_LABELS}

    for req in pipeline:
        if not req.start_date:
            continue
        start = req.start_date
        num_weeks = req.num_weeks or 16
        end = start + timedelta(weeks=num_weeks)
        role = req.canonical_role or req.role or "Unknown"
        alloc_pct = (req.allocation_pct or 100) / 100

        for label, (m_start, m_end) in zip(MONTH_LABELS, MONTHS):
            # Does this request overlap with this month?
            overlap_start = max(start, m_start)
            overlap_end = min(end, m_end)
            if overlap_start < overlap_end:
                monthly_demand[label][role] += alloc_pct

    # ── Supply: employees rolling off (becoming available) each month ──────
    employees = await db.employee.find_many(
        where={"is_recommended_pool": True},
        include={"allocations": True},
    )

    monthly_supply: dict[str, dict[str, int]] = {m: defaultdict(int) for m in MONTH_LABELS}

    for emp in employees:
        desig = emp.designation or "Unknown"
        for label, (m_start, m_end) in zip(MONTH_LABELS, MONTHS):
            # Employee is available in this month if they have no active billable alloc overlapping it
            active_in_month = any(
                a.is_allocation_active
                and a.status == "BILLABLE"
                and not a.is_placeholder_date
                and (a.allocated_end_date is None or a.allocated_end_date > m_start)
                and (a.allocated_start_date is None or a.allocated_start_date < m_end)
                for a in (emp.allocations or [])
            )
            if not active_in_month:
                monthly_supply[label][desig] += 1

    # ── Build output ──────────────────────────────────────────────────────
    monthly_outlook = []
    for label, (m_start, m_end) in zip(MONTH_LABELS, MONTHS):
        demand = dict(monthly_demand[label])
        supply = dict(monthly_supply[label])

        all_roles = set(demand) | set(supply)
        role_breakdown = []
        for role in sorted(all_roles):
            d = round(demand.get(role, 0), 2)
            s = supply.get(role, 0)
            role_breakdown.append({
                "role": role,
                "demand_fte": d,
                "supply_headcount": s,
                "gap": round(d - s, 2),
                "status": "SHORTFALL" if d > s else "SURPLUS" if s > d * 1.2 else "BALANCED",
            })

        role_breakdown.sort(key=lambda x: -(abs(x["gap"])))

        monthly_outlook.append({
            "month": label,
            "total_demand_fte": round(sum(demand.values()), 2),
            "total_supply_headcount": sum(supply.values()),
            "role_breakdown": role_breakdown,
            "critical_gaps": [r for r in role_breakdown if r["status"] == "SHORTFALL"],
        })

    return {
        "sow_filter": sow_filter,
        "pipeline_count": len(pipeline),
        "forecast_anchor": "2026-07-01",
        "forecast_end": "2026-12-31",
        "note": "Oct–Dec 2026 pipeline data is sparse (expected gap per audit). Supply projections are indicative.",
        "monthly_outlook": monthly_outlook,
    }


# Keep old URL working for backward compat
@app.get("/api/dashboard/supply-demand-forecast")
async def supply_demand_forecast_alias(sow_filter: str = "confirmed"):
    return await get_pipeline_outlook(sow_filter=sow_filter)


# ═════════════════════════════════════════════════════════════════════════════
# DELIVERABLE 3 — Current-State Allocation Report
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/allocations")
async def get_allocations(
    status: Optional[str] = None,
    active_only: bool = True,
):
    where = {}
    if active_only:
        where["is_allocation_active"] = True
    if status:
        where["status"] = status.upper()

    allocations = await db.allocation.find_many(
        where=where,
        include={"employee": True, "project": True},
    )
    return {
        "total": len(allocations),
        "data": allocations,
    }


@app.get("/api/dashboard/utilization")
async def get_utilization(flag: Optional[str] = None):
    """
    Deliverable 3: Per-employee utilisation with OVER/UNDER flags.
    Excludes BAU_OVERHEAD and placeholder date allocations from utilisation maths.
    flag=OVER → only over-utilised | flag=UNDER → under-utilised | None → all
    """
    employees = await db.employee.find_many(
        where={"is_recommended_pool": True},
        include={"allocations": True},
    )

    today = datetime.now(timezone.utc)
    threshold_30d = today + timedelta(days=30)

    result = []
    for emp in employees:
        allocs = emp.allocations or []

        # Active, non-BAU allocations (the real project load)
        active = [
            a for a in allocs
            if a.is_allocation_active
            and a.status not in ("BAU_OVERHEAD",)
            and not a.is_placeholder_date
        ]

        billable_pct = sum(a.percentage for a in active if a.status == "BILLABLE")
        shadow_pct = sum(a.percentage for a in active if a.status in ("SHADOW", "UNBILLED"))
        total_pct = billable_pct + shadow_pct

        util_flag = "OVER" if total_pct > 100 else ("UNDER" if billable_pct < 50 else "OK")

        # Approaching availability: end date within 30 days, non-placeholder
        approaching = [
            a for a in active
            if a.allocated_end_date
            and not _is_placeholder(a.allocated_end_date)
            and today <= a.allocated_end_date <= threshold_30d
        ]

        earliest_available = (
            min(a.allocated_end_date for a in approaching)
            if approaching else None
        )

        row = {
            "employee_id": emp.id,
            "designation": emp.designation,
            "location": emp.location,
            "primary_domain": emp.primary_skill_domain,
            "billable_percentage": billable_pct,
            "shadow_percentage": shadow_pct,
            "total_utilization_pct": total_pct,
            "utilization_flag": util_flag,
            "approaching_availability": len(approaching) > 0,
            "earliest_available_date": earliest_available.date().isoformat() if earliest_available else None,
            "active_projects": len(active),
        }
        result.append(row)

    # Apply flag filter
    if flag:
        result = [r for r in result if r["utilization_flag"] == flag.upper()]

    result.sort(key=lambda x: -x["total_utilization_pct"])

    over_count = sum(1 for r in result if r["utilization_flag"] == "OVER")
    under_count = sum(1 for r in result if r["utilization_flag"] == "UNDER")
    bench_count = sum(1 for r in result if r["total_utilization_pct"] == 0)

    return {
        "summary": {
            "total_employees": len(result),
            "over_utilised": over_count,
            "under_utilised": under_count,
            "on_bench": bench_count,
        },
        "utilization": result,
    }


@app.get("/api/dashboard/leakage")
async def get_financial_leakage():
    """Deliverable 3: Financial leakage from shadow/unbilled resources."""
    allocations = await db.allocation.find_many(
        where={"is_allocation_active": True},
        include={"employee": True},
    )

    shadow_allocs = [a for a in allocations if a.status.upper() in ("SHADOW", "UNBILLED")]

    rate_card = {
        "trainee": 35, "junior": 50, "associate": 60,
        "consultant": 85, "senior": 120, "lead": 140,
        "principal": 160, "architect": 180, "manager": 150,
        "enabler": 95, "director": 200,
    }
    assumed_hours_per_week = 40
    exact_leakage = 0
    unknown_band_count = 0

    for alloc in shadow_allocs:
        role = (alloc.employee.designation or "").lower() if alloc.employee else ""
        rate = next((v for k, v in rate_card.items() if k in role), None)
        effective_hours = assumed_hours_per_week * (alloc.percentage / 100)
        if rate:
            exact_leakage += rate * effective_hours
        else:
            unknown_band_count += 1

    blended_low, blended_high = 60, 130
    min_leakage = exact_leakage + unknown_band_count * blended_low * assumed_hours_per_week
    max_leakage = exact_leakage + unknown_band_count * blended_high * assumed_hours_per_week

    return {
        "shadow_resource_count": len(shadow_allocs),
        "weekly_unbilled_hours": len(shadow_allocs) * assumed_hours_per_week,
        "estimated_weekly_revenue_leakage_usd": (
            f"${min_leakage:,.0f}" if min_leakage == max_leakage
            else f"${min_leakage:,.0f} – ${max_leakage:,.0f}"
        ),
        "calculation_method": "Role-based banded rates with FTE% weighting and confidence intervals for unmapped roles.",
        "action_prompt": f"Redeploying {len(shadow_allocs)} shadow resources recovers up to ${max_leakage:,.0f} weekly.",
    }


@app.get("/api/dashboard/team-health")
async def get_team_health_scores():
    """PM-level composite health leaderboard (60% utilisation, 40% risk-free rate)."""
    projects = await db.project.find_many()
    risk_scores = await db.projectriskscore.find_many()
    allocations = await db.allocation.find_many()

    risk_map = {rs.project_id: rs.is_at_risk for rs in risk_scores}
    alloc_map: dict[str, list[str]] = defaultdict(list)
    for a in allocations:
        if a.project_id:
            alloc_map[a.project_id].append(a.status.upper() if a.status else "UNKNOWN")

    pm_stats: dict = defaultdict(lambda: {
        "total_projects": 0, "risk_projects": 0,
        "total_resources": 0, "shadow_resources": 0,
    })

    for p in projects:
        pm = getattr(p, "project_manager", None) or "Unassigned"
        pm_stats[pm]["total_projects"] += 1
        if risk_map.get(p.id) is True:
            pm_stats[pm]["risk_projects"] += 1
        for status in alloc_map.get(p.id, []):
            pm_stats[pm]["total_resources"] += 1
            if status in ("SHADOW", "UNBILLED", "PRESENCE UNVERIFIED"):
                pm_stats[pm]["shadow_resources"] += 1

    results = []
    for pm, stats in pm_stats.items():
        if stats["total_projects"] == 0 or stats["total_resources"] == 0:
            continue
        risk_rate = stats["risk_projects"] / stats["total_projects"]
        shadow_rate = stats["shadow_resources"] / stats["total_resources"]
        composite = round((1 - shadow_rate) * 60 + (1 - risk_rate) * 40, 1)
        results.append({
            "project_manager": pm,
            "total_projects": stats["total_projects"],
            "high_risk_projects": stats["risk_projects"],
            "total_resources": stats["total_resources"],
            "shadow_resources": stats["shadow_resources"],
            "composite_score": composite,
        })

    results.sort(key=lambda x: -x["composite_score"])
    return {"leaderboard": results}


# ═════════════════════════════════════════════════════════════════════════════
# RESOURCE ALLOCATION — Bulletproof with Redis locking
# ═════════════════════════════════════════════════════════════════════════════

class AllocationRequest(BaseModel):
    employee_id: str
    project_id: str
    percentage: int


@app.post("/api/allocate")
async def allocate_resource(req: AllocationRequest):
    lock_key = f"lock:employee:{req.employee_id}"
    lock_acquired = await redis_client.set(lock_key, "locked", ex=15, nx=True)

    if not lock_acquired:
        raise HTTPException(
            status_code=409,
            detail=f"Resource {req.employee_id} is currently being allocated by another manager.",
        )

    try:
        existing = await db.allocation.find_first(
            where={"employee_id": req.employee_id, "project_id": req.project_id}
        )
        all_allocs = await db.allocation.find_many(where={"employee_id": req.employee_id})
        other_committed = sum(
            a.percentage for a in all_allocs
            if a.status not in ("SHADOW", "BAU_OVERHEAD")
            and a.project_id != req.project_id
        )

        if other_committed + req.percentage > 100:
            raise HTTPException(
                status_code=400,
                detail=f"Allocation failed. Resource committed at {other_committed}% elsewhere. Adding {req.percentage}% exceeds 100%.",
            )

        if existing:
            result = await db.allocation.update(
                where={"id": existing.id},
                data={"percentage": req.percentage, "status": "BILLABLE"},
            )
            msg = "Allocation updated."
        else:
            result = await db.allocation.create(
                data={
                    "employee_id": req.employee_id,
                    "project_id": req.project_id,
                    "percentage": req.percentage,
                    "status": "BILLABLE",
                    "is_allocation_active": True,
                }
            )
            msg = "Resource allocated successfully."

        return {"status": "SUCCESS", "message": msg, "data": result}

    finally:
        await redis_client.delete(lock_key)


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    vector_count = 0
    try:
        vector_count = collection.count()
    except Exception:
        pass

    ml_status = "loaded" if health_model else "not loaded — run train_lgbm.py"

    return {
        "status": "ok",
        "vector_store_profiles": vector_count,
        "ml_model": ml_status,
        "model_features": MODEL_FEATURES,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
