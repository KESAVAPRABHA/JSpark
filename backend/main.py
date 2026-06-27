from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prisma import Prisma
import joblib
import pandas as pd
import shap
from contextlib import asynccontextmanager
import numpy as np
import redis.asyncio as redis
from ai_engine import recommend_resource
import difflib
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from collections import defaultdict


redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True, protocol=2)

# --- ML Initialization ---
try:
    health_model = joblib.load('lgbm_project_health.pkl')
    # Initialize SHAP explainer for Root-Cause Analysis (Feature 3)
    explainer = shap.TreeExplainer(health_model)
except Exception as e:
    print(f"Warning: ML model not found. Error: {e}")

db = Prisma()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()

app = FastAPI(title="Resourcing CoLab API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =================================================================
# FEATURE 2: Strategic Hiring Aggregator & Use Case 1a
# =================================================================
class RecommendationRequest(BaseModel):
    requirements: str
    role: str

@app.post("/api/recommend")
async def get_recommendation(req: RecommendationRequest):
    req_clean = req.requirements.strip() if req.requirements else ""
    role_clean = req.role.strip() if req.role else ""

    # 🚨 FIX #7 (Part 1): Upfront Validation Gate
    # Prevent garbage queries from burning GenAI compute or polluting the DB
    if not role_clean or len(req_clean) < 10:
        raise HTTPException(
            status_code=400, 
            detail="Malformed request: Role cannot be empty and requirements must be > 10 characters."
        )

    try:
        result = recommend_resource(req_clean, role_clean)
        
        # 🚨 FIX #7 (Part 2): Strategic Hiring Aggregator with Fuzzy Deduplication
        if result["status"] == "NO_MATCH_FOUND":
            
            # Fetch existing gaps for this specific role
            existing_gaps = await db.skillgap.find_many(where={"role": role_clean})
            is_duplicate = False
            
            for gap in existing_gaps:
                # Calculate semantic similarity between the strings
                similarity = difflib.SequenceMatcher(None, req_clean.lower(), gap.requirements.lower()).ratio()
                
                if similarity > 0.80: # 80% threshold for deduplication
                    is_duplicate = True
                    print(f"🛡️ Blocked duplicate SkillGap logging (Similarity: {similarity:.2f})")
                    break
            
            if not is_duplicate:
                await db.skillgap.create(
                    data={
                        "role": role_clean,
                        "requirements": req_clean
                    }
                )
                print(f"✅ Logged new legitimate Skill Gap: {req_clean}")
                
        # Existing logic for Flaw 5 (Immutable AI Audit Trail)
        elif result["status"] == "MATCH_FOUND":
            await db.airecommendationlog.create(
                data={
                    "employee_id": result["employee_id"],
                    "role_requested": role_clean,
                    "requirements": req_clean,
                    "cosine_distance": result["cosine_distance"],
                    "rationale_text": result["rationale"]
                }
            )
            
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/dashboard/audit-log")
async def get_ai_audit_log():
    """Endpoint for Auditors to review past AI decisions."""
    logs = await db.airecommendationlog.find_many(
        order={"generated_at": "desc"}, 
        take=10
    )
    return {"audit_trail": logs} 
   
@app.get("/api/dashboard/skill-gaps")
async def get_skill_gaps():
    """Endpoint for HR to see what skills are blocking revenue."""
    gaps = await db.skillgap.find_many(order={"logged_at": "desc"}, take=10)
    return {"recent_skill_gaps": gaps}


# =================================================================
# FEATURE 3: SHAP Root-Cause Explainer & Use Case 1b
# =================================================================
class HealthRiskRequest(BaseModel):
    quality_status: str
    csat_status: str
    team_status: str

@app.post("/api/predict-risk")
async def predict_project_risk(req: HealthRiskRequest):
    status_map = {'NO_COLOR': 0, 'GREEN': 1, 'AMBER': 2, 'RED': 3}
    
    input_df = pd.DataFrame([{
        'quality_status': status_map.get(req.quality_status.upper(), 0),
        'csat_status': status_map.get(req.csat_status.upper(), 0),
        'team_status': status_map.get(req.team_status.upper(), 0)
    }])
    
    risk_prob = health_model.predict_proba(input_df)[0][1]
    
    # Read the optimal threshold generated during training
    try:
        with open('optimal_threshold.txt', 'r') as f:
            BASE_THRESHOLD = float(f.read().strip())
    except:
        BASE_THRESHOLD = 0.5 # Fallback    
        
    # FEATURE 3 LOGIC: SHAP Root-Cause Extraction
    shap_values = explainer.shap_values(input_df)
    # LightGBM binary classification usually returns a list; we want the positive class (index 1)
    target_shap = shap_values[1][0] if isinstance(shap_values, list) else shap_values[0]
    
    # Find the feature that contributed the most to the risk
    feature_names = input_df.columns
    max_feature_idx = np.argmax(target_shap)
    root_cause_feature = feature_names[max_feature_idx].replace('_', ' ').title()
    
    risk_tier = "LOW"
    action = "On Track"
    root_cause_msg = "No significant risk drivers detected."
    
    # Dynamic tiering based on the mathematically optimal threshold
    if risk_prob >= (BASE_THRESHOLD * 1.5): # e.g., significantly higher than threshold
        risk_tier = "HIGH"
        action = "Immediate Review Required: Potential Escalation"
        root_cause_msg = f"Primary Driver: Degradation in {root_cause_feature}"
    elif risk_prob >= BASE_THRESHOLD:
        risk_tier = "MEDIUM"
        action = "Monitor Closely: Velocity Drift Detected"
        root_cause_msg = f"Primary Driver: Instability in {root_cause_feature}"     
           
    return {
        "risk_probability": round(float(risk_prob), 2),
        "risk_tier": risk_tier,
        "recommended_action": action,
        "root_cause_explainer": root_cause_msg # The SHAP output
    }

# =================================================================
# FEATURE 1: Financial Leakage Quantifier & Use Case 3
# =================================================================
@app.get("/api/allocations")
async def get_allocations():
    allocations = await db.allocation.find_many(
        include={'employee': True, 'project': True}
    )
    return {"data": allocations}
@app.get("/api/dashboard/leakage")
async def get_financial_leakage():
    # Include employee data to access their designation (role)
    allocations = await db.allocation.find_many(
        include={'employee': True}
    )
    
    shadow_allocations = [a for a in allocations if a.status.upper() in ['SHADOW', 'UNBILLED']]
    shadow_count = len(shadow_allocations)
    
    # Banded hourly rates (USD) mapping based on typical designations
    rate_card = {
        "junior": 50,
        "associate": 60,
        "consultant": 85,
        "senior": 120,
        "lead": 140,
        "principal": 160,
        "architect": 180,
        "manager": 150
    }
    
    assumed_hours_per_week = 40
    exact_leakage = 0
    unknown_band_count = 0
    
    for alloc in shadow_allocations:
        role = alloc.employee.designation.lower() if alloc.employee and alloc.employee.designation else ""
        
        # Find matching band, default to None if not found
        rate = next((v for k, v in rate_card.items() if k in role), None)
        
        if rate:
            exact_leakage += (rate * assumed_hours_per_week)
        else:
            unknown_band_count += 1
            
    # Apply a confidence interval (range) for roles missing from the rate_card
    blended_low = 60
    blended_high = 130
    
    min_leakage = exact_leakage + (unknown_band_count * blended_low * assumed_hours_per_week)
    max_leakage = exact_leakage + (unknown_band_count * blended_high * assumed_hours_per_week)
    
    # Format the output range
    if min_leakage == max_leakage:
        leakage_display = f"${min_leakage:,.0f}"
    else:
        leakage_display = f"${min_leakage:,.0f} - ${max_leakage:,.0f}"

    return {
        "shadow_resource_count": shadow_count,
        "weekly_unbilled_hours": shadow_count * assumed_hours_per_week,
        "estimated_weekly_revenue_leakage_usd": leakage_display,
        "calculation_method": "Role-based banded rates with confidence intervals for unmapped roles.",
        "action_prompt": f"Redeploying {shadow_count} shadow resources recovers {leakage_display} weekly."
    }
    
 
 
@app.get("/api/risk-scores")
async def get_risk_scores(project_id: str = None):
    if project_id:
        score = await db.projectriskscore.find_unique(
            where={"project_id": project_id}
        )
        if not score:
            raise HTTPException(status_code=404, detail="Project risk score not found.")
        return score
    else:
        scores = await db.projectriskscore.find_many(
            order={"risk_probability": "desc"}
        )
        return {"active_risk_assessments": scores} 
    
# =================================================================
# FEATURE: Bulletproof Resource Allocation (Fixing Flaw #2)
# =================================================================
class AllocationRequest(BaseModel):
    employee_id: str
    project_id: str
    percentage: int

@app.post("/api/allocate")
async def allocate_resource(req: AllocationRequest):
    lock_key = f"lock:employee:{req.employee_id}"
    
    # 1. ATTEMPT ACQUIRE LOCK (15-second TTL)
    lock_acquired = await redis_client.set(lock_key, "locked_by_rm", ex=15, nx=True)
    
    if not lock_acquired:
        raise HTTPException(
            status_code=409, 
            detail=f"Resource {req.employee_id} is currently being allocated by another manager."
        )
        
    try:
        # 2. CHECK EXISTING ALLOCATION TO THIS SPECIFIC PROJECT
        # If they are already on this project, we are just updating their hours, not adding a new project.
        existing_project_alloc = await db.allocation.find_first(
            where={
                "employee_id": req.employee_id,
                "project_id": req.project_id
            }
        )
        
        # 3. VERIFY GLOBAL CAPACITY
        current_allocations = await db.allocation.find_many(where={"employee_id": req.employee_id})
        
        # Calculate total capacity, IGNORING the current project (since we are about to overwrite it)
        total_other_percent = sum(
            a.percentage for a in current_allocations 
            if a.status != 'SHADOW' and a.project_id != req.project_id
        )
        
        if total_other_percent + req.percentage > 100:
             raise HTTPException(
                status_code=400, 
                detail=f"Allocation failed. Resource is committed to other projects at {total_other_percent}%. Adding {req.percentage}% exceeds 100% capacity."
            )

        # 4. EXECUTE DATABASE UPSERT (Update if exists, Create if new)
        if existing_project_alloc:
            # Update existing record
            result_allocation = await db.allocation.update(
                where={"id": existing_project_alloc.id},
                data={
                    "percentage": req.percentage,
                    "status": "BILLABLE"
                }
            )
            action_msg = "Resource allocation updated successfully."
        else:
            # Create new record
            result_allocation = await db.allocation.create(
                data={
                    "employee_id": req.employee_id,
                    "project_id": req.project_id,
                    "percentage": req.percentage,
                    "status": "BILLABLE"
                }
            )
            action_msg = "Resource successfully allocated."
            
        return {"status": "SUCCESS", "message": action_msg, "data": result_allocation}
        
    finally:
        # GUARANTEED RELEASE
        await redis_client.delete(lock_key)
        
        
@app.get("/api/dashboard/supply-demand-forecast")
async def get_supply_demand_forecast():
    now = datetime.utcnow()
    intervals = [4, 8, 12]
    
    # 1. Fetch relevant core datasets from Prisma
    # SOW=True indicates guaranteed upcoming demand pipeline
    upcoming_projects = await db.project.find_many(
        where={
            "sow_status": True,
            "start_date": {"gt": now}
        }
    )
    
    # Active allocations let us compute when engineers drop off onto the bench
    active_allocations = await db.allocation.find_many(
        where={"status": "ALLOCATED"},
        include={"employee": True}
    )
    
    # Unique core skill domains across our workforce roster
    employees = await db.employee.find_many()
    skill_categories = list(set([e.primary_skill_domain for e in employees if e.primary_skill_domain]))
    
    forecast_data = []

    for skill in skill_categories:
        # Initial supply is total workforce in this domain
        total_workforce = sum(1 for e in employees if e.primary_skill_domain == skill)
        
        timeline_metrics = {}
        
        for weeks in intervals:
            target_date = now + timedelta(weeks=weeks)
            
            # Supply Calculation: Engineers whose allocation ends BEFORE target_date are on the bench (available)
            # Plus anyone currently unallocated or rolling off
            available_supply = 0
            for alloc in active_allocations:
                if alloc.employee and alloc.employee.primary_skill_domain == skill:
                    if alloc.end_date and datetime.fromisoformat(str(alloc.end_date)) <= target_date:
                        available_supply += 1
                        
            # Add base unallocated pool (workforce minus currently locked individuals)
            locked_count = sum(1 for alloc in active_allocations if alloc.employee and alloc.employee.primary_skill_domain == skill and (alloc.end_date is None or datetime.fromisoformat(str(alloc.end_date)) > target_date))
            available_supply += max(0, total_workforce - locked_count)

            # Demand Calculation: Upcoming pipeline requiring this domain starting before/during target_date
            upcoming_demand = sum(
                1 for p in upcoming_projects 
                if p.required_primary_domain == skill and datetime.fromisoformat(str(p.start_date)) <= target_date
            )
            
            timeline_metrics[f"week_{weeks}_supply"] = available_supply
            timeline_metrics[f"week_{weeks}_demand"] = upcoming_demand
            
        forecast_data.append({
            "skill_category": skill,
            "metrics": timeline_metrics
        })

    return {"forecast": forecast_data}


@app.get("/api/dashboard/team-health")
async def get_team_health_scores():
    # Fetch all relevant datasets
    projects = await db.project.find_many()
    risk_scores = await db.projectriskscore.find_many()
    allocations = await db.allocation.find_many()
    
    # Create fast lookup maps
    risk_map = {rs.project_id: rs.is_at_risk for rs in risk_scores}
    alloc_map = defaultdict(list)
    for a in allocations:
        # Map allocation status to its project
        if a.project_id:
            alloc_map[a.project_id].append(a.status.upper() if a.status else "UNKNOWN")

    pm_stats = defaultdict(lambda: {
        "total_projects": 0, 
        "risk_projects": 0, 
        "total_resources": 0, 
        "shadow_resources": 0
    })

    for p in projects:
        # Default to "Unassigned" if project_manager field is missing or null
        pm = getattr(p, 'project_manager', None) or "Unassigned"
        
        pm_stats[pm]["total_projects"] += 1
        
        # Check high-risk status
        if risk_map.get(p.project_id) is True:
            pm_stats[pm]["risk_projects"] += 1
            
        # Tally resource utilization
        project_allocs = alloc_map.get(p.project_id, [])
        for status in project_allocs:
            pm_stats[pm]["total_resources"] += 1
            if status in ['SHADOW', 'UNBILLED', 'PRESENCE UNVERIFIED']:
                pm_stats[pm]["shadow_resources"] += 1

    results = []
    for pm, stats in pm_stats.items():
        if stats["total_projects"] == 0 or stats["total_resources"] == 0:
            continue
            
        # Calculate Rates
        risk_rate = stats["risk_projects"] / stats["total_projects"]
        shadow_rate = stats["shadow_resources"] / stats["total_resources"]
        
        utilization_rate = 1 - shadow_rate
        health_rate = 1 - risk_rate
        
        # Composite Score: 60% Utilization weight, 40% Risk weight
        composite_score = (utilization_rate * 60) + (health_rate * 40)
        
        results.append({
            "project_manager": pm,
            "total_projects": stats["total_projects"],
            "high_risk_projects": stats["risk_projects"],
            "total_resources": stats["total_resources"],
            "shadow_resources": stats["shadow_resources"],
            "composite_score": round(composite_score, 1)
        })

    # Sort by Composite Score (Descending - Best PMs first)
    results.sort(key=lambda x: x["composite_score"], reverse=True)
    return {"leaderboard": results}