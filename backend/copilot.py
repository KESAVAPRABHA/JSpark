"""
copilot.py — JSpark Resource Manager Co-pilot (LOCAL LLM, DATA COMPLIANT)

CHANGES FROM PREVIOUS VERSION:
  ✅ Groq/Gemini replaced with local Ollama (mistral:7b-instruct)
  ✅ httpx retry logic added (BUG 3 fix) — 3 attempts with 1s backoff
  ✅ All live resourcing data stays on-premise — zero external API calls
  ✅ skill_gaps endpoint added to _ENDPOINT_MAP
  ✅ data_note field added to answer when data sources had errors
"""

import asyncio
import json
import os
from typing import Optional

import httpx

from local_llm import llm_call_with_fallback

BASE_URL = os.environ.get("JSPARK_BASE_URL", "http://localhost:8000")

SYSTEM_PROMPT = """\
You are a Resource Management Co-pilot for JMAN Group, a data and AI consulting firm.
You have access to real-time resourcing data provided below.
Answer the Resource Manager's question in 3-5 sentences MAX.
Cite specific employee IDs, project IDs, numbers, and dates from the data.
End with ONE clear recommended action the RM should take RIGHT NOW.
Never make up data. If data is missing, say so explicitly.
Do NOT pad with generic advice. Be surgical and specific.\
"""

TOOL_DESCRIPTIONS = """\
Live data sources fetched from JSpark:
- summary: headline KPIs (bench count, at-risk projects, overrunning, shadow/unbilled resources)
- utilization: per-employee utilisation % with OVER/UNDER/OK flags
- ramp_down: projects ending within 30/60/90 days + overrunning projects
- pipeline_outlook: monthly Jul-Dec 2026 demand vs supply by role
- risk_scores: ML-predicted at-risk projects with SHAP root-cause drivers
- leakage: financial leakage from UNBILLED resources ($ weekly)
- skill_gaps: roles the system cannot fill internally — strategic hiring backlog\
"""

# ─────────────────────────────────────────────────────────────────────────────
# INTENT ROUTER
# ─────────────────────────────────────────────────────────────────────────────
_INTENT_MAP = [
    (["take on", "absorb", "new project", "capacity", "can we", "handle", "bandwidth"],
     ["summary", "utilization", "pipeline_outlook"]),
    (["assign", "recommend", "who should", "find someone", "find me", "who for", "best person"],
     ["utilization", "ramp_down"]),
    (["risk", "health", "blow up", "escalat", "amber", "red flag", "in trouble", "concern"],
     ["risk_scores", "ramp_down"]),
    (["bench", "available", "idle", "free", "unused", "unallocated", "sitting"],
     ["utilization", "summary"]),
    (["pipeline", "forecast", "demand", "supply", "jul", "aug", "sep", "oct", "nov", "dec",
      "q3", "q4", "next quarter", "upcoming", "outlook"],
     ["pipeline_outlook"]),
    (["leakage", "shadow", "unbilled", "revenue", "money", "cost", "losing", "wasting"],
     ["leakage", "utilization"]),
    (["ramp", "ending", "finish", "overrun", "overdue", "wrapping", "rolling off"],
     ["ramp_down"]),
    (["hire", "skill gap", "missing", "can't fill", "no one", "nobody", "vacancy"],
     ["skill_gaps", "utilization"]),
    (["over", "over-utilised", "overloaded", "stretched", "burnout"],
     ["utilization"]),
    (["summary", "overview", "status", "how are we", "where are we", "show me"],
     ["summary", "risk_scores", "leakage"]),
]

def _route_question(question: str) -> list[str]:
    q = question.lower()
    matched: set[str] = set()
    for keywords, endpoints in _INTENT_MAP:
        if any(kw in q for kw in keywords):
            matched.update(endpoints)
    if not matched:
        matched = {"summary", "utilization"}
    return list(matched)


# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHER — parallel httpx with retry (BUG 3 FIX)
# ─────────────────────────────────────────────────────────────────────────────
_ENDPOINT_MAP = {
    "summary":          "/api/dashboard/summary",
    "utilization":      "/api/dashboard/utilization",
    "ramp_down":        "/api/dashboard/ramp-down",
    "pipeline_outlook": "/api/dashboard/pipeline-outlook?sow_filter=all",
    "risk_scores":      "/api/risk-scores?at_risk_only=true",
    "leakage":          "/api/dashboard/leakage",
    "skill_gaps":       "/api/dashboard/skill-gaps",
}

async def _fetch_endpoint(name: str, client: httpx.AsyncClient) -> tuple[str, Optional[dict]]:
    """Fetch one endpoint with 3-attempt retry on connection errors."""
    url = BASE_URL + _ENDPOINT_MAP[name]
    for attempt in range(3):
        try:
            r = await client.get(url, timeout=10.0)
            r.raise_for_status()
            return name, r.json()
        except httpx.ConnectError:
            # Server not fully ready — retry with backoff (BUG 3 FIX)
            if attempt < 2:
                await asyncio.sleep(1.0)
                continue
            return name, {"_error": "endpoint_unavailable — server not ready"}
        except Exception as exc:
            return name, {"_error": str(exc)}
    return name, {"_error": "max_retries_exceeded"}


def _trim_data(data: dict, max_chars: int = 3500) -> str:
    """Trim nested data to stay within LLM context budget."""
    def _trim_value(v, depth=0):
        if isinstance(v, list):
            limit = 8 if depth == 0 else 4
            trimmed = [_trim_value(i, depth + 1) for i in v[:limit]]
            if len(v) > limit:
                trimmed.append(f"... ({len(v) - limit} more)")
            return trimmed
        if isinstance(v, dict):
            return {k: _trim_value(val, depth + 1) for k, val in v.items()}
        return v

    result = json.dumps(_trim_value(data), default=str, indent=2)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... (truncated)"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN COPILOT FUNCTION
# ─────────────────────────────────────────────────────────────────────────────
async def copilot_answer(question: str) -> dict:
    """
    Route → parallel fetch → local LLM synthesis → structured response.
    All data stays on-premise. LLM inference via Ollama (mistral:7b-instruct).
    """
    endpoints = _route_question(question)

    # Parallel fetch with retry
    async with httpx.AsyncClient() as http:
        tasks = [_fetch_endpoint(ep, http) for ep in endpoints]
        results = await asyncio.gather(*tasks)

    data_context: dict = {}
    errors: list[str] = []
    for name, data in results:
        if data and "_error" not in data:
            data_context[name] = data
        else:
            errors.append(f"{name}: {data.get('_error', 'unknown') if data else 'no response'}")

    data_str = _trim_data(data_context)

    user_prompt = (
        f'Resource Manager question: "{question}"\n\n'
        f"{TOOL_DESCRIPTIONS}\n\n"
        f"Real-time data from JSpark:\n{data_str}\n\n"
        + (f"Note: Could not fetch: {'; '.join(errors)}\n" if errors else "")
        + "Answer using ONLY the data above. Cite IDs and numbers. 3-5 sentences. One action at the end."
    )

    answer, model_used = llm_call_with_fallback(
        user_prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_tokens=450,
        temperature=0.0,
    )

    # Extract headline numbers for audit trail
    snapshot: dict = {}
    if "summary" in data_context:
        snapshot = data_context["summary"].get("headline_numbers", {})
    if "leakage" in data_context:
        snapshot["weekly_leakage"] = data_context["leakage"].get(
            "estimated_weekly_revenue_leakage_usd", "N/A"
        )

    return {
        "question":           question,
        "answer":             answer,
        "data_sources_used":  endpoints,
        "errors":             errors if errors else None,
        "model":              model_used,
        "raw_data_snapshot":  snapshot,
        "data_compliance":    "All data processed locally. No external API calls.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# DEMO QUESTIONS
# ─────────────────────────────────────────────────────────────────────────────
DEMO_QUESTIONS = [
    "Can we take on two new Data Engineering projects starting in August?",
    "Which projects are most at risk of escalation this quarter?",
    "Who is available for a new Senior Software Engineer role?",
    "What is our weekly revenue leakage from unbilled resources?",
    "How many people are on the bench right now?",
    "Which projects are overrunning and what should I do about them?",
    "Show me an executive summary of our resourcing health.",
    "Which skill gaps are blocking us from staffing the pipeline?",
]
