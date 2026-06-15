"""
embeddings.py — Embedder plugável para os trechos de evidência.

Dois modos, selecionados por env var MEMORY_EMBEDDER:

  - "offline" (default): embedder determinístico via hashing de tokens. Roda sem
    nenhuma chave de API. Bom para desenvolvimento, testes e ambientes fechados.
  - "openai": usa text-embedding-3-small via REST (env OPENAI_API_KEY).
    Apenas urllib da stdlib — sem dependências extras.

A camada dimensional (VDLP) NÃO usa este módulo: o vetor de 17-D já é o seu
próprio embedding interpretável (ver vectors.py).

Nunca embuta segredos no código — a chave vem só de variável de ambiente.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import urllib.request
from typing import List

import numpy as np

OFFLINE_DIM = 256


def embedder_name() -> str:
    return os.environ.get("MEMORY_EMBEDDER", "offline").strip().lower()


# ---- offline determinístico --------------------------------------------------

def _offline_embed_one(text: str, dim: int = OFFLINE_DIM) -> np.ndarray:
    """
    Embedding determinístico por hashing de tokens (bag-of-hashed-tokens com
    sinal). Não é semântico de verdade, mas é estável e suficiente para validar
    o pipeline ponta-a-ponta sem chave.
    """
    vec = np.zeros(dim, dtype=np.float32)
    tokens = [t for t in text.lower().split() if t]
    for tok in tokens:
        h = hashlib.sha1(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if (h[4] & 1) else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


# ---- OpenAI ------------------------------------------------------------------

def _openai_embed(texts: List[str]) -> np.ndarray:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MEMORY_EMBEDDER=openai mas OPENAI_API_KEY não está definida no ambiente."
        )
    model = os.environ.get("MEMORY_EMBEDDER_MODEL", "text-embedding-3-small")
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    ordered = sorted(data["data"], key=lambda d: d["index"])
    return np.array([d["embedding"] for d in ordered], dtype=np.float32)


# ---- API pública -------------------------------------------------------------

def embed(texts: List[str]) -> np.ndarray:
    """Retorna matriz (len(texts), dim) float32. Vazio -> shape (0, dim)."""
    if not texts:
        return np.zeros((0, OFFLINE_DIM), dtype=np.float32)
    name = embedder_name()
    if name == "openai":
        return _openai_embed(texts)
    return np.vstack([_offline_embed_one(t) for t in texts])


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]


# ---- serialização BLOB <-> np ------------------------------------------------

def to_blob(vec: np.ndarray) -> bytes:
    vec = np.asarray(vec, dtype=np.float32).ravel()
    return struct.pack(f"<{vec.size}f", *vec.tolist())


def from_blob(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"<{n}f", blob), dtype=np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
