"""
retrieve.py — Recuperação híbrida sobre os três stores.

Modos:
  - search_evidence      : entrada semântica (vetor sobre trechos de evidência)
  - state_trajectory     : trajetória dimensional em ℳ (série temporal)
  - similar_states       : similaridade entre vetores dimensionais (interpretável)
  - graph_neighborhood   : travessia multi-hop no grafo GEM
  - friction_to_leverage : caminhos emergenáveis (.epe) atrito -> alavancagem
  - as_of_graph          : fotografia do grafo válida numa data (tempo de transação)
  - assemble_context     : compositor — junta os modos num bundle p/ o LLM

Sem chamadas de LLM no momento da query: tudo é busca local + álgebra de vetores.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Dict, List, Optional

import numpy as np

from . import db
from . import embeddings as emb
from .vectors import dimensions_to_vector


# ---- evidência (vetor) -------------------------------------------------------

def search_evidence(conn, patient_id: str, query: str, k: int = 6) -> List[Dict]:
    qv = emb.embed_one(query)
    name = emb.embedder_name()
    rows = conn.execute(
        "SELECT chunk_id, episode_id, text, embedding, provenance "
        "FROM evidence_chunks WHERE patient_id=? AND embedder=?",
        (patient_id, name),
    ).fetchall()
    scored = []
    for r in rows:
        score = emb.cosine(qv, emb.from_blob(r["embedding"]))
        scored.append((score, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    out = []
    for score, r in scored[:k]:
        out.append({
            "chunk_id": r["chunk_id"],
            "episode_id": r["episode_id"],
            "text": r["text"],
            "score": round(score, 4),
            "provenance": json.loads(r["provenance"] or "{}"),
        })
    return out


# ---- trajetória dimensional --------------------------------------------------

def state_trajectory(conn, patient_id: str, from_date: Optional[str] = None,
                     to_date: Optional[str] = None) -> List[Dict]:
    q = ("SELECT episode_id, session_date, dimensions, dominant_pattern "
         "FROM dimensional_states WHERE patient_id=?")
    args: list = [patient_id]
    if from_date:
        q += " AND session_date >= ?"; args.append(from_date)
    if to_date:
        q += " AND session_date <= ?"; args.append(to_date)
    q += " ORDER BY session_date ASC"
    rows = conn.execute(q, args).fetchall()
    return [{
        "episode_id": r["episode_id"],
        "session_date": r["session_date"],
        "dimensions": json.loads(r["dimensions"]),
        "dominant_pattern": r["dominant_pattern"],
    } for r in rows]


def dimension_series(conn, patient_id: str, dimension: str) -> List[Dict]:
    """Série temporal de UMA dimensão (ex.: 'v1_valencia_emocional')."""
    traj = state_trajectory(conn, patient_id)
    series = []
    for s in traj:
        val = s["dimensions"].get(dimension)
        if isinstance(val, dict):  # v5
            val = val
        series.append({"session_date": s["session_date"], "value": val})
    return series


def similar_states(conn, patient_id: str, ref_episode_id: str, k: int = 5) -> List[Dict]:
    """Sessões em configuração mental parecida (cosseno no vetor 17-D)."""
    ref = conn.execute(
        "SELECT vector FROM dimensional_states WHERE patient_id=? AND episode_id=?",
        (patient_id, ref_episode_id),
    ).fetchone()
    if not ref:
        return []
    rv = emb.from_blob(ref["vector"])
    rows = conn.execute(
        "SELECT episode_id, session_date, vector, dominant_pattern "
        "FROM dimensional_states WHERE patient_id=? AND episode_id != ?",
        (patient_id, ref_episode_id),
    ).fetchall()
    scored = [(emb.cosine(rv, emb.from_blob(r["vector"])), r) for r in rows]
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{
        "episode_id": r["episode_id"],
        "session_date": r["session_date"],
        "similarity": round(s, 4),
        "dominant_pattern": r["dominant_pattern"],
    } for s, r in scored[:k]]


# ---- grafo GEM ---------------------------------------------------------------

def graph_neighborhood(conn, patient_id: str, event_id: str, hops: int = 2) -> Dict:
    """Travessia multi-hop a partir de um evento (apenas arestas ativas)."""
    seen_events = {event_id}
    frontier = {event_id}
    edges_out = []
    for _ in range(max(1, hops)):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        rows = conn.execute(
            f"""SELECT edge_id, source_event_id, target_event_id, directionality,
                       causal_strength, influence_magnitude, semantic_similarity
                  FROM gem_edges
                 WHERE patient_id=? AND {db.active_filter()}
                   AND (source_event_id IN ({placeholders})
                        OR target_event_id IN ({placeholders}))""",
            (patient_id, *frontier, *frontier),
        ).fetchall()
        new_front = set()
        for r in rows:
            edges_out.append(dict(r))
            for nid in (r["source_event_id"], r["target_event_id"]):
                if nid not in seen_events:
                    new_front.add(nid); seen_events.add(nid)
        frontier = new_front
    nodes = _fetch_events(conn, patient_id, list(seen_events))
    # dedup arestas
    uniq = {e["edge_id"]: e for e in edges_out}
    return {"nodes": nodes, "edges": list(uniq.values())}


def _fetch_events(conn, patient_id, event_ids: List[str]) -> List[Dict]:
    if not event_ids:
        return []
    placeholders = ",".join("?" * len(event_ids))
    rows = conn.execute(
        f"""SELECT event_id, episode_id, literal_text, semantic_summary,
                   dimensional_properties
              FROM gem_events
             WHERE patient_id=? AND {db.active_filter()}
               AND event_id IN ({placeholders})""",
        (patient_id, *event_ids),
    ).fetchall()
    return [{
        "event_id": r["event_id"],
        "episode_id": r["episode_id"],
        "literal_text": r["literal_text"],
        "semantic_summary": r["semantic_summary"],
        "dimensional_properties": json.loads(r["dimensional_properties"] or "{}"),
    } for r in rows]


def friction_to_leverage(conn, patient_id: str) -> List[Dict]:
    """Caminhos emergenáveis (.epe) ativos: como o atrito vira alavancagem."""
    rows = conn.execute(
        f"""SELECT pathway_id, description, source_friction_clusters,
                   leverage_clusters, key_leverage_events, required_conditions,
                   emergenable_potential_score
              FROM gem_pathways
             WHERE patient_id=? AND {db.active_filter()}
             ORDER BY emergenable_potential_score DESC""",
        (patient_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "pathway_id": r["pathway_id"],
            "description": r["description"],
            "friction_clusters": json.loads(r["source_friction_clusters"] or "[]"),
            "leverage_clusters": json.loads(r["leverage_clusters"] or "[]"),
            "key_leverage_events": json.loads(r["key_leverage_events"] or "[]"),
            "required_conditions": r["required_conditions"],
            "emergenable_potential_score": r["emergenable_potential_score"],
        })
    return out


def active_clusters(conn, patient_id: str, role: Optional[str] = None) -> List[Dict]:
    q = (f"SELECT cluster_id, label, hitop_spectrum, cluster_role, "
         f"semantic_centrality, relational_density, valid_from "
         f"FROM gem_clusters WHERE patient_id=? AND {db.active_filter()}")
    args = [patient_id]
    if role:
        q += " AND cluster_role=?"; args.append(role)
    rows = conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def as_of_graph(conn, patient_id: str, asof_iso: str) -> Dict:
    """Fotografia 'as-of': clusters/flows/pathways ativos naquele tempo de transação."""
    params = {"pid": patient_id, "asof": asof_iso}

    def fetch(table, cols):
        return [dict(r) for r in conn.execute(
            f"SELECT {cols} FROM {table} WHERE patient_id=:pid AND {db.as_of_filter()}",
            params,
        ).fetchall()]

    return {
        "as_of": asof_iso,
        "clusters": fetch("gem_clusters", "cluster_id, label, cluster_role, hitop_spectrum"),
        "flows": fetch("gem_flows", "flow_id, description, causal_strength"),
        "pathways": fetch("gem_pathways", "pathway_id, description, emergenable_potential_score"),
    }


# ---- compositor de contexto --------------------------------------------------

def assemble_context(conn, patient_id: str, query: str,
                     k_evidence: int = 6, hops: int = 2) -> Dict:
    """
    Pipeline híbrido (padrão 2026): vetor acha a entrada -> grafo expande o
    contexto relacional -> trajetória dá a tendência. Retorna um bundle pronto
    para virar contexto do LLM.

    Artefatos derivados, summary-only e NÃO-autorizantes: este bundle é
    superfície de insight para o clínico, não conduta nem autorização.
    """
    evidence = search_evidence(conn, patient_id, query, k=k_evidence)

    # expande a partir dos eventos citados nas evidências (quando houver)
    seed_events = []
    for e in evidence:
        ev = e.get("provenance", {}).get("gem_event_id")
        if ev:
            seed_events.append(ev)

    neighborhood = {"nodes": [], "edges": []}
    if seed_events:
        merged_nodes, merged_edges = {}, {}
        for ev in seed_events[:3]:
            nb = graph_neighborhood(conn, patient_id, ev, hops=hops)
            for n in nb["nodes"]:
                merged_nodes[n["event_id"]] = n
            for ed in nb["edges"]:
                merged_edges[ed["edge_id"]] = ed
        neighborhood = {"nodes": list(merged_nodes.values()),
                        "edges": list(merged_edges.values())}

    traj = state_trajectory(conn, patient_id)
    latest = traj[-1] if traj else None

    return {
        "patient_id": patient_id,
        "query": query,
        "disclaimer": ("Artefatos derivados e summary-only; superfície de insight "
                       "clínico, não-autorizante."),
        "evidence": evidence,
        "graph_neighborhood": neighborhood,
        "emergenable_pathways": friction_to_leverage(conn, patient_id),
        "friction_clusters": active_clusters(conn, patient_id, role="friction"),
        "leverage_clusters": active_clusters(conn, patient_id, role="leverage"),
        "latest_state": latest,
        "trajectory_len": len(traj),
    }
