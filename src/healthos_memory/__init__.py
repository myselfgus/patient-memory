"""
HealthOS Patient Memory — memória/RAG por paciente para um agente LLM.

Três stores coordenados (episódio/evidência, estado dimensional ℳ, grafo mental
GEM bi-temporal) sobre um único SQLite, com recuperação híbrida.

Uso típico:

    from healthos_memory import db, ingest, retrieve

    conn = db.connect("memory.db")
    ingest.ingest_projection_file(conn, "sessao_projetada.json")
    bundle = retrieve.assemble_context(conn, "PACIENTE_001", "como está o sono?")
"""

from . import db, ingest, retrieve, vectors, embeddings, constants  # noqa: F401

__all__ = ["db", "ingest", "retrieve", "vectors", "embeddings", "constants"]
__version__ = "0.1.0"
