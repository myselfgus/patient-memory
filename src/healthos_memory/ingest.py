"""
ingest.py — Grava um JSON de projeção (saída do prompt project_to_memory) nos
três stores. Idempotência e historicidade são garantidas pela espinha
bi-temporal: clusters/flows/pathways com mesmo id lógico superam a versão
anterior (expired_at) em vez de sobrescrever.

Entrada: objeto conforme schemas/memory_projection.schema.json.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Dict, List

from . import db
from . import embeddings as emb
from .vectors import dimensions_to_vector

_SCHEMA_PATH = __import__("pathlib").Path(__file__).resolve().parents[2] / "schemas" / "memory_projection.schema.json"


def validate_projection(projection: Dict) -> list:
    """Valida contra o schema se jsonschema estiver instalado. Retorna lista de
    erros (vazia = ok). Se jsonschema não estiver disponível, retorna [] (no-op)."""
    try:
        import json as _json
        from jsonschema import Draft202012Validator
    except ImportError:
        return []
    schema = _json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    v = Draft202012Validator(schema)
    return [f"{list(e.path)}: {e.message}" for e in v.iter_errors(projection)]


def ingest_projection(conn: sqlite3.Connection, projection: Dict, validate: bool = True) -> Dict:
    """Ingere uma projeção de sessão. Retorna um resumo do que foi gravado."""
    if validate:
        errors = validate_projection(projection)
        if errors:
            raise ValueError("Projeção inválida:\n  - " + "\n  - ".join(errors[:10]))
    patient_id = projection["patient_id"]
    episode = projection["episode"]
    episode_id = episode["episode_id"]
    recorded_at = db.now_iso()

    summary = {"patient_id": patient_id, "episode_id": episode_id}

    _write_episode(conn, patient_id, episode, recorded_at)
    summary["evidence_chunks"] = _write_evidence(
        conn, patient_id, episode_id, projection.get("evidence_chunks", []), recorded_at
    )
    summary["dimensional_state"] = _write_state(
        conn, patient_id, episode_id, projection.get("dimensional_state"), recorded_at
    )
    gem = projection.get("gem", {}) or {}
    summary["gem"] = _write_gem(conn, patient_id, episode_id, gem, recorded_at)

    conn.commit()
    return summary


def ingest_projection_file(conn: sqlite3.Connection, path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return ingest_projection(conn, json.load(f))


# ---- writers -----------------------------------------------------------------

def _write_episode(conn, patient_id, episode, recorded_at):
    conn.execute(
        """INSERT OR REPLACE INTO episodes
           (episode_id, patient_id, session_id, session_date, transcript_ref,
            synthesis_text, source_refs, recorded_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            episode["episode_id"],
            patient_id,
            episode.get("session_id"),
            episode.get("session_date"),
            episode.get("transcript_ref"),
            episode.get("synthesis_text"),
            json.dumps(episode.get("source_refs", {}), ensure_ascii=False),
            recorded_at,
        ),
    )


def _write_evidence(conn, patient_id, episode_id, chunks: List[Dict], recorded_at) -> int:
    if not chunks:
        return 0
    texts = [c["text"] for c in chunks]
    vectors = emb.embed(texts)
    name = emb.embedder_name()
    for c, vec in zip(chunks, vectors):
        conn.execute(
            """INSERT OR REPLACE INTO evidence_chunks
               (chunk_id, patient_id, episode_id, text, embedding, embedder, dim,
                provenance, recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                c["chunk_id"],
                patient_id,
                episode_id,
                c["text"],
                emb.to_blob(vec),
                name,
                int(vec.size),
                json.dumps(c.get("provenance", {}), ensure_ascii=False),
                recorded_at,
            ),
        )
    return len(chunks)


def _write_state(conn, patient_id, episode_id, state: Dict, recorded_at) -> bool:
    if not state:
        return False
    dimensions = state["dimensions"]
    vec = dimensions_to_vector(dimensions)
    conn.execute(
        """INSERT OR REPLACE INTO dimensional_states
           (state_id, patient_id, episode_id, session_date, dimensions, vector,
            dominant_pattern, recorded_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            state.get("state_id", f"{episode_id}_STATE"),
            patient_id,
            episode_id,
            state.get("session_date"),
            json.dumps(dimensions, ensure_ascii=False),
            emb.to_blob(vec),
            state.get("dominant_pattern"),
            recorded_at,
        ),
    )
    return True


def _write_gem(conn, patient_id, episode_id, gem: Dict, recorded_at) -> Dict:
    counts = {}

    # eventos (.aje) — append-only, escopo de sessão
    events = gem.get("events", [])
    for e in events:
        conn.execute(
            """INSERT INTO gem_events
               (event_id, patient_id, episode_id, literal_text, semantic_summary,
                dimensional_properties, paralinguistic, valid_from, valid_to,
                recorded_at, expired_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                e["event_id"], patient_id, episode_id,
                e.get("literal_text"), e.get("semantic_summary"),
                json.dumps(e.get("dimensional_properties", {}), ensure_ascii=False),
                json.dumps(e.get("paralinguistic_context", {}), ensure_ascii=False),
                e.get("valid_from"), e.get("valid_to"), recorded_at,
            ),
        )
    counts["events"] = len(events)

    # arestas (.aje relational_vectors) — append-only, escopo de sessão
    edges = gem.get("edges", [])
    for ed in edges:
        conn.execute(
            """INSERT INTO gem_edges
               (edge_id, patient_id, source_event_id, target_event_id, directionality,
                influence_magnitude, causal_strength, semantic_similarity, temporal_lag,
                valid_from, valid_to, recorded_at, expired_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                ed["edge_id"], patient_id, ed["source_event_id"], ed["target_event_id"],
                ed.get("directionality"), ed.get("influence_magnitude"),
                ed.get("causal_strength"), ed.get("semantic_similarity"),
                ed.get("temporal_lag"), ed.get("valid_from"), ed.get("valid_to"),
                recorded_at,
            ),
        )
    counts["edges"] = len(edges)

    # clusters (.ire), flows (.e), pathways (.epe) — persistentes, bi-temporais
    counts["clusters"] = _write_bitemporal_clusters(
        conn, patient_id, gem.get("clusters", []), recorded_at
    )
    counts["flows"] = _write_bitemporal_flows(
        conn, patient_id, gem.get("flows", []), recorded_at
    )
    counts["pathways"] = _write_bitemporal_pathways(
        conn, patient_id, gem.get("pathways", []), recorded_at
    )
    return counts


def _write_bitemporal_clusters(conn, patient_id, clusters: List[Dict], recorded_at) -> int:
    for c in clusters:
        db.supersede_open_row(conn, "gem_clusters", "cluster_id", c["cluster_id"],
                              patient_id, recorded_at)
        conn.execute(
            """INSERT INTO gem_clusters
               (cluster_id, patient_id, label, event_ids, hitop_spectrum,
                semantic_centrality, relational_density, novelty_score, cluster_role,
                valid_from, valid_to, recorded_at, expired_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                c["cluster_id"], patient_id, c.get("label"),
                json.dumps(c.get("event_ids", []), ensure_ascii=False),
                c.get("hitop_spectrum"), c.get("semantic_centrality"),
                c.get("relational_density"), c.get("novelty_score"),
                c.get("cluster_role", "neutral"),
                c.get("valid_from"), c.get("valid_to"), recorded_at,
            ),
        )
    return len(clusters)


def _write_bitemporal_flows(conn, patient_id, flows: List[Dict], recorded_at) -> int:
    for f in flows:
        db.supersede_open_row(conn, "gem_flows", "flow_id", f["flow_id"],
                              patient_id, recorded_at)
        conn.execute(
            """INSERT INTO gem_flows
               (flow_id, patient_id, description, source_events, target_clusters,
                causal_strength, directionality, mapped_dimensions, kind,
                valid_from, valid_to, recorded_at, expired_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                f["flow_id"], patient_id, f.get("description"),
                json.dumps(f.get("source_events", []), ensure_ascii=False),
                json.dumps(f.get("target_clusters", []), ensure_ascii=False),
                f.get("causal_strength"), f.get("directionality"),
                json.dumps(f.get("mapped_dimensions", {}), ensure_ascii=False),
                f.get("kind", "diagnostic"),
                f.get("valid_from"), f.get("valid_to"), recorded_at,
            ),
        )
    return len(flows)


def _write_bitemporal_pathways(conn, patient_id, pathways: List[Dict], recorded_at) -> int:
    for p in pathways:
        db.supersede_open_row(conn, "gem_pathways", "pathway_id", p["pathway_id"],
                              patient_id, recorded_at)
        conn.execute(
            """INSERT INTO gem_pathways
               (pathway_id, patient_id, description, source_friction_clusters,
                leverage_clusters, key_leverage_events, required_conditions,
                emergenable_potential_score, kind, valid_from, valid_to,
                recorded_at, expired_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                p["pathway_id"], patient_id, p.get("description"),
                json.dumps(p.get("source_friction_clusters", []), ensure_ascii=False),
                json.dumps(p.get("leverage_clusters", []), ensure_ascii=False),
                json.dumps(p.get("key_leverage_events", []), ensure_ascii=False),
                p.get("required_conditions"), p.get("emergenable_potential_score"),
                p.get("kind", "prognostic"),
                p.get("valid_from"), p.get("valid_to"), recorded_at,
            ),
        )
    return len(pathways)
