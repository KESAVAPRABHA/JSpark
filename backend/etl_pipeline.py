"""
etl_pipeline.py — JSpark v2 Full Ingestion Pipeline (FIXED)

ROOT CAUSE OF 0 PROJECTS/ALLOCATIONS/SKILLS:
  ✅ FIX 1 (CRITICAL): safe_date() now returns Python datetime objects, not ISO strings.
     Prisma Python client requires datetime objects for DateTime fields.
     Passing a string like '2024-03-08T00:00:00' caused a silent type error caught by except:pass.
     This is why 374 employees ingested fine (no DateTime fields) but 0 projects/allocations/skills did.

Additional column name mismatches fixed:
  ✅ FIX 2: Project 'project_manager' → uses 'reporter_id' (actual column in CSV)
  ✅ FIX 3: Allocation 'resourcing_type' → removed (column doesn't exist); 'resourcing_status' is used for status
  ✅ FIX 4: Allocation 'is_bau_overhead' → removed (column doesn't exist); BAU detected via project type_of_project
  ✅ FIX 5: Pipeline col_map corrected — 'resources_requested', 'likely_start_date', 'number_of_weeks' are actual names
  ✅ FIX 6: Pipeline % column handles non-int values like '75/100' and '25-50'
  ✅ FIX 7: Competency Excel column stripping — 'Score ', 'Score .1' trailing spaces handled
  ✅ FIX 8: WeeklyStatus week_start_date now passes datetime object not isoformat string
  ✅ FIX 9: CLEANED_DIR auto-detects '../data/cleaned' if env var not set but directory exists
  ✅ FIX 10: Silent except:pass replaced with logged warnings (stderr) so failures are visible
"""

import pandas as pd
import asyncio
import os
import sys
from datetime import datetime
from prisma import Prisma

# ─────────────────────────────────────────────────────────────────────────────
# P0-3: ROLE NORMALISATION — map raw pipeline role codes → canonical designations
# Ensures pipeline demand groups match Employee.designation values for supply matching
# ─────────────────────────────────────────────────────────────────────────────
ROLE_NORMALISATION = {
    "sse":               "Senior Software Engineer",
    "ssea":              "Senior Software Engineer",
    "se":                "Software Engineer",
    "tse":               "Trainee Software Engineer",
    "p":                 "Principal",
    "sc":                "Solution Consultant",
    "sac":               "Associate Consultant",
    "ac":                "Associate Consultant",
    "sa":                "Solution Architect",
    "solutionsenablement": "Solution Enabler",
    "enabler":           "Solution Enabler",
    "architect":         "Solution Architect",
    "consultant":        "Solution Consultant",
    "data":              "Data Scientist",   # 'data scientist' → first word 'data'
    "analyst":           "Data Analyst",
}


def normalise_role(raw: str) -> str:
    """Normalise raw pipeline role codes to canonical designation strings."""
    if not raw:
        return "Unknown"
    # Try full lower-stripped match first (e.g. 'data scientist')
    full_key = raw.strip().lower().replace("/", " ").strip()
    if full_key in ROLE_NORMALISATION:
        return ROLE_NORMALISATION[full_key]
    # Special cases: 'AC/SAC' → Associate Consultant, 'SSE or SE' → Senior Software Engineer
    if "sse" in full_key:
        return "Senior Software Engineer"
    if full_key.startswith("ac") or full_key.startswith("sac"):
        return "Associate Consultant"
    if "data scientist" in full_key:
        return "Data Scientist"
    if "data analyst" in full_key:
        return "Data Analyst"
    # Fall back to first word match
    first_word = full_key.split()[0] if full_key.split() else ""
    return ROLE_NORMALISATION.get(first_word, raw.strip())

DATA_DIR = os.environ.get("DATA_DIR", "../data")
# Auto-detect cleaned dir: env var takes priority, else check default path
_default_cleaned = os.path.join(DATA_DIR, "cleaned")
CLEANED_DIR = os.environ.get("CLEANED_DIR", _default_cleaned if os.path.isdir(_default_cleaned) else None)

if CLEANED_DIR:
    print(f"CLEANED_DIR: {CLEANED_DIR}")

# ─────────────────────────────────────────────────────────────────────────────
# SENTINEL PLACEHOLDER DATES — treat as "unknown end date", not real roll-off
# ─────────────────────────────────────────────────────────────────────────────
PLACEHOLDER_YEARS = {2030, 2035}


def is_placeholder(dt) -> bool:
    if pd.isnull(dt):
        return False
    try:
        return pd.to_datetime(dt, dayfirst=True, errors="coerce").year in PLACEHOLDER_YEARS
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SAFE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def safe_date(val):
    """
    Parse any date-like value to a Python datetime object.
    CRITICAL FIX: Must return datetime object, NOT a string.
    Prisma Python client requires datetime objects for DateTime fields.
    Passing a string silently fails with a type error caught by except:pass.
    """
    if pd.isnull(val):
        return None
    try:
        dt = pd.to_datetime(val, dayfirst=True, format="mixed", errors="coerce")
        if pd.isnull(dt):
            return None
        return dt.to_pydatetime()  # ← datetime object, not .isoformat() string
    except Exception:
        return None


def safe_str(val, default=None):
    if pd.isnull(val):
        return default
    s = str(val).strip()
    return s if s else default


def safe_int(val, default=0):
    if val is None or (isinstance(val, float) and pd.isnull(val)):
        return default
    try:
        # Handle values like '75/100' or '25-50' — take the first number
        s = str(val).strip()
        if "/" in s:
            s = s.split("/")[0]
        elif "-" in s and not s.startswith("-"):
            s = s.split("-")[0]
        return int(float(s))
    except (TypeError, ValueError):
        return default


def safe_float(val, default=0.0):
    try:
        v = float(val)
        return default if pd.isnull(v) else round(float(v), 4)
    except (TypeError, ValueError):
        return default


def _log_warning(msg: str):
    """Print warning to stderr so it's visible but doesn't clutter stdout."""
    print(f"  ⚠️  {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# FILE LOADERS — prefer cleaned files if they exist
# ─────────────────────────────────────────────────────────────────────────────

def _load(name: str, fallback_name: str = None, **kwargs) -> pd.DataFrame:
    """Load from cleaned dir if available, else raw data dir."""
    if CLEANED_DIR:
        clean_path = os.path.join(CLEANED_DIR, name)
        if os.path.exists(clean_path):
            print(f"  ℹ️  Using cleaned file: {clean_path}")
            return pd.read_csv(clean_path, encoding="latin1", **kwargs)
    raw_path = os.path.join(DATA_DIR, fallback_name or name)
    print(f"  ℹ️  Using raw file: {raw_path}")
    return pd.read_csv(raw_path, encoding="latin1", **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# CLEAN & PREPARE
# ─────────────────────────────────────────────────────────────────────────────

def clean_and_prepare_data():
    print("📦 Loading and cleaning all data files…")

    # ── 01 EMPLOYEES ───────────────────────────────────────────────────────
    df_emp = _load("01_employees_clean.csv", "01_260624_employee_details.csv")
    df_emp = df_emp.drop(columns=["is_active_version", "project_key"], errors="ignore")
    df_emp = df_emp.dropna(subset=["employee_id"])
    df_emp["department_name"] = df_emp["department_name"].fillna("Delivery")
    df_emp["job_name"] = df_emp["job_name"].fillna("Unassigned")
    # Filter to Delivery only (per problem statement scope)
    df_emp = df_emp[df_emp["department_name"] == "Delivery"].copy()
    # Mark employees who have resigned as NOT in recommended pool
    df_emp["has_resigned"] = df_emp["date_of_resignation"].notna() & (df_emp["date_of_resignation"] != "")
    df_emp["is_recommended_pool"] = ~df_emp["has_resigned"]
    print(f"  ✓ Employees: {len(df_emp)} rows | {df_emp['is_recommended_pool'].sum()} eligible for recommendations")

    # ── 02 PROJECTS ────────────────────────────────────────────────────────
    df_proj = _load("02_projects_clean.csv", "02_260624_project_details.csv")
    df_proj = df_proj.drop(columns=["is_active_version", "project_key"], errors="ignore")
    df_proj = df_proj.dropna(subset=["project_id"])
    # FIX 2: reporter_id is the proxy for project_manager (no project_manager column exists)
    if "project_manager" not in df_proj.columns and "reporter_id" in df_proj.columns:
        df_proj["project_manager"] = df_proj["reporter_id"]
    print(f"  ✓ Projects: {len(df_proj)} rows")

    # ── 03 ALLOCATIONS ─────────────────────────────────────────────────────
    df_alloc = _load("03_allocations_clean.csv", "03_260623_Project_Allocation_Details.csv")
    df_alloc = df_alloc.drop(columns=["is_active_version"], errors="ignore")
    df_alloc = df_alloc.dropna(subset=["project_id"])
    df_alloc["employee_id"] = df_alloc["employee_id"].fillna("OPEN_REQ")
    df_alloc["allocation_by_percentage"] = pd.to_numeric(
        df_alloc["allocation_by_percentage"], errors="coerce"
    ).fillna(0).astype(int)
    # Flag placeholder end dates
    df_alloc["is_placeholder_date"] = df_alloc["allocated_end_date"].apply(is_placeholder)
    # FIX 4: No 'is_bau_overhead' column — detect BAU via project join (done at ingest time)
    # FIX 3: No 'resourcing_type' column — 'resourcing_status' is the correct column name
    print(f"  ✓ Allocations: {len(df_alloc)} rows | {df_alloc['is_placeholder_date'].sum()} placeholder end dates")

    # ── 05 SKILLS ──────────────────────────────────────────────────────────
    df_skills = _load("05_skills_clean.csv", "05_260624_Skill_Data.csv")
    # Handle both raw Excel headers (with 'COE Skill') and cleaned CSV
    df_skills.columns = df_skills.columns.str.strip()
    df_skills["Score"] = pd.to_numeric(df_skills["Score"], errors="coerce").fillna(0).astype(int)
    # Fill blank Skill from SubSkill
    if "Skill" in df_skills.columns and "SubSkill" in df_skills.columns:
        df_skills["Skill"] = df_skills["Skill"].fillna(df_skills["SubSkill"])
    # Normalise COE names (case variants in raw data)
    if "COE" in df_skills.columns:
        df_skills["COE"] = df_skills["COE"].str.strip().str.title().fillna("Unknown")
    print(f"  ✓ Skills: {len(df_skills)} rows | {df_skills['employee_id'].nunique()} unique employees")

    # ── 06 COMPETENCY (NEW) ────────────────────────────────────────────────
    clean_comp = os.path.join(CLEANED_DIR or "", "06_competency_clean.csv")
    raw_comp_csv = os.path.join(DATA_DIR, "06_260623_Competency_Details.csv")
    raw_comp_xlsx = os.path.join(DATA_DIR, "06_260623_Competency_Details.xlsx")

    if CLEANED_DIR and os.path.exists(clean_comp):
        df_comp = pd.read_csv(clean_comp, encoding="latin1")
        print(f"  ✓ Competency (cleaned long-format): {len(df_comp)} rows")
    elif os.path.exists(raw_comp_csv):
        df_comp = pd.read_csv(raw_comp_csv, encoding="latin1")
        print(f"  ✓ Competency (raw CSV): {len(df_comp)} rows")
    elif os.path.exists(raw_comp_xlsx):
        # FIX 7: Strip column names (trailing spaces in 'Score ', 'Score .1' etc.)
        xl = pd.ExcelFile(raw_comp_xlsx)
        frames = []
        for sheet in xl.sheet_names:
            tmp = xl.parse(sheet)
            # Strip ALL column names (handles 'Score ', 'Score .1', 'Score .2' etc.)
            tmp.columns = tmp.columns.str.strip()
            # Rename 'Score.N' variants to just 'Score_N' for consistent handling
            score_cols = [c for c in tmp.columns if c.lower().startswith("score")]
            emp_col = "Employee ID" if "Employee ID" in tmp.columns else tmp.columns[0]
            desig_col = "Designation" if "Designation" in tmp.columns else None
            coe_col = "COE/Dep" if "COE/Dep" in tmp.columns else None

            # Get dimension columns (non-Score, non-meta columns)
            meta_cols = [emp_col] + ([desig_col] if desig_col else []) + ([coe_col] if coe_col else [])
            dim_cols = [c for c in tmp.columns if c not in meta_cols and not c.lower().startswith("score")]

            if not dim_cols or not score_cols:
                continue

            # Pair each dimension column with its corresponding Score column
            for i, (dim, score) in enumerate(zip(dim_cols, score_cols)):
                sub = tmp[[emp_col, dim, score]].copy()
                sub.columns = ["employee_id", "dimension", "score"]
                sub["role_track"] = sheet.strip()
                sub["score"] = pd.to_numeric(sub["score"], errors="coerce").fillna(0)
                frames.append(sub)

        df_comp = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        print(f"  ✓ Competency (multi-sheet xlsx → long): {len(df_comp)} rows")
    else:
        print("  ⚠️  Competency file not found — skipping (will impact recommendation quality)")
        df_comp = pd.DataFrame(columns=["employee_id", "role_track", "dimension", "score"])

    # ── 07 PIPELINE (NEW) ─────────────────────────────────────────────────
    df_pipe = _load("07_pipeline_clean.csv", "07_260624_Pipeline_Details.csv")
    # Normalise column names to snake_case
    df_pipe.columns = df_pipe.columns.str.strip().str.lower().str.replace(r"[\s\n]+", "_", regex=True)
    # FIX 5: Correct column name mappings based on actual Pipeline file columns
    # Actual columns after normalisation: 'resources_requested', 'likely_start_date',
    # 'number_of_weeks', 'sow_signed', 'skillset', 'cluster', 'deal_stage_(hubspot)'
    if "sow_signed" in df_pipe.columns:
        df_pipe["sow_signed"] = df_pipe["sow_signed"].astype(str).str.strip().str.upper().isin(
            ["YES", "Y", "TRUE", "1"]
        )
    else:
        df_pipe["sow_signed"] = False

    sow_count = int(df_pipe["sow_signed"].sum()) if "sow_signed" in df_pipe.columns else 0
    print(f"  ✓ Pipeline: {len(df_pipe)} rows | {sow_count} SOW=Yes")

    # ── 09 WSR ────────────────────────────────────────────────────────────
    wsr_candidates = []
    if CLEANED_DIR:
        wsr_candidates.append(os.path.join(CLEANED_DIR, "09_wsr_clean.csv"))
    wsr_candidates += [
        os.path.join(DATA_DIR, "09_260624_Project_Weekly_Status_Details.csv"),
        os.path.join(DATA_DIR, "09. 260624_Project_Weekly_Status_Details.csv"),  # space in original filename
    ]
    df_wsr = None
    for p in wsr_candidates:
        if os.path.exists(p):
            df_wsr = pd.read_csv(p, encoding="latin1")
            print(f"  ✓ WSR: {len(df_wsr)} rows from {p}")
            break
    if df_wsr is None:
        print("  ⚠️  WSR file not found — project health scores will be empty")
        df_wsr = pd.DataFrame()

    # Fix CLIENT_661 dash→underscore in project_id
    if df_wsr is not None and "project_id_masked" in df_wsr.columns:
        df_wsr["project_id_masked"] = df_wsr["project_id_masked"].astype(str).str.replace(
            r"CLIENT_661-", "CLIENT_661_", regex=True
        )

    return df_emp, df_proj, df_alloc, df_skills, df_comp, df_pipe, df_wsr


# ─────────────────────────────────────────────────────────────────────────────
# DERIVE primary_skill_domain per employee from their skills
# ─────────────────────────────────────────────────────────────────────────────

def derive_primary_domains(df_skills: pd.DataFrame) -> dict:
    """Return {employee_id: top_COE_domain} based on average skill score."""
    if df_skills.empty or "COE" not in df_skills.columns:
        return {}
    g = (
        df_skills.groupby(["employee_id", "COE"])["Score"]
        .mean()
        .reset_index()
    )
    idx = g.groupby("employee_id")["Score"].idxmax()
    top = g.loc[idx].set_index("employee_id")["COE"]
    return top.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# INGEST
# ─────────────────────────────────────────────────────────────────────────────

async def ingest_data():
    db = Prisma()
    await db.connect()

    print("\n🧹 Wiping existing data for clean ingestion (order matters for FK constraints)…")
    await db.weeklystatus.delete_many()
    await db.projectriskscore.delete_many()
    await db.airecommendationlog.delete_many()
    await db.skillgap.delete_many()
    await db.pipelinerequest.delete_many()
    await db.competency.delete_many()
    await db.skill.delete_many()
    await db.allocation.delete_many()
    await db.project.delete_many()
    await db.employee.delete_many()

    df_emp, df_proj, df_alloc, df_skills, df_comp, df_pipe, df_wsr = clean_and_prepare_data()

    primary_domain_map = derive_primary_domains(df_skills)

    # ── EMPLOYEES ──────────────────────────────────────────────────────────
    print("\n👤 Ingesting Employees…")
    emp_ids_ingested = set()
    emp_errors = 0
    for _, row in df_emp.iterrows():
        eid = safe_str(row.get("employee_id"))
        if not eid:
            continue
        try:
            await db.employee.upsert(
                where={"id": eid},
                data={
                    "create": {
                        "id": eid,
                        "location": safe_str(row.get("location")),
                        "designation": safe_str(row.get("job_name"), "Unassigned"),
                        "department": safe_str(row.get("department_name"), "Delivery"),
                        # FIX 1: safe_date now returns datetime objects
                        "date_of_join": safe_date(row.get("date_of_join")),
                        "date_of_resignation": safe_date(row.get("date_of_resignation")),
                        "account_status": safe_str(row.get("account_status")),
                        "is_recommended_pool": bool(row.get("is_recommended_pool", True)),
                        "primary_skill_domain": primary_domain_map.get(eid),
                    },
                    "update": {
                        "designation": safe_str(row.get("job_name"), "Unassigned"),
                        "is_recommended_pool": bool(row.get("is_recommended_pool", True)),
                        "date_of_resignation": safe_date(row.get("date_of_resignation")),
                        "primary_skill_domain": primary_domain_map.get(eid),
                    },
                },
            )
            emp_ids_ingested.add(eid)
        except Exception as e:
            emp_errors += 1
            if emp_errors <= 3:
                _log_warning(f"Employee {eid} failed: {e}")
    print(f"  ✓ {len(emp_ids_ingested)} employees ingested ({emp_errors} errors)")

    # ── PROJECTS ───────────────────────────────────────────────────────────
    print("\n📁 Ingesting Projects…")
    proj_ids_ingested = set()
    proj_errors = 0
    for _, row in df_proj.iterrows():
        pid = safe_str(row.get("project_id"))
        if not pid:
            continue
        try:
            await db.project.upsert(
                where={"id": pid},
                data={
                    "create": {
                        "id": pid,
                        "status": safe_str(row.get("project_status")),
                        "tech_coe": safe_str(row.get("tech_coe")),
                        # FIX 1: safe_date returns datetime objects now
                        "project_start_date": safe_date(row.get("project_start_date")),
                        "project_end_date": safe_date(row.get("project_end_date")),
                        "type_of_project": safe_str(row.get("type_of_project")),
                        "client_id": safe_str(row.get("CLIENT_ID") or row.get("client_id")),
                        # FIX 2: Use reporter_id as project_manager proxy
                        "project_manager": safe_str(row.get("project_manager") or row.get("reporter_id")),
                    },
                    "update": {
                        "status": safe_str(row.get("project_status")),
                        "project_end_date": safe_date(row.get("project_end_date")),
                        "project_start_date": safe_date(row.get("project_start_date")),
                        "type_of_project": safe_str(row.get("type_of_project")),
                        "project_manager": safe_str(row.get("project_manager") or row.get("reporter_id")),
                    },
                },
            )
            proj_ids_ingested.add(pid)
        except Exception as e:
            proj_errors += 1
            if proj_errors <= 3:
                _log_warning(f"Project {pid} failed: {e}")
    print(f"  ✓ {len(proj_ids_ingested)} projects ingested ({proj_errors} errors)")

    # ── ALLOCATIONS ────────────────────────────────────────────────────────
    print("\n🔗 Ingesting Allocations…")
    alloc_count = 0
    alloc_skipped_fk = 0
    alloc_errors = 0
    for _, row in df_alloc.iterrows():
        eid = safe_str(row.get("employee_id"))
        pid = safe_str(row.get("project_id"))
        # Skip OPEN_REQ rows (no employee to link)
        if eid in (None, "OPEN_REQ", "OPEN_REQUISITION") or not pid:
            continue
        # FIX: Guard FK constraints — skip if employee/project not ingested
        if eid not in emp_ids_ingested:
            alloc_skipped_fk += 1
            continue
        if pid not in proj_ids_ingested:
            alloc_skipped_fk += 1
            continue
        try:
            # FIX 3: resourcing_status is the correct column name (not resourcing_type)
            status = safe_str(row.get("resourcing_status"), "UNKNOWN")
            is_active = bool(int(row.get("is_allocation_active", 1)) == 1)
            is_ph = bool(row.get("is_placeholder_date", False))

            await db.allocation.create(
                data={
                    "employee_id": eid,
                    "project_id": pid,
                    "status": status,
                    # FIX 1: safe_date returns datetime objects
                    "allocated_start_date": safe_date(row.get("allocated_start_date")),
                    "allocated_end_date": safe_date(row.get("allocated_end_date")),
                    "is_allocation_active": is_active,
                    "is_placeholder_date": is_ph,
                    "percentage": safe_int(row.get("allocation_by_percentage"), 0),
                    # FIX 3: resourcing_type removed (column doesn't exist); store status here
                    "resourcing_type": status,
                }
            )
            alloc_count += 1
        except Exception as e:
            alloc_errors += 1
            if alloc_errors <= 3:
                _log_warning(f"Allocation {eid}/{pid} failed: {e}")

    print(f"  ✓ {alloc_count} allocations ingested | {alloc_skipped_fk} skipped (FK miss) | {alloc_errors} errors")

    # ── SKILLS ─────────────────────────────────────────────────────────────
    print("\n🎯 Ingesting Skills…")
    skill_count = 0
    skill_errors = 0
    for _, row in df_skills.iterrows():
        eid = safe_str(row.get("employee_id"))
        if not eid or eid not in emp_ids_ingested:
            continue
        try:
            await db.skill.create(
                data={
                    "employee_id": eid,
                    "coe": safe_str(row.get("COE"), "Unknown"),
                    "skill_name": safe_str(row.get("Skill"), "Unknown"),
                    "sub_skill": safe_str(row.get("SubSkill")),
                    "experience": safe_str(row.get("Experience")),
                    "score": safe_int(row.get("Score"), 0),
                }
            )
            skill_count += 1
        except Exception as e:
            skill_errors += 1
            if skill_errors <= 3:
                _log_warning(f"Skill for {eid} failed: {e}")
    print(f"  ✓ {skill_count} skill records ingested ({skill_errors} errors)")

    # ── COMPETENCIES (NEW) ────────────────────────────────────────────────
    print("\n🧠 Ingesting Competencies…")
    comp_count = 0
    comp_errors = 0
    if not df_comp.empty:
        for _, row in df_comp.iterrows():
            eid = safe_str(row.get("employee_id") or row.get("Employee ID"))
            if not eid or eid not in emp_ids_ingested:
                continue
            try:
                score = safe_float(row.get("score", row.get("Score", 0)), 0.0)
                if score == 0.0:
                    continue  # Skip zero-score rows — no signal
                dimension = safe_str(row.get("dimension", row.get("variable")), "unknown")
                role_track = safe_str(row.get("role_track", row.get("job_name")), "unknown")
                await db.competency.create(
                    data={
                        "employee_id": eid,
                        "role_track": role_track,
                        "dimension": dimension,
                        "score": score,
                    }
                )
                comp_count += 1
            except Exception as e:
                comp_errors += 1
                if comp_errors <= 3:
                    _log_warning(f"Competency for {eid} failed: {e}")
    print(f"  ✓ {comp_count} competency records ingested ({comp_errors} errors)")

    # ── PIPELINE REQUESTS (NEW) ────────────────────────────────────────────
    print("\n📊 Ingesting Pipeline Requests…")
    pipe_count = 0
    pipe_errors = 0
    if not df_pipe.empty:
        # FIX 5: Correct column names from actual Pipeline file (after snake_case normalisation)
        # Raw:   'Resources Requested'  → 'resources_requested'
        # Raw:   'Likely Start Date'    → 'likely_start_date'
        # Raw:   'Number of Weeks'      → 'number_of_weeks'
        # Raw:   'SOW Signed'           → 'sow_signed'
        # Raw:   'Skillset'             → 'skillset'
        # Raw:   'Cluster'              → 'cluster'
        col_map = {
            "role":         ["resources_requested", "role", "canonical_role", "resource_type", "designation"],
            "start_date":   ["likely_start_date", "start_date", "expected_start", "original_requested_start_date"],
            "num_weeks":    ["number_of_weeks", "num_weeks", "number_of_weeks", "duration_weeks"],
            "coe":          ["coe", "tech_coe", "cluster"],
            "primary_skill": ["skillset", "primary_skill", "skill"],
            "client_id":    ["client", "client_id"],
            "project_name": ["solution", "project_name", "opportunity_name"],
            "alloc_pct":    ["%", "allocation_pct", "percentage"],
        }

        def get_col(row, alternatives):
            for alt in alternatives:
                val = row.get(alt)
                if val is not None and not (isinstance(val, float) and pd.isnull(val)):
                    return val
            return None

        for idx, row in df_pipe.iterrows():
            try:
                role_raw = safe_str(get_col(row, col_map["role"]))
                # P0-3: Normalise raw role codes to canonical designation strings
                role = normalise_role(role_raw) if role_raw else "Unknown"
                # FIX 6: handle '75/100' and '25-50' in % column
                alloc_pct = safe_int(get_col(row, col_map["alloc_pct"]), 100)
                # FIX 1: safe_date returns datetime objects
                start_raw = safe_date(get_col(row, col_map["start_date"]))
                sow = bool(row.get("sow_signed", False))
                num_weeks = safe_int(get_col(row, col_map["num_weeks"]), 16)

                await db.pipelinerequest.create(
                    data={
                        "project_name": safe_str(get_col(row, col_map["project_name"])),
                        "client_id": safe_str(get_col(row, col_map["client_id"])),
                        "role": role_raw,       # preserve original for audit
                        "canonical_role": role,  # normalised for matching
                        "sow_signed": sow,
                        "start_date": start_raw,
                        "num_weeks": num_weeks,
                        "allocation_pct": alloc_pct,
                        "coe": safe_str(get_col(row, col_map["coe"])),
                        "primary_skill": safe_str(get_col(row, col_map["primary_skill"])),
                        "source_row": int(idx),
                    }
                )
                pipe_count += 1
            except Exception as e:
                pipe_errors += 1
                if pipe_errors <= 3:
                    _log_warning(f"Pipeline row {idx} failed: {e}")
    print(f"  ✓ {pipe_count} pipeline requests ingested ({pipe_errors} errors)")

    # ── WEEKLY STATUS REPORTS (NEW) ────────────────────────────────────────
    print("\n📅 Ingesting Weekly Status Reports…")
    wsr_count = 0
    wsr_skipped_fk = 0
    wsr_errors = 0
    if df_wsr is not None and not df_wsr.empty:
        # Filter epoch artefacts (dates before 2000 are data corruption)
        if "week_start_date" in df_wsr.columns:
            df_wsr["week_start_date"] = pd.to_datetime(
                df_wsr["week_start_date"], dayfirst=True, format="mixed", errors="coerce"
            )
            df_wsr = df_wsr[df_wsr["week_start_date"].dt.year >= 2000].copy()

        # Only keep last 52 weeks per project to keep DB lean
        latest_date = df_wsr["week_start_date"].max() if "week_start_date" in df_wsr.columns else None
        if latest_date:
            cutoff = latest_date - pd.Timedelta(weeks=52)
            df_wsr_recent = df_wsr[df_wsr["week_start_date"] >= cutoff].copy()
        else:
            df_wsr_recent = df_wsr.copy()

        pid_col = "project_id_masked" if "project_id_masked" in df_wsr_recent.columns else "project_id"

        for _, row in df_wsr_recent.iterrows():
            pid = safe_str(row.get(pid_col))
            if not pid or pid not in proj_ids_ingested:
                wsr_skipped_fk += 1
                continue
            try:
                week_date_val = row.get("week_start_date")
                # FIX 8: Pass datetime object (to_pydatetime), not isoformat string
                if pd.notna(week_date_val):
                    if hasattr(week_date_val, "to_pydatetime"):
                        week_dt = week_date_val.to_pydatetime()
                    else:
                        week_dt = safe_date(week_date_val)
                else:
                    week_dt = None

                await db.weeklystatus.create(
                    data={
                        "project_id": pid,
                        "week_start_date": week_dt,
                        "schedule_status": safe_str(row.get("schedule_status")),
                        "scope_status": safe_str(row.get("scope_status")),
                        "budget_status": safe_str(row.get("budget_status")),
                        "quality_status": safe_str(row.get("quality_status")),
                        "csat_status": safe_str(row.get("csat_status")),
                        "team_status": safe_str(row.get("team_status")),
                        "overall_status": safe_str(row.get("overall_status")),
                    }
                )
                wsr_count += 1
            except Exception as e:
                wsr_errors += 1
                if wsr_errors <= 3:
                    _log_warning(f"WSR for {pid} failed: {e}")

    print(f"  ✓ {wsr_count} WSR records ingested | {wsr_skipped_fk} skipped (FK miss) | {wsr_errors} errors")

    print("\n✅ ETL complete — all data ingested.")
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(ingest_data())
