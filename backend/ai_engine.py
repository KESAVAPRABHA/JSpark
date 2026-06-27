"""
ai_engine.py — JSpark v2 Recommendation Engine (FIXED)

ROOT CAUSE OF EMPTY RECOMMENDATIONS (v2 bug):
  build_vector_db() queried employees with include={"skills": True, "competencies": True}
  but the Prisma Python client returned skills=None / competencies=None for every employee.
  This caused `if not full_doc.strip(): continue` to skip ALL employees →
  ChromaDB was populated with 0 documents → every query returned no results.

FIX APPLIED:
  ✅ build_vector_db() now reads directly from the pre-cleaned CSV files.
     - 05_skills_clean.csv already has `skill_vector_text` pre-computed per row.
       Group by employee_id → join all texts → one rich document per person.
     - 06_competency_clean.csv has `dimension_short`, `score`, `score_label` per row.
       Group by employee_id → generate natural-language competency sentences.
  ✅ DB is still used for the employee pool filter (is_recommended_pool, date_of_resignation)
     and for the availability gate (live allocation check). Only the TEXT BUILDING is CSV-sourced.
  ✅ Falls back gracefully to DB-based skill text if CSVs are not present.
  ✅ All v2 fixes retained: ranked top-3, availability gate, LLM rationale, flexible role match.
"""

import os
import chromadb
from prisma import Prisma

# ─────────────────────────────────────────────────────────────────────────────
# LLM — lazy-init so the engine can be imported without crashing if key is missing
# ─────────────────────────────────────────────────────────────────────────────
_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        from langchain_google_genai import ChatGoogleGenerativeAI
        _llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.0)
    return _llm


# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB — cosine distance collection
# ─────────────────────────────────────────────────────────────────────────────
chroma_client = chromadb.PersistentClient(path="./chroma_db")

try:
    collection = chroma_client.get_or_create_collection(
        name="employee_skills",
        metadata={"hnsw:space": "cosine"},
    )
except Exception:
    collection = chroma_client.get_collection(name="employee_skills")

COSINE_THRESHOLD = 0.65   # > 0.35 → less than 65% semantic similarity → no match
TOP_N = 10                 # query up to 10 candidates; return top 3 available


# ─────────────────────────────────────────────────────────────────────────────
# DATA PATHS — resolved once at module load
# ─────────────────────────────────────────────────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "../data")
CLEANED_DIR = os.environ.get(
    "CLEANED_DIR",
    os.path.join(DATA_DIR, "cleaned") if os.path.isdir(os.path.join(DATA_DIR, "cleaned")) else DATA_DIR,
)

SKILLS_CSV_CANDIDATES = [
    os.path.join(CLEANED_DIR, "05_skills_clean.csv"),
    os.path.join(DATA_DIR, "05_skills_clean.csv"),
    os.path.join(DATA_DIR, "05_260624_Skill_Data.csv"),
]
COMPETENCY_CSV_CANDIDATES = [
    os.path.join(CLEANED_DIR, "06_competency_clean.csv"),
    os.path.join(DATA_DIR, "06_competency_clean.csv"),
]

def _find_file(candidates: list[str]) -> str | None:
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# ─────────────────────────────────────────────────────────────────────────────
# COMPETENCY LABEL MAP — dimension_short → human-readable phrase
# ─────────────────────────────────────────────────────────────────────────────
DIMENSION_LABELS = {
    "techno_functional":       "Strong techno-functional expertise",
    "consulting_advisory":     "Consulting and advisory skills",
    "client_influence":        "Client influence and stakeholder management",
    "communication":           "Clear communication and structured presentation",
    "ambiguity":               "Navigates ambiguity and drives clarity under pressure",
    "capability_articulation": "Articulates technical capabilities to business stakeholders",
    "architecture_estimation": "Architecture estimation and solution design",
    "project_planning":        "Project planning, delivery management, and agile execution",
}


# ─────────────────────────────────────────────────────────────────────────────
# BUILD SKILL MAP FROM CSV
# Returns { employee_id: "combined skill_vector_text string" }
# ─────────────────────────────────────────────────────────────────────────────
def _build_skill_map_from_csv() -> dict[str, str]:
    """
    Read 05_skills_clean.csv and group skill_vector_text by employee_id.
    The `skill_vector_text` column is already pre-computed by the data quality script.

    Returns {} if the CSV is not found (caller falls back to DB-based text).
    """
    import pandas as pd

    path = _find_file(SKILLS_CSV_CANDIDATES)
    if path is None:
        print("  ⚠️  skills CSV not found — falling back to DB skill text")
        return {}

    print(f"  ℹ️  Reading skill profiles from: {path}")
    df = pd.read_csv(path, encoding="latin1")

    # Drop zero-score/negative skills to prevent vector poisoning
    score_col = next((c for c in df.columns if c.lower() == "score"), None)
    if score_col:
        df[score_col] = pd.to_numeric(df[score_col], errors="coerce").fillna(0)
        df = df[df[score_col] > 0]

    if "skill_vector_text" not in df.columns:
        df["skill_vector_text"] = df.apply(_reconstruct_skill_text, axis=1)
    else:
        # Extra safety drop for pre-computed negative texts
        df = df[~df["skill_vector_text"].astype(str).str.contains("Lacks capability", na=False, case=False)]

    df = df.dropna(subset=["skill_vector_text"])
    df = df[df["skill_vector_text"].str.strip() != ""]
    
    # Group by employee_id: join all skill texts for one employee into one document
    skill_map = (
        df.groupby("employee_id")["skill_vector_text"]
        .apply(lambda texts: " | ".join(texts.tolist()))
        .to_dict()
    )
    print(f"  ✓ Skill map built: {len(skill_map)} employees have skill profiles")
    return skill_map


def _reconstruct_skill_text(row) -> str:
    """Fallback text builder if skill_vector_text column is absent."""
    try:
        skill = str(row.get("Skill") or row.get("skill_name") or "").strip()
        sub   = str(row.get("SubSkill") or row.get("sub_skill") or "").strip()
        exp   = str(row.get("Experience") or row.get("experience") or "").strip()
        score = int(row.get("Score") or row.get("score") or 0)
        label_map = {0: "no_capability", 1: "beginner", 2: "basic", 3: "competent", 4: "proficient", 5: "expert"}
        label = label_map.get(score, "unknown")
        name = f"{skill} - {sub}" if sub and sub.lower() != skill.lower() else skill
        if not name.strip():
            return ""
        if not name.strip() or score == 0:
            return ""
            
        return f"Proficient in {name} ({label}, {exp})"
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# BUILD COMPETENCY MAP FROM CSV
# Returns { employee_id: "combined competency text string" }
# ─────────────────────────────────────────────────────────────────────────────
def _build_competency_map_from_csv() -> dict[str, str]:
    """
    Read 06_competency_clean.csv (long-format) and build a competency text
    per employee.  Only scores > 0 contribute.

    Expected columns: employee_id, dimension_short, score, score_label
    Falls back gracefully if file is absent.
    """
    import pandas as pd

    path = _find_file(COMPETENCY_CSV_CANDIDATES)
    if path is None:
        print("  ⚠️  competency CSV not found — competency dimension will be omitted from vector docs")
        return {}

    print(f"  ℹ️  Reading competency profiles from: {path}")
    df = pd.read_csv(path, encoding="latin1")

    # Normalise column names (handle both snake_case and original headers)
    df.columns = df.columns.str.strip()

    emp_col = next((c for c in df.columns if c.lower() in ("employee_id", "employee id")), None)
    dim_col = next((c for c in df.columns if "dimension_short" in c.lower() or c.lower() == "dimension"), None)
    score_col = next((c for c in df.columns if c.lower() == "score"), None)
    label_col = next((c for c in df.columns if "score_label" in c.lower()), None)

    if not emp_col or not score_col:
        print("  ⚠️  Competency CSV missing required columns — skipping")
        return {}

    df = df.rename(columns={emp_col: "employee_id"})
    df["score"] = pd.to_numeric(df[score_col], errors="coerce").fillna(0)
    df = df[df["score"] > 0]   # Only demonstrated competencies contribute

    comp_map: dict[str, str] = {}
    for emp_id, grp in df.groupby("employee_id"):
        parts = []
        for _, row in grp.iterrows():
            dim  = str(row.get(dim_col or "dimension", "")).strip() if dim_col else ""
            lbl  = str(row.get(label_col or "", "")).strip() if label_col else ""
            sc   = float(row["score"])
            human_label = DIMENSION_LABELS.get(dim, dim.replace("_", " ").title())
            parts.append(f"{human_label} (competency: {lbl}, {sc:.1f}/5)")
        if parts:
            comp_map[str(emp_id)] = ". ".join(parts) + "."

    print(f"  ✓ Competency map built: {len(comp_map)} employees have competency profiles")
    return comp_map


# ─────────────────────────────────────────────────────────────────────────────
# BUILD VECTOR DB — called on lifespan startup if collection is empty
# ─────────────────────────────────────────────────────────────────────────────
async def build_vector_db():
    """
    Build / refresh the ChromaDB vector store.

    STRATEGY (CSV-first, DB-fallback):
      1.  Load employee pool from DB  (who is eligible for recommendations)
      2.  Load skill text from CSV    (pre-computed skill_vector_text — fast and reliable)
      3.  Load competency text from CSV (long-format competency scores)
      4.  Combine skill + competency text per employee
      5.  Upsert into ChromaDB

    This bypasses the broken `include={"skills": True}` DB query that returned
    skills=None / competencies=None, causing 0 documents to be indexed.
    """
    import pandas as pd

    db = Prisma()
    await db.connect()

    # ── Step 1: Load recommended employee pool from DB ────────────────────
    print("  📋 Loading employee pool from DB…")
    employees = await db.employee.find_many(
        where={
            "is_recommended_pool": True,
            "date_of_resignation": None,
        }
    )
    # NOTE: We do NOT use include={"skills": True} here — that's what was broken.
    # Skill and competency text come from CSVs in steps 2 & 3.

    if not employees:
        print("  ❌ No employees found in DB with is_recommended_pool=True.")
        print("     Run etl_pipeline.py first, then call this again.")
        await db.disconnect()
        return

    pool = {emp.id: emp for emp in employees}
    print(f"  ✓ Employee pool: {len(pool)} employees eligible for recommendations")

    # ── Step 2: Build skill text map from CSV ─────────────────────────────
    skill_map = _build_skill_map_from_csv()

    # Fallback: if CSV not found, reconstruct from DB Skill records
    if not skill_map:
        print("  🔄 CSV unavailable — loading skills from DB (slower)…")
        all_skills = await db.skill.find_many(
            where={"employee_id": {"in": list(pool.keys())}}
        )
        for s in all_skills:
            if s.score > 0:
                text = f"Proficient in {s.skill_name} (score {s.score}/5, {s.experience or ''})."
                skill_map[s.employee_id] = skill_map.get(s.employee_id, "") + " " + text
                
        print(f"  ✓ DB skill map: {len(skill_map)} employees")

    # ── Step 3: Build competency text map from CSV ────────────────────────
    comp_map = _build_competency_map_from_csv()

    # Fallback: if CSV not found, reconstruct from DB Competency records
    if not comp_map:
        print("  🔄 CSV unavailable — loading competencies from DB…")
        all_comps = await db.competency.find_many(
            where={"employee_id": {"in": list(pool.keys())}}
        )
        for c in all_comps:
            if c.score > 0:
                label = DIMENSION_LABELS.get(c.dimension, c.dimension.replace("_", " ").title())
                text = f"{label} (competency score {c.score:.1f}/5)."
                comp_map[c.employee_id] = comp_map.get(c.employee_id, "") + " " + text
        print(f"  ✓ DB competency map: {len(comp_map)} employees")

    # ── Step 4: Assemble and upsert documents ─────────────────────────────
    docs, metadatas, ids = [], [], []
    no_skill_count = 0

    for emp_id, emp in pool.items():
        skill_text = (skill_map.get(emp_id) or "").strip()
        comp_text  = (comp_map.get(emp_id) or "").strip()

        if not skill_text and not comp_text:
            # Employee is in pool but has no skill/competency data
            no_skill_count += 1
            continue   # Skip — indexing empty docs would corrupt similarity scores

        full_doc = skill_text
        if comp_text:
            full_doc += " || COMPETENCY: " + comp_text

        docs.append(full_doc)
        metadatas.append({
            "employee_id":    emp_id,
            "designation":    emp.designation or "Unknown",
            "primary_domain": emp.primary_skill_domain or "Unknown",
            "location":       emp.location or "Unknown",
        })
        ids.append(emp_id)

    if no_skill_count:
        print(f"  ⚠️  {no_skill_count} pool employees skipped — no skill or competency data found")

    if not docs:
        print(
            "  ❌ Zero documents to index.  Likely causes:\n"
            "     1. skills CSV not found at expected path (check DATA_DIR / CLEANED_DIR env vars)\n"
            "     2. employee_ids in skills CSV don't match employee_ids in DB\n"
            "     3. ETL was not run — DB has employees but no skill records\n"
            f"     Expected skills CSV at: {SKILLS_CSV_CANDIDATES}"
        )
        await db.disconnect()
        return

    # Upsert into existing collection.
    # IDs are employee_ids — upserting with the same ID cleanly overwrites
    # stale documents, so this works for both initial build and refresh.
    # We avoid delete+recreate because `from ai_engine import collection`
    # in main.py would hold a stale reference to the deleted object.
    collection.upsert(documents=docs, metadatas=metadatas, ids=ids)

    # Verify
    count = collection.count()
    print(
        f"\n  ✅ Vector DB built successfully:\n"
        f"     • {count} employee profiles indexed\n"
        f"     • {len([d for d in docs if 'COMPETENCY' in d])} profiles include competency dimension\n"
        f"     • {len([d for d in docs if 'COMPETENCY' not in d])} profiles are skill-only\n"
        f"     • Cosine similarity threshold: {COSINE_THRESHOLD}"
    )

    await db.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# AVAILABILITY CHECK — prevents recommending over-committed employees
# ─────────────────────────────────────────────────────────────────────────────
async def _get_available_capacity(employee_id: str, db: Prisma) -> int:
    """
    Return remaining capacity % for an employee.
    Excludes placeholder-date allocations (CLIENT_127 BAU overhead) from the sum.
    100 = fully available, 0 = fully committed.
    """
    active_allocs = await db.allocation.find_many(
        where={
            "employee_id": employee_id,
            "is_allocation_active": True,
            "status": {"not": "BAU_OVERHEAD"},
            "is_placeholder_date": False,   # exclude rolling-placeholder rows
        }
    )
    committed = sum(
        a.percentage for a in active_allocs
        if a.status not in ("SHADOW", "BAU_OVERHEAD")
    )
    return max(0, 100 - committed)


# ─────────────────────────────────────────────────────────────────────────────
# RECOMMEND — ranked list of top 3 available candidates
# ─────────────────────────────────────────────────────────────────────────────
async def recommend_resource(project_requirements: str, required_role: str, db: Prisma):
    """
    Returns a ranked list of up to 3 available candidates.
    Each candidate includes: employee_id, rank, cosine_distance,
    skill_match_pct, available_capacity_pct, rationale.
    """

    # ── Sanity check: collection must have documents ──────────────────────
    count = collection.count()
    if count == 0:
        return {
            "status": "ERROR",
            "signal": "Vector DB is empty",
            "reason": (
                "ChromaDB has 0 documents. Call POST /api/vector-db/rebuild "
                "or restart the server (auto-rebuild runs on startup when empty)."
            ),
            "candidates": [],
        }

    role_lower = required_role.lower().strip()

    results = collection.query(
        query_texts=[project_requirements],
        n_results=min(TOP_N, count),
        # No `where` filter: flexible role matching done in Python below.
        # Exact-string `where` filters cause misses on "SSE" vs "Senior Software Engineer".
    )

    if not results["ids"][0]:
        return {
            "status": "NO_MATCH_FOUND",
            "signal": "Initiate Hire",
            "reason": "Vector search returned no results.",
            "candidates": [],
        }

    candidates = []
    for emp_id, distance, doc, meta in zip(
        results["ids"][0],
        results["distances"][0],
        results["documents"][0],
        results["metadatas"][0],
    ):
        designation = (meta.get("designation") or "").lower()

        # ── Flexible role match ──────────────────────────────────────────
        # Accept if ANY meaningful word from the requested role appears in designation.
        # Stop-words ("and", "or", "the") are excluded to avoid false matches.
        STOP = {"and", "or", "the", "a", "of", "in", "for"}
        role_words = {w for w in role_lower.replace("_", " ").split() if w not in STOP}
        desig_words = set(designation.split())
        role_match = bool(role_words & desig_words) or (role_lower in designation)

        if not role_match:
            continue

        # ── Cosine distance gate ─────────────────────────────────────────
        if distance > COSINE_THRESHOLD:
            continue

        # ── Availability gate ────────────────────────────────────────────
        available_pct = await _get_available_capacity(emp_id, db)
        if available_pct <= 0:
            continue  # Fully committed — skip

        candidates.append({
            "employee_id":         emp_id,
            "designation":         meta.get("designation"),
            "primary_domain":      meta.get("primary_domain"),
            "location":            meta.get("location"),
            "cosine_distance":     round(float(distance), 3),
            "skill_match_pct":     round((1 - float(distance)) * 100, 1),
            "available_capacity_pct": available_pct,
            "doc":                 doc,
        })

        if len(candidates) >= 3:
            break   # We have our top 3

    # ── No candidates after all filters ──────────────────────────────────
    if not candidates:
        return {
            "status": "NO_MATCH_FOUND",
            "signal": "Initiate Hire",
            "reason": (
                f"No available employee with role matching '{required_role}' found "
                f"within cosine threshold {COSINE_THRESHOLD}. "
                f"All semantic matches are either fully allocated or below quality threshold. "
                f"(Vector DB contains {count} indexed profiles.)"
            ),
            "candidates": [],
        }

    # ── Generate LLM rationale per candidate ─────────────────────────────
    llm = _get_llm()
    from langchain_core.prompts import PromptTemplate

    rationale_prompt = PromptTemplate(
        input_variables=["rank", "emp_id", "skills", "reqs", "capacity", "location"],
        template=(
            "You are a Resourcing Matchmaker for a data & AI consultancy. "
            "Write exactly 3 concise bullet points (max 20 words each) "
            "defending why {emp_id} (ranked #{rank}, {capacity}% capacity free, based in {location}) "
            "is a strong match for this project request.\n"
            "Project Requirements: {reqs}\n"
            "Employee Skill & Competency Profile: {skills}\n"
            "Rules: Start each bullet with '•'. Be specific — name skills and competency dimensions. "
            "Do not use generic phrases like 'strong candidate'."
        ),
    )

    ranked = []
    for rank, c in enumerate(candidates, 1):
        try:
            resp = llm.invoke(
                rationale_prompt.format(
                    rank=rank,
                    emp_id=c["employee_id"],
                    skills=c["doc"][:1200],   # truncate to stay within LLM token budget
                    reqs=project_requirements,
                    capacity=c["available_capacity_pct"],
                    location=c.get("location", "Unknown"),
                )
            )
            rationale = resp.content.strip()
        except Exception as exc:
            rationale = f"Rationale unavailable ({exc}). Check GOOGLE_API_KEY."

        ranked.append({
            "rank":                  rank,
            "employee_id":           c["employee_id"],
            "designation":           c["designation"],
            "primary_domain":        c["primary_domain"],
            "location":              c["location"],
            "cosine_distance":       c["cosine_distance"],
            "skill_match_pct":       c["skill_match_pct"],
            "available_capacity_pct": c["available_capacity_pct"],
            "rationale":             rationale,
        })

    return {
        "status":        "MATCH_FOUND",
        "candidates":    ranked,
        "top_candidate": ranked[0],   # backward-compat convenience field
    }
