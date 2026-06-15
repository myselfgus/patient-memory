"""
db.py — Backing store único (SQLite) para os três stores coordenados da memória
do paciente:

  1. Store episódico/evidência   -> tabelas `episodes`, `evidence_chunks`
  2. Store de estado dimensional -> tabela  `dimensional_states`   (trajetória em ℳ)
  3. Grafo mental GEM            -> tabelas `gem_events`, `gem_edges`,
                                    `gem_clusters`, `gem_flows`, `gem_pathways`

Espinha bi-temporal:
  - valid_from / valid_to   = tempo de validade (verdadeiro no mundo do paciente)
  - recorded_at / expired_at = tempo de transação (quando o sistema soube)
Fatos superados são INVALIDADOS (expired_at preenchido), nunca deletados.

Tudo é namespaced por `patient_id` — sem vazamento de memória entre pacientes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id    TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL,
    session_id    TEXT,
    session_date  TEXT,                 -- ISO-8601 (valid time da sessão)
    transcript_ref TEXT,                -- ponteiro p/ transcrição bruta (path/uri/id)
    synthesis_text TEXT,                -- sintese_interpretativa distilada
    source_refs   TEXT,                 -- JSON: {asl, vdlp, gem} refs de origem
    recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_episodes_patient ON episodes(patient_id, session_date);

CREATE TABLE IF NOT EXISTS evidence_chunks (
    chunk_id      TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL,
    episode_id    TEXT NOT NULL,
    text          TEXT NOT NULL,        -- citação literal / trecho de evidência
    embedding     BLOB,                 -- float32 little-endian
    embedder      TEXT,                 -- nome do embedder (p/ comparar só compatíveis)
    dim           INTEGER,
    provenance    TEXT,                 -- JSON: de onde veio (asl path, gem event_id, etc.)
    recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_patient ON evidence_chunks(patient_id);

CREATE TABLE IF NOT EXISTS dimensional_states (
    state_id      TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL,
    episode_id    TEXT NOT NULL,
    session_date  TEXT,                 -- ISO-8601
    dimensions    TEXT NOT NULL,        -- JSON: dict nomeado v1..v15 (forma rica)
    vector        BLOB NOT NULL,        -- float32 17-D (forma de similaridade)
    dominant_pattern TEXT,              -- padrao_dimensional_dominante (texto curto)
    recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_states_patient ON dimensional_states(patient_id, session_date);

-- ---- GEM: grafo mental bi-temporal -------------------------------------------

CREATE TABLE IF NOT EXISTS gem_events (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      TEXT NOT NULL,        -- id lógico do evento (.aje)
    patient_id    TEXT NOT NULL,
    episode_id    TEXT NOT NULL,
    literal_text  TEXT,
    semantic_summary TEXT,
    dimensional_properties TEXT,        -- JSON
    paralinguistic TEXT,                -- JSON
    valid_from    TEXT,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    expired_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_patient ON gem_events(patient_id, event_id);

CREATE TABLE IF NOT EXISTS gem_edges (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id       TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    directionality TEXT,                -- causal|correlational|bidirectional|inhibitory
    influence_magnitude REAL,
    causal_strength REAL,
    semantic_similarity REAL,
    temporal_lag  INTEGER,
    valid_from    TEXT,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    expired_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_edges_patient ON gem_edges(patient_id, source_event_id);

CREATE TABLE IF NOT EXISTS gem_clusters (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id    TEXT NOT NULL,        -- id lógico persistente entre sessões
    patient_id    TEXT NOT NULL,
    label         TEXT,
    event_ids     TEXT,                 -- JSON array
    hitop_spectrum TEXT,
    semantic_centrality REAL,
    relational_density REAL,
    novelty_score REAL,
    cluster_role  TEXT,                 -- friction|leverage|neutral
    valid_from    TEXT,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    expired_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_clusters_patient ON gem_clusters(patient_id, cluster_id);

CREATE TABLE IF NOT EXISTS gem_flows (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_id       TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    description   TEXT,
    source_events TEXT,                 -- JSON array
    target_clusters TEXT,               -- JSON array
    causal_strength REAL,
    directionality TEXT,
    mapped_dimensions TEXT,             -- JSON
    kind          TEXT,                 -- diagnostic
    valid_from    TEXT,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    expired_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_flows_patient ON gem_flows(patient_id, flow_id);

CREATE TABLE IF NOT EXISTS gem_pathways (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    pathway_id    TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    description   TEXT,
    source_friction_clusters TEXT,      -- JSON array
    leverage_clusters TEXT,             -- JSON array
    key_leverage_events TEXT,           -- JSON array
    required_conditions TEXT,
    emergenable_potential_score REAL,
    kind          TEXT,                 -- prognostic
    valid_from    TEXT,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    expired_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_pathways_patient ON gem_pathways(patient_id, pathway_id);
"""

# Tabelas bi-temporais cujas entidades persistem/superam entre sessões,
# com a coluna que serve de chave lógica de identidade.
BITEMPORAL_LOGICAL_KEY = {
    "gem_clusters": "cluster_id",
    "gem_flows": "flow_id",
    "gem_pathways": "pathway_id",
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Abre (e inicializa) o banco. Cria diretório-pai se necessário."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def supersede_open_row(
    conn: sqlite3.Connection,
    table: str,
    logical_key_col: str,
    logical_key_val: str,
    patient_id: str,
    when: Optional[str] = None,
) -> None:
    """
    Fecha (invalida) a versão ativa anterior de uma entidade lógica, marcando
    expired_at (tempo de transação). Não deleta — preserva histórico.
    Use antes de inserir a nova versão.
    """
    when = when or now_iso()
    conn.execute(
        f"""
        UPDATE {table}
           SET expired_at = ?
         WHERE {logical_key_col} = ?
           AND patient_id = ?
           AND expired_at IS NULL
        """,
        (when, logical_key_val, patient_id),
    )


def active_filter(alias: str = "") -> str:
    """Cláusula SQL p/ filtrar apenas linhas ativas (não superadas)."""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}expired_at IS NULL"


def as_of_filter(alias: str = "") -> str:
    """
    Cláusula p/ consulta 'as-of' por tempo de transação: linha estava ativa em :asof
    (recorded_at <= :asof AND (expired_at IS NULL OR expired_at > :asof)).
    Espera bind params nomeados :asof.
    """
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}recorded_at <= :asof "
        f"AND ({prefix}expired_at IS NULL OR {prefix}expired_at > :asof)"
    )
