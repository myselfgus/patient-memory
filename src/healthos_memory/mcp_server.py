"""
mcp_server.py — Servidor MCP (stdio) que expõe a memória do paciente como
ferramentas para um agente LLM (Claude Code, Claude Desktop, Cursor, etc.).

Execução:
    MEMORY_DB=/caminho/memory.db python -m healthos_memory.mcp_server

Requer o pacote `mcp`:
    pip install "mcp[cli]"

Todas as ferramentas são read-only (readOnlyHint=True). A ingestão é feita fora
do agente, pelo pipeline de projeção/ingestão.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "Pacote 'mcp' não encontrado. Instale com: pip install \"mcp[cli]\""
    ) from e

from . import db
from . import retrieve

DB_PATH = os.environ.get("MEMORY_DB", "memory.db")
_conn = db.connect(DB_PATH)

mcp = FastMCP("patient_memory_mcp")


class PatientQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    patient_id: str = Field(..., description="ID do paciente (namespace da memória).", min_length=1)
    query: str = Field(..., description="Pergunta clínica em linguagem natural.", min_length=1)
    k_evidence: int = Field(6, description="Nº de trechos de evidência a recuperar.", ge=1, le=20)
    hops: int = Field(2, description="Saltos de travessia no grafo GEM.", ge=1, le=4)


class PatientId(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    patient_id: str = Field(..., description="ID do paciente.", min_length=1)


class EvidenceSearch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    patient_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    k: int = Field(6, ge=1, le=20)


class EventQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    patient_id: str = Field(..., min_length=1)
    event_id: str = Field(..., description="ID do evento .aje semente.", min_length=1)
    hops: int = Field(2, ge=1, le=4)


class AsOfQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    patient_id: str = Field(..., min_length=1)
    asof_iso: str = Field(..., description="Data/hora ISO-8601 da fotografia.", min_length=4)


_RO = {"title": "", "readOnlyHint": True, "destructiveHint": False,
       "idempotentHint": True, "openWorldHint": False}


@mcp.tool(name="memory_assemble_context", annotations={**_RO, "title": "Montar contexto do paciente"})
async def memory_assemble_context(params: PatientQuery) -> str:
    """Compositor híbrido: evidência + vizinhança no grafo + caminhos emergenáveis
    + estado dimensional mais recente. Retorna JSON pronto para virar contexto do
    LLM. Artefatos derivados, summary-only e não-autorizantes."""
    bundle = retrieve.assemble_context(
        _conn, params.patient_id, params.query,
        k_evidence=params.k_evidence, hops=params.hops,
    )
    return json.dumps(bundle, ensure_ascii=False, indent=2)


@mcp.tool(name="memory_search_evidence", annotations={**_RO, "title": "Buscar evidência"})
async def memory_search_evidence(params: EvidenceSearch) -> str:
    """Busca semântica nos trechos de evidência (citações literais com proveniência)."""
    res = retrieve.search_evidence(_conn, params.patient_id, params.query, k=params.k)
    return json.dumps(res, ensure_ascii=False, indent=2)


@mcp.tool(name="memory_state_trajectory", annotations={**_RO, "title": "Trajetória dimensional ℳ"})
async def memory_state_trajectory(params: PatientId) -> str:
    """Trajetória do estado mental no Espaço ℳ ao longo das sessões (série temporal)."""
    res = retrieve.state_trajectory(_conn, params.patient_id)
    return json.dumps(res, ensure_ascii=False, indent=2)


@mcp.tool(name="memory_graph_neighborhood", annotations={**_RO, "title": "Vizinhança no grafo GEM"})
async def memory_graph_neighborhood(params: EventQuery) -> str:
    """Travessia multi-hop no grafo causal GEM a partir de um evento .aje."""
    res = retrieve.graph_neighborhood(_conn, params.patient_id, params.event_id, hops=params.hops)
    return json.dumps(res, ensure_ascii=False, indent=2)


@mcp.tool(name="memory_emergenable_pathways", annotations={**_RO, "title": "Caminhos emergenáveis (.epe)"})
async def memory_emergenable_pathways(params: PatientId) -> str:
    """Caminhos emergenáveis ativos: como a energia do atrito pode virar alavancagem
    (prognóstico/potência). Não-autorizante."""
    res = retrieve.friction_to_leverage(_conn, params.patient_id)
    return json.dumps(res, ensure_ascii=False, indent=2)


@mcp.tool(name="memory_as_of", annotations={**_RO, "title": "Fotografia as-of do grafo"})
async def memory_as_of(params: AsOfQuery) -> str:
    """Estado do grafo (clusters/flows/pathways) válido numa data — raciocínio
    temporal bi-temporal ('como estava em março?')."""
    res = retrieve.as_of_graph(_conn, params.patient_id, params.asof_iso)
    return json.dumps(res, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
