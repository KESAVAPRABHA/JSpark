"""
local_llm.py — JSpark Local LLM Wrapper
========================================
DATA COMPLIANCE RATIONALE:
  JMAN Group is extremely strict about customer data leaving the network.
  Employee IDs, skill profiles, competency scores, project names, allocation
  details, and WSR statuses are all confidential client/HR data.

  The previous implementation sent this data to:
    - Google Gemini API (gemini-2.5-flash-lite) → Google Cloud servers
    - Groq API (llama-3.3-70b-versatile)       → Groq cloud servers

  This file replaces BOTH with Ollama running locally on the dev machine.
  Zero data leaves the network. Zero API keys needed. Runs on RTX 3070 (8GB VRAM).

SETUP (one-time, ~5 minutes):
  1. Install Ollama:   https://ollama.com/download  (Windows/macOS/Linux)
  2. Pull LLM model:   ollama pull mistral:7b-instruct
  3. Pull embed model: ollama pull nomic-embed-text
  4. Confirm running:  ollama list
     Should show: mistral:7b-instruct, nomic-embed-text

  VRAM usage on RTX 3070 (8GB):
    mistral:7b-instruct (Q4_K_M) = 4.1 GB  ← LLM inference
    nomic-embed-text              = 0.27 GB ← document embedding
    Total                         = ~4.4 GB  ← well within 8GB

ENV VARIABLES:
  OLLAMA_BASE_URL  = http://localhost:11434  (default)
  OLLAMA_LLM_MODEL = mistral:7b-instruct     (default)
  OLLAMA_EMBED_MODEL = nomic-embed-text      (default)

  No GOOGLE_API_KEY, GROQ_API_KEY, or any external API key needed.

FALLBACK CHAIN (if Ollama is unavailable):
  → Groq (if GROQ_API_KEY is set) → Gemini (if GOOGLE_API_KEY is set) → Error message
  Fallbacks should ONLY be used during development, never with production data.
"""
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
import os
import json
import re
import requests
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL   = os.environ.get("OLLAMA_BASE_URL",    "http://localhost:11434")
OLLAMA_LLM_MODEL  = os.environ.get("OLLAMA_LLM_MODEL",   "mistral:7b-instruct")
OLLAMA_EMBED_MODEL= os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Timeouts (local inference is slower than cloud APIs on first token)
LLM_TIMEOUT_SECS   = 90    # mistral 7B generates ~30 tok/sec on RTX 3070
EMBED_TIMEOUT_SECS = 30

# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK — call at startup to detect misconfiguration early
# ─────────────────────────────────────────────────────────────────────────────
def check_ollama_health() -> dict:
    """
    Returns:
        { "available": bool, "models": list[str], "llm_ready": bool, "embed_ready": bool }
    """
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        llm_name   = OLLAMA_LLM_MODEL.split(":")[0]
        embed_name = OLLAMA_EMBED_MODEL.split(":")[0]
        return {
            "available":   True,
            "models":      models,
            "llm_ready":   any(llm_name in m for m in models),
            "embed_ready": any(embed_name in m for m in models),
            "llm_model":   OLLAMA_LLM_MODEL,
            "embed_model": OLLAMA_EMBED_MODEL,
        }
    except Exception as exc:
        return {
            "available":   False,
            "error":       str(exc),
            "hint":        "Install Ollama from https://ollama.com, then run: ollama pull mistral:7b-instruct",
            "llm_ready":   False,
            "embed_ready": False,
        }


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL LLM CALL — Ollama /api/chat (non-streaming)
# ─────────────────────────────────────────────────────────────────────────────
def llm_call(
    user_prompt: str,
    system_prompt: str = "",
    max_tokens: int = 600,
    temperature: float = 0.0,
    expect_json: bool = False,
) -> str:
    """
    Send a prompt to the local Ollama LLM and return the response text.

    Args:
        user_prompt:   The main prompt text.
        system_prompt: Optional system/instruction prefix.
        max_tokens:    Max tokens to generate (keep low for speed).
        temperature:   0.0 for deterministic output (recommended for structured tasks).
        expect_json:   If True, appends a JSON reminder to the prompt and tries to
                       extract valid JSON from the response.

    Returns:
        The response string (or JSON string if expect_json=True and parse succeeded).

    Raises:
        RuntimeError: If Ollama is not reachable or the request fails.
    """
    if expect_json:
        user_prompt += "\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown fences, no preamble."

    payload = {
        "model":  OLLAMA_LLM_MODEL,
        "stream": False,
        "options": {
            "temperature":   temperature,
            "num_predict":   max_tokens,
            "stop":          [],
        },
        "messages": [],
    }
    if system_prompt:
        payload["messages"].append({"role": "system", "content": system_prompt})
    payload["messages"].append({"role": "user", "content": user_prompt})

    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=LLM_TIMEOUT_SECS,
        )
        r.raise_for_status()
        content = r.json()["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Ollama is not running. Start it with: ollama serve\n"
            "If Ollama is not installed: https://ollama.com/download"
        )
    except Exception as exc:
        raise RuntimeError(f"Ollama LLM call failed: {exc}")

    if expect_json:
        # Strip markdown fences if model ignored the instruction
        clean = re.sub(r"```(?:json)?|```", "", content).strip()
        # Validate JSON — return raw string if parse fails (caller handles it)
        try:
            json.loads(clean)
            return clean
        except json.JSONDecodeError:
            return content   # Return raw; caller uses .get() with default

    return content


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL EMBEDDING — Ollama /api/embeddings
# ─────────────────────────────────────────────────────────────────────────────
def embed_text(text: str) -> list[float]:
    """
    Generate a local embedding vector for the given text using nomic-embed-text.
    """
    clean_text = str(text).strip() if text else ""
    if not clean_text:
        return [0.0] * 768

    # FIX: Ollama defaults to a 2048 token limit for nomic-embed-text.
    # 4,000 characters (~1,000 words) guarantees we will never crash the local LLM.
    if len(clean_text) > 4000:
        clean_text = clean_text[:4000]

    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={
                "model": OLLAMA_EMBED_MODEL, 
                "prompt": clean_text
            },
            timeout=EMBED_TIMEOUT_SECS,
        )
        
        if r.status_code != 200:
            print(f"\n🚨 OLLAMA CRASHED ON THIS TEXT:")
            print(f"   Error: {r.text}")
            print(f"   🔍 SEARCH YOUR CSV FOR THIS EXACT STRING TO FIND THE EMPLOYEE:")
            print(f"   {clean_text[:150]}\n")
            
        r.raise_for_status()
        return r.json()["embedding"]
        
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Ollama is not running. Start with: ollama serve")
    except Exception as exc:
        raise RuntimeError(f"Ollama embed call failed: {exc}")
    
def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts. Ollama doesn't natively batch embed so we loop,
    but it's fast enough for our 289-employee dataset (<30 seconds on RTX 3070).
    """
    return [embed_text(t) for t in texts]


# ─────────────────────────────────────────────────────────────────────────────
# CHROMADB EMBEDDING FUNCTION — plug into collection creation
# ─────────────────────────────────────────────────────────────────────────────
class OllamaEmbeddingFunction:
    """
    Custom ChromaDB embedding function that routes to local Ollama.

    Usage:
        from local_llm import OllamaEmbeddingFunction
        from chromadb import PersistentClient

        ef = OllamaEmbeddingFunction()
        client = PersistentClient(path="./chroma_db")
        collection = client.get_or_create_collection(
            name="employee_skills",
            metadata={"hnsw:space": "cosine"},
            embedding_function=ef,
        )
    """

    def __call__(self, input: list[str]) -> list[list[float]]:
        """ChromaDB calls this with a list of strings; return list of embedding vectors."""
        return embed_batch(input)

    def name(self) -> str:
        return "ollama_embedding"

# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK — allows graceful degradation during development (NOT for production)
# ─────────────────────────────────────────────────────────────────────────────
def llm_call_with_fallback(
    user_prompt: str,
    system_prompt: str = "",
    max_tokens: int = 600,
    temperature: float = 0.0,
    expect_json: bool = False,
) -> tuple[str, str]:
    """
    Try Ollama → Groq → Gemini in order. Return (response_text, model_used).

    IMPORTANT: Only Ollama is compliant for production use with customer data.
    Groq and Gemini fallbacks should be disabled in production via env var:
        DISABLE_CLOUD_LLM_FALLBACK=true
    """
    disable_cloud = os.environ.get("DISABLE_CLOUD_LLM_FALLBACK", "").lower() in ("1", "true", "yes")

    # ── 1. Try local Ollama (always first, always compliant) ─────────────
    try:
        resp = llm_call(user_prompt, system_prompt, max_tokens, temperature, expect_json)
        return resp, f"ollama/{OLLAMA_LLM_MODEL} (local, compliant)"
    except RuntimeError as ollama_err:
        if disable_cloud:
            raise RuntimeError(
                f"Ollama unavailable and cloud fallback is disabled (DISABLE_CLOUD_LLM_FALLBACK=true). "
                f"Ollama error: {ollama_err}"
            )
        print(f"  ⚠️  Ollama unavailable ({ollama_err}). Falling back to cloud LLM.")
        print("  ⚠️  DATA COMPLIANCE WARNING: Customer data may be sent to external servers.")

    # ── 2. Groq fallback (development only) ──────────────────────────────
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return r.choices[0].message.content.strip(), "groq/llama-3.3-70b (CLOUD ⚠️)"
        except Exception as exc:
            print(f"  ⚠️  Groq fallback failed: {exc}")

    # ── 3. Gemini fallback (development only) ────────────────────────────
    gemini_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_core.messages import HumanMessage, SystemMessage
            llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=temperature)
            msgs = []
            if system_prompt:
                msgs.append(SystemMessage(content=system_prompt))
            msgs.append(HumanMessage(content=user_prompt))
            resp = llm.invoke(msgs)
            return resp.content.strip(), "gemini/2.5-flash-lite (CLOUD ⚠️)"
        except Exception as exc:
            print(f"  ⚠️  Gemini fallback failed: {exc}")

    return (
        "No LLM available. Start Ollama (ollama serve) or set GROQ_API_KEY / GOOGLE_API_KEY.",
        "none",
    )
