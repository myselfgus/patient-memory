"""
project.py — (Opcional) Projeta os três JSONs canônicos (ASL + VDLP + GEM) numa
projeção de memória, chamando um LLM com o prompt prompts/project_to_memory.md.

Requer OPENAI_API_KEY (ou adapte _call_llm para outro provedor). Se você já gera
a projeção por outro caminho (ex.: dentro do HealthOS), pule este módulo e use
ingest.ingest_projection diretamente.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Dict, Optional

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "project_to_memory.md"


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_user_message(patient_id: str, session_id: str, session_date: str,
                       asl: Dict, vdlp: Dict, gem: Dict,
                       transcript_ref: Optional[str] = None) -> str:
    payload = {
        "patient_id": patient_id,
        "session_id": session_id,
        "session_date": session_date,
        "transcript_ref": transcript_ref,
        "asl": asl,
        "vdlp": vdlp,
        "gem": gem,
    }
    return json.dumps(payload, ensure_ascii=False)


def _call_llm(system_prompt: str, user_message: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não definida — necessária para project.py.")
    model = os.environ.get("MEMORY_PROJECTION_MODEL", "gpt-4o-mini")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def project(patient_id: str, session_id: str, session_date: str,
            asl: Dict, vdlp: Dict, gem: Dict,
            transcript_ref: Optional[str] = None) -> Dict:
    """Retorna a projeção (dict) pronta para ingest.ingest_projection."""
    system_prompt = load_prompt()
    user_message = build_user_message(
        patient_id, session_id, session_date, asl, vdlp, gem, transcript_ref
    )
    raw = _call_llm(system_prompt, user_message)
    return json.loads(raw)
