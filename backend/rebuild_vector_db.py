"""
rebuild_vector_db.py — Standalone script to rebuild ChromaDB from clean CSVs.

Run this INSTEAD OF (or before) starting the server to diagnose and fix
the "0 employees recommended" problem.

Usage:
    python rebuild_vector_db.py               # auto-detect CSV paths
    python rebuild_vector_db.py --verify      # rebuild + run a test query
    DATA_DIR=../data python rebuild_vector_db.py   # explicit path

What this script does:
    1. Connects to the DB to get the recommended employee pool
    2. Reads skill profiles from 05_skills_clean.csv (uses pre-computed skill_vector_text)
    3. Reads competency profiles from 06_competency_clean.csv
    4. Builds one rich text document per employee (skill + competency combined)
    5. Upserts all documents into ChromaDB
    6. Prints a verification summary
"""

import asyncio
import sys
import os

# ── Allow running from inside the backend directory ──────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

# ── Set DATA_DIR from env or use default ─────────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "../data")
CLEANED_DIR = os.environ.get(
    "CLEANED_DIR",
    os.path.join(DATA_DIR, "cleaned")
    if os.path.isdir(os.path.join(DATA_DIR, "cleaned"))
    else DATA_DIR,
)
os.environ.setdefault("DATA_DIR", DATA_DIR)
os.environ.setdefault("CLEANED_DIR", CLEANED_DIR)


async def main():
    verify = "--verify" in sys.argv

    print("=" * 60)
    print("  JSpark Vector DB Rebuild")
    print("=" * 60)
    print(f"  DATA_DIR    : {DATA_DIR}")
    print(f"  CLEANED_DIR : {CLEANED_DIR}")
    print()

    # ── Import after env vars are set ────────────────────────────────────
    from ai_engine import build_vector_db, collection, COSINE_THRESHOLD

    print("🔧 Building vector store…")
    await build_vector_db()

    # ── Verification query ────────────────────────────────────────────────
    count = collection.count()
    print(f"\n📊 ChromaDB collection count: {count}")

    if count == 0:
        print("\n❌ REBUILD FAILED — 0 documents in ChromaDB.")
        print("\n   Checklist:")
        print(f"   1. Does this file exist?  {os.path.join(CLEANED_DIR, '05_skills_clean.csv')}")
        print(f"      → {os.path.exists(os.path.join(CLEANED_DIR, '05_skills_clean.csv'))}")
        print(f"   2. Does this file exist?  {os.path.join(CLEANED_DIR, '06_competency_clean.csv')}")
        print(f"      → {os.path.exists(os.path.join(CLEANED_DIR, '06_competency_clean.csv'))}")
        print("   3. Check that etl_pipeline.py ran successfully (employees must be in DB).")
        sys.exit(1)

    if verify:
        print("\n🔍 Running verification query: 'Python, dbt, Spark, AWS data engineering'…")
        results = collection.query(
            query_texts=["I need someone proficient in techops and automation and they need to know python also"],
            n_results=min(5, count),
        )
        print(f"\n   Top {len(results['ids'][0])} semantic matches:")
        for i, (emp_id, dist, meta) in enumerate(
            zip(results["ids"][0], results["distances"][0], results["metadatas"][0])
        ):
            match_pct = round((1 - dist) * 100, 1)
            designation = meta.get("designation", "?")
            domain = meta.get("primary_domain", "?")
            passed_threshold = "✅" if dist <= COSINE_THRESHOLD else "⚠️ (below threshold)"
            print(f"   #{i+1}  {emp_id}  |  {designation}  |  {domain}")
            print(f"        match={match_pct}%  distance={dist:.3f}  {passed_threshold}")

        print(f"\n   Cosine threshold: {COSINE_THRESHOLD}  "
              f"(results above {COSINE_THRESHOLD} would be filtered out in recommend)")

    print("\n✅ Done.  You can now call POST /api/recommend.")


if __name__ == "__main__":
    asyncio.run(main())
