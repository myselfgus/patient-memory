"""
run_example.py — Demonstração ponta-a-ponta, OFFLINE (sem nenhuma chave de API).

Ingere duas sessões de exemplo e roda os modos de recuperação, mostrando:
  - trajetória dimensional em ℳ (melhora entre S1 e S2)
  - supersessão bi-temporal (o cluster C_LUTO_RUMINACAO e o pathway EPE_*
    superam a versão da sessão anterior; o histórico permanece consultável)
  - recuperação híbrida (evidência -> grafo -> caminhos emergenáveis)

Uso:
    cd healthos-patient-memory
    pip install -r requirements.txt        # só numpy é obrigatório p/ este demo
    python examples/run_example.py
"""

import json
import os
import sys
from pathlib import Path

# garante import do pacote a partir de src/ sem instalação
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("MEMORY_EMBEDDER", "offline")

from healthos_memory import db, ingest, retrieve  # noqa: E402

DB_PATH = ROOT / "examples" / "_demo_memory.db"
PATIENT = "PACIENTE_001"


def hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = db.connect(DB_PATH)

    hr("INGESTÃO")
    import time
    s1 = ingest.ingest_projection_file(conn, str(ROOT / "examples" / "sample_session1.json"))
    print(f"  sample_session1.json: {json.dumps(s1, ensure_ascii=False)}")
    time.sleep(0.02)
    t_after_s1 = db.now_iso()   # tempo de transação entre as duas sessões
    time.sleep(0.02)
    s2 = ingest.ingest_projection_file(conn, str(ROOT / "examples" / "sample_session2.json"))
    print(f"  sample_session2.json: {json.dumps(s2, ensure_ascii=False)}")

    hr("TRAJETÓRIA DIMENSIONAL EM ℳ (v1 valência, v9 agência, v5 futuro)")
    for s in retrieve.state_trajectory(conn, PATIENT):
        d = s["dimensions"]
        print(f"  {s['session_date']}  "
              f"v1={d['v1_valencia_emocional']:+.2f}  "
              f"v9={d['v9_senso_agencia']:.2f}  "
              f"futuro={d['v5_orientacao_temporal']['futuro']:.2f}  "
              f"| {s['dominant_pattern']}")

    hr("ESTADOS SIMILARES a S1 (cosseno no vetor 17-D interpretável)")
    for r in retrieve.similar_states(conn, PATIENT, "PACIENTE_001_S1"):
        print(f"  {r['episode_id']}  sim={r['similarity']:.3f}  | {r['dominant_pattern']}")

    hr("BUSCA DE EVIDÊNCIA: 'escrever cartas e dormir melhor'")
    for r in retrieve.search_evidence(conn, PATIENT, "escrever cartas e dormir melhor", k=3):
        print(f"  [{r['score']:.3f}] ({r['episode_id']}) {r['text']}")
        print(f"          provenance.gem_event_id = {r['provenance'].get('gem_event_id')}")

    hr("VIZINHANÇA NO GRAFO GEM a partir de E1_LUTO_DISCLOSURE (2 hops)")
    nb = retrieve.graph_neighborhood(conn, PATIENT, "E1_LUTO_DISCLOSURE", hops=2)
    print(f"  nós: {[n['event_id'] for n in nb['nodes']]}")
    for e in nb["edges"]:
        print(f"  {e['source_event_id']} --{e['directionality']}({e['causal_strength']})--> {e['target_event_id']}")

    hr("CLUSTERS ATIVOS (após supersessão bi-temporal)")
    print("  friction:", [c["cluster_id"] for c in retrieve.active_clusters(conn, PATIENT, role="friction")])
    print("  leverage:", [c["cluster_id"] for c in retrieve.active_clusters(conn, PATIENT, role="leverage")])

    hr("CAMINHOS EMERGENÁVEIS (.epe) — atrito -> alavancagem")
    for p in retrieve.friction_to_leverage(conn, PATIENT):
        print(f"  {p['pathway_id']} (pot={p['emergenable_potential_score']})")
        print(f"     atrito={p['friction_clusters']}  alavancagem={p['leverage_clusters']}")
        print(f"     {p['description']}")

    hr("FOTOGRAFIA AS-OF: como o grafo estava logo após a sessão 1")
    snap = retrieve.as_of_graph(conn, PATIENT, t_after_s1)
    for p in snap["pathways"]:
        print(f"  as-of {t_after_s1[:19]}: {p['pathway_id']} pot={p['emergenable_potential_score']}")
    print("  (a versão ATIVA atual do mesmo pathway tem pot=0.72 — o bi-temporal")
    print("   preserva as duas: a histórica e a vigente)")

    hr("CONTEXTO MONTADO PARA O LLM (compositor híbrido)")
    bundle = retrieve.assemble_context(conn, PATIENT, "como está o sono e a agência do paciente?")
    print(f"  evidências: {len(bundle['evidence'])}  | nós no grafo: {len(bundle['graph_neighborhood']['nodes'])}")
    print(f"  pathways: {[p['pathway_id'] for p in bundle['emergenable_pathways']]}")
    print(f"  estado mais recente: {bundle['latest_state']['session_date']} "
          f"({bundle['latest_state']['dominant_pattern']})")
    print(f"  disclaimer: {bundle['disclaimer']}")

    conn.close()
    print("\nOK — pipeline ponta-a-ponta funcionou (offline).")


if __name__ == "__main__":
    main()
