# CLAUDE.md

Guia para agentes (Claude Code / Cowork) trabalharem neste repositório. Leia antes
de qualquer mudança. Mantenha edições **mínimas, precisas e baseadas no uso real**
do repo; em caso de dúvida, prefira um TODO curto a inventar comportamento.

---

## O que é este projeto

`patient-memory` (pacote `healthos_memory`) é a **memória/RAG por paciente** do
HealthOS para um agente LLM. Ele distila as três camadas do HealthOS — **ASL**
(linguística), **VDLP** (estado dimensional em 15 vetores) e **GEM** (grafo mental
bi-temporal) — em **três stores coordenados** sobre um único SQLite, com recuperação
híbrida (vetor → grafo → trajetória).

Tese central: as três camadas **não** são a mesma coisa armazenada do mesmo jeito.
Episódio/evidência é documento+vetor; estado dimensional ℳ é um vetor interpretável;
GEM é grafo causal. A memória respeita as três formas em vez de achatar tudo num
único índice vetorial. **Não reverta essa separação por estética.**

---

## Mapa do código

| Caminho | Papel |
|---|---|
| `src/healthos_memory/constants.py` | Ordem canônica do vetor dimensional **17-D** (contrato — não reordenar sem migrar vetores). |
| `src/healthos_memory/db.py` | SQLite: schema dos 3 stores + helpers **bi-temporais**. |
| `src/healthos_memory/embeddings.py` | Embedder plugável: `offline` (determinístico, sem chave) ou `openai`. |
| `src/healthos_memory/vectors.py` | Dimensões nomeadas v1..v15 → vetor 17-D (v5 vira 3 componentes baricêntricos). |
| `src/healthos_memory/ingest.py` | Projeção JSON → stores, com validação de schema e **upsert bi-temporal**. |
| `src/healthos_memory/retrieve.py` | Recuperação híbrida + `assemble_context` (compositor do bundle). |
| `src/healthos_memory/project.py` | (Opcional) chama o LLM com o prompt de projeção. |
| `src/healthos_memory/mcp_server.py` | Servidor MCP (stdio) read-only com as ferramentas de memória. |
| `schemas/memory_projection.schema.json` | Contrato de entrada da ingestão (saída do prompt de projeção). |
| `prompts/project_to_memory.md` | Prompt ASL+VDLP+GEM → registros de memória. |
| `examples/run_example.py` | Demo offline ponta-a-ponta (não requer chave). |

---

## Comandos

```bash
# Ambiente (numpy é o único obrigatório; jsonschema é recomendado)
pip install -r requirements.txt

# Demo offline ponta-a-ponta (ingestão de 2 sessões + recuperação híbrida)
python examples/run_example.py

# Servidor MCP read-only para um agente
MEMORY_DB=./memory.db python -m healthos_memory.mcp_server
```

Variáveis de ambiente (ver `.env.example`): `MEMORY_DB`, `MEMORY_EMBEDDER`
(`offline` | `openai`), e `OPENAI_API_KEY` só quando `MEMORY_EMBEDDER=openai`.

---

## Invariantes (não quebrar)

1. **Ordem do vetor dimensional é contrato.** `DIMENSIONAL_VECTOR_ORDER` (17
   componentes) não pode ser reordenado sem migrar os vetores já gravados.
2. **Bi-temporalidade: invalidar, não deletar.** Fatos superados recebem
   `expired_at`/`valid_to`; nunca são removidos. Preserva auditoria clínica e o
   "como estava antes".
3. **Namespacing por paciente.** Toda leitura/escrita é filtrada por `patient_id`.
   Não introduza caminho que cruze pacientes.
4. **Recuperação é local.** `assemble_context` e os modos de `retrieve.py` **não**
   chamam LLM no momento da query — só busca local + álgebra de vetores.
5. **Artefatos derivados, não-autorizantes.** Tudo que a memória devolve é
   superfície de insight clínico, *summary-only* — nunca conduta, prescrição
   efetiva ou autorização. O `disclaimer` do bundle não deve ser removido.
6. **Sem camada de confiança nesta versão.** O store dimensional guarda só os
   `score` de v1..v15. Adicionar confiança depois é possível sem quebrar o schema.
7. **MCP é read-only.** A ingestão acontece fora do agente, pelo pipeline de
   projeção/ingestão.

---

## Convenções

- Idioma do código, docs e mensagens: **PT-BR** (como o restante do repo).
- IDs lógicos de GEM (clusters/flows/pathways) são **estáveis entre sessões**
  (ex.: `C_LUTO_RUMINACAO`, `EPE_RECLAMAR_AGENCIA`) — é o que permite a memória
  **acumular e superar**.
- Mudanças de schema vêm acompanhadas de migração e atualização do
  `memory_projection.schema.json` + `constants.py` juntos.
- Mantenha edições no escopo pedido; não faça refactors oportunistas nem mexa em
  arquivos gerados/`examples/_demo_memory.db`.

---

## Fluxo de trabalho git

- Verifique `main` local vs `origin/main` antes de começar.
- Crie branch a partir de `main`; publique via PR quando solicitado.
- Hashes/branches explícitos no relato; `fetch --prune` após remoção de branch remota.
