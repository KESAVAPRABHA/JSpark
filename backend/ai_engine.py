"""
ai_engine.py — JSpark v2 Recommendation Engine (LOCAL LLM, DATA COMPLIANT)

CHANGES FROM PREVIOUS VERSION:
  Gemini API replaced with local Ollama (mistral:7b-instruct)
  ChromaDB embeddings use local nomic-embed-text via OllamaEmbeddingFunction
  build_vector_db() reads skill_vector_text directly from clean CSVs
  Returns ranked top-3 candidates with availability gate + seniority weighting
  Structured JSON rationale output (parseable, not just a text blob)
  Zero data sent to external APIs — fully compliant with JMAN data policy
"""
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
import os, json, re
import chromadb
from prisma import Prisma
from local_llm import OllamaEmbeddingFunction, llm_call_with_fallback

COSINE_THRESHOLD = 0.40
TOP_N_QUERY      = 15
TOP_N_RETURN     = 3

DATA_DIR    = os.environ.get("DATA_DIR", "../data")
CLEANED_DIR = os.environ.get("CLEANED_DIR",
    os.path.join(DATA_DIR, "cleaned") if os.path.isdir(os.path.join(DATA_DIR, "cleaned")) else DATA_DIR)

SKILLS_CSV    = [os.path.join(CLEANED_DIR, "05_skills_clean.csv"), os.path.join(DATA_DIR, "05_skills_clean.csv")]
COMP_CSV      = [os.path.join(CLEANED_DIR, "06_competency_clean.csv"), os.path.join(DATA_DIR, "06_competency_clean.csv")]

def _find_file(candidates):
    for p in candidates:
        if os.path.exists(p): return p
    return None

# ── ChromaDB (local embeddings via Ollama) ────────────────────────────────────
_embedding_fn = OllamaEmbeddingFunction()
chroma_client = chromadb.PersistentClient(path="./chroma_db")
try:
    collection = chroma_client.get_or_create_collection(
        name="employee_skills",
        metadata={"hnsw:space": "cosine"},
        embedding_function=_embedding_fn,
    )
except Exception:
    collection = chroma_client.get_collection(name="employee_skills", embedding_function=_embedding_fn)

# ── Seniority weighting ────────────────────────────────────────────────────────
SENIORITY_RANK = {
    "principal": 8, "solution architect": 7, "technical architect": 7,
    "senior software engineer": 6, "senior associate consultant": 5,
    "software engineer": 5, "associate consultant": 4, "solution consultant": 4,
    "solutions consultant": 4, "solutions enabler": 3, "solution enabler": 3,
    "consultant": 4, "trainee software engineer": 2,
}

def _seniority_penalty(required_role: str, candidate_designation: str) -> float:
    req  = SENIORITY_RANK.get(required_role.lower().strip(), 0)
    cand = SENIORITY_RANK.get((candidate_designation or "").lower().strip(), 0)
    if req == 0 or cand == 0: return 0.0
    return max(0, req - cand - 1) * 0.07

# ── Competency labels ──────────────────────────────────────────────────────────
DIMENSION_LABELS = {
    "techno_functional": "Strong techno-functional expertise",
    "consulting_advisory": "Consulting and advisory skills",
    "client_influence": "Client influence and stakeholder management",
    "communication": "Clear communication and structured presentation",
    "ambiguity": "Navigates ambiguity and drives clarity under pressure",
    "capability_articulation": "Articulates technical capabilities to business stakeholders",
    "architecture_estimation": "Architecture estimation and solution design",
    "project_planning": "Project planning, delivery management, and agile execution",
}

# ── CSV loaders ────────────────────────────────────────────────────────────────
def _build_skill_map_from_csv() -> dict:
    import pandas as pd
    path = _find_file(SKILLS_CSV)
    if not path: return {}
    print(f"  ℹ️  Skills from: {path}")
    df = pd.read_csv(path, encoding="latin1").dropna(subset=["skill_vector_text"])
    # Defence-in-depth: drop zero-score rows even if etl_pipeline already filtered them.
    # Score=0 means "Lacks capability" — including them bloats the vector text and pushes
    # documents past Ollama's 2048-token context window, causing embedding crashes.
    if "Score" in df.columns:
        before = len(df)
        df["Score"] = pd.to_numeric(df["Score"], errors="coerce").fillna(0)
        df = df[df["Score"] > 0]
        dropped = before - len(df)
        if dropped:
            print(f"  ⚠️  Dropped {dropped} zero-score skill rows from vector build (Score=0 = no capability)")
    result = df.groupby("employee_id")["skill_vector_text"].apply(lambda t: " | ".join(t)).to_dict()
    print(f"  ✓ Skill profiles: {len(result)}")
    return result

def _build_competency_map_from_csv() -> dict:
    import pandas as pd
    path = _find_file(COMP_CSV)
    if not path: return {}
    print(f"  ℹ️  Competency from: {path}")
    df = pd.read_csv(path, encoding="latin1")
    df.columns = df.columns.str.strip()
    emp_col   = next((c for c in df.columns if c.lower() in ("employee_id", "employee id")), None)
    dim_col   = next((c for c in df.columns if "dimension_short" in c.lower() or c.lower() == "dimension"), None)
    score_col = next((c for c in df.columns if c.lower() == "score"), None)
    label_col = next((c for c in df.columns if "score_label" in c.lower()), None)
    if not emp_col or not score_col: return {}
    df = df.rename(columns={emp_col: "employee_id"})
    df["score"] = pd.to_numeric(df[score_col], errors="coerce").fillna(0)
    df = df[df["score"] > 0]
    comp_map = {}
    for emp_id, grp in df.groupby("employee_id"):
        parts = [f"{DIMENSION_LABELS.get(str(r.get(dim_col,'')).strip(), str(r.get(dim_col,'')).replace('_',' ').title())} ({str(r.get(label_col,'')).strip()}, {float(r['score']):.1f}/5)" for _, r in grp.iterrows()]
        if parts: comp_map[str(emp_id)] = ". ".join(parts) + "."
    print(f"  ✓ Competency profiles: {len(comp_map)}")
    return comp_map

# ── Build vector DB ────────────────────────────────────────────────────────────
async def build_vector_db():
    """Build ChromaDB from clean CSVs. All embeddings local via Ollama nomic-embed-text."""
    db = Prisma(); await db.connect()
    print("  📋 Loading employee pool…")
    employees = await db.employee.find_many(where={"is_recommended_pool": True, "date_of_resignation": None})
    if not employees:
        print("  ❌ No employees. Run etl_pipeline.py first."); await db.disconnect(); return
    pool = {e.id: e for e in employees}
    print(f"  ✓ Pool: {len(pool)} employees")

    skill_map = _build_skill_map_from_csv()
    comp_map  = _build_competency_map_from_csv()

    docs, metadatas, ids, skipped = [], [], [], 0
    for emp_id, emp in pool.items():
        st = (skill_map.get(emp_id) or "").strip()
        ct = (comp_map.get(emp_id) or "").strip()
        if not st and not ct: skipped += 1; continue
        full_doc = st + (" || COMPETENCY: " + ct if ct else "")
        docs.append(full_doc)
        metadatas.append({"employee_id": emp_id, "designation": emp.designation or "Unknown",
                          "primary_domain": emp.primary_skill_domain or "Unknown", "location": emp.location or "Unknown"})
        ids.append(emp_id)

    if skipped: print(f"  ⚠️  {skipped} skipped (no data)")
    if not docs: print(f"  ❌ No documents. Check CSV paths: {SKILLS_CSV}"); await db.disconnect(); return

    print(f"  🔢 Embedding {len(docs)} documents locally (nomic-embed-text)…")
    collection.upsert(documents=docs, metadatas=metadatas, ids=ids)
    print(f"  ✅ {collection.count()} profiles indexed | all local, data compliant")
    await db.disconnect()

# ── Availability check ─────────────────────────────────────────────────────────
async def _get_available_capacity(employee_id: str, db: Prisma) -> int:
    active = await db.allocation.find_many(
        where={"employee_id": employee_id, "is_allocation_active": True,
               "is_placeholder_date": False, "status": {"not": "BAU_OVERHEAD"}})
    committed = sum(a.percentage for a in active if a.status not in ("SHADOW", "BAU_OVERHEAD"))
    return max(0, 100 - committed)

# ── Recommend resource ─────────────────────────────────────────────────────────
async def recommend_resource(project_requirements: str, required_role: str, db: Prisma) -> dict:
    count = collection.count()
    if count == 0:
        return {"status": "ERROR", "signal": "Vector DB empty", "candidates": [],
                "reason": "Call POST /api/vector-db/rebuild or delete chroma_db/ and restart."}

    role_lower = required_role.lower().strip()
    STOP = {"and", "or", "the", "a", "of", "in", "for", "sr", "jr"}

    results = collection.query(query_texts=[project_requirements], n_results=min(TOP_N_QUERY, count))
    if not results["ids"][0]:
        return {"status": "NO_MATCH_FOUND", "signal": "Initiate Hire", "candidates": [],
                "reason": "No semantic results."}

    candidates = []
    for emp_id, raw_dist, doc, meta in zip(
            results["ids"][0], results["distances"][0], results["documents"][0], results["metadatas"][0]):
        designation = (meta.get("designation") or "").lower()
        role_words  = {w for w in role_lower.replace("_", " ").split() if w not in STOP}
        if not (role_words & set(designation.split())) and role_lower not in designation:
            continue
        penalty      = _seniority_penalty(required_role, meta.get("designation", ""))
        adjusted     = float(raw_dist) + penalty
        if adjusted > COSINE_THRESHOLD: continue
        avail = await _get_available_capacity(emp_id, db)
        if avail <= 0: continue
        candidates.append({"employee_id": emp_id, "designation": meta.get("designation"),
            "primary_domain": meta.get("primary_domain"), "location": meta.get("location"),
            "cosine_distance": round(float(raw_dist), 3), "seniority_penalty": round(penalty, 3),
            "skill_match_pct": round((1 - float(raw_dist)) * 100, 1),
            "available_capacity_pct": avail, "_doc": doc})
        if len(candidates) >= TOP_N_RETURN: break

    if not candidates:
        return {"status": "NO_MATCH_FOUND", "signal": "Initiate Hire", "candidates": [],
                "reason": f"No available '{required_role}' within threshold {COSINE_THRESHOLD}."}

    SYSTEM = ("You are a resource allocation AI. Respond ONLY with valid JSON. No markdown. No preamble.")
    PROMPT = (
        "Employee: {emp_id} | {designation} | {location} | {capacity}% free\n"
        "Profile: {skills}\nRequirements: {requirements}\nRole: {role}\n"
        "Respond ONLY with JSON:\n"
        '{"match_confidence":<0-100>,"top_matching_skills":["s1","s2","s3"],'
        '"skill_gaps":["g1"],"availability_note":"<1 sentence>","rationale":"<2-3 sentences>",'
        '"risk_flag":<null or "SKILL_GAP" or "JUNIOR_FOR_ROLE" or "APPROACHING_RESIGNATION">}'
    )

    ranked = []
    for rank, c in enumerate(candidates, 1):
        prompt = PROMPT.format(emp_id=c["employee_id"], designation=c["designation"],
            location=c["location"], capacity=c["available_capacity_pct"],
            skills=c["_doc"][:1500], requirements=project_requirements, role=required_role)
        raw, model_used = llm_call_with_fallback(prompt, SYSTEM, max_tokens=350, expect_json=True)
        try:
            s = json.loads(re.sub(r"```(?:json)?|```", "", raw).strip())
        except Exception:
            s = {"match_confidence": round(c["skill_match_pct"]), "top_matching_skills": [],
                 "skill_gaps": [], "availability_note": "", "rationale": raw[:300], "risk_flag": None}
        ranked.append({**{k: v for k, v in c.items() if not k.startswith("_")},
            "rank": rank, "match_confidence": s.get("match_confidence", c["skill_match_pct"]),
            "top_matching_skills": s.get("top_matching_skills", []),
            "skill_gaps": s.get("skill_gaps", []),
            "availability_note": s.get("availability_note", ""),
            "rationale": s.get("rationale", ""), "risk_flag": s.get("risk_flag"),
            "llm_model": model_used})

    return {"status": "MATCH_FOUND", "candidates": ranked, "top_candidate": ranked[0]}
