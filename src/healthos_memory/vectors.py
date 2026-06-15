"""
vectors.py — Constrói o vetor dimensional interpretável (17-D) a partir do
dict nomeado de dimensões v1..v15.

Diferente de um embedding de texto opaco, cada componente aqui tem nome e
significado clínico — similaridade entre vetores é explicável ("sessões em
configuração mental parecida"). v5 (orientação temporal) entra como seus 3
componentes baricêntricos.
"""

from __future__ import annotations

from typing import Dict

import numpy as np

from .constants import DIMENSIONAL_VECTOR_ORDER, DIMENSIONAL_VECTOR_DIM, NEUTRAL_FILL


def dimensions_to_vector(dimensions: Dict) -> np.ndarray:
    """
    `dimensions` é o dict nomeado (forma rica), ex.:
        {
          "v1_valencia_emocional": -0.35,
          "v5_orientacao_temporal": {"passado": 0.5, "presente": 0.3, "futuro": 0.2},
          "v15_prosodia_emocional": None,   # ausente -> imputado
          ...
        }
    Retorna float32 (17,) na ordem canônica. Valores ausentes/None -> NEUTRAL_FILL.
    """
    v5 = dimensions.get("v5_orientacao_temporal") or {}
    flat = {
        "v5_passado": _num(v5.get("passado")),
        "v5_presente": _num(v5.get("presente")),
        "v5_futuro": _num(v5.get("futuro")),
    }
    out = np.empty(DIMENSIONAL_VECTOR_DIM, dtype=np.float32)
    for i, key in enumerate(DIMENSIONAL_VECTOR_ORDER):
        if key in flat:
            out[i] = flat[key]
        else:
            out[i] = _num(dimensions.get(key))
    return out


def _num(x) -> float:
    if x is None:
        return float(NEUTRAL_FILL)
    try:
        return float(x)
    except (TypeError, ValueError):
        return float(NEUTRAL_FILL)
