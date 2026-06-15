"""
Constantes canônicas do HealthOS Patient Memory.

A camada dimensional (VDLP) é o núcleo interpretável da memória: cada sessão
colapsa num ponto do Espaço Mental ℳ. Para similaridade vetorial usamos uma
ordenação fixa de 17 componentes (15 dimensões, sendo v5 expandido em seus 3
componentes baricêntricos passado/presente/futuro).

Esta ordenação é um contrato: NÃO reordene sem migrar os vetores já gravados.
"""

# Ordem canônica do vetor de similaridade dimensional (17 componentes).
# v5 (orientação temporal) entra como 3 componentes baricêntricos.
DIMENSIONAL_VECTOR_ORDER = [
    "v1_valencia_emocional",
    "v2_arousal_ativacao",
    "v3_coerencia_narrativa",
    "v4_complexidade_sintatica",
    "v5_passado",
    "v5_presente",
    "v5_futuro",
    "v6_densidade_autorreferencia",
    "v7_orientacao_social",
    "v8_flexibilidade_cognitiva",
    "v9_senso_agencia",
    "v10_fragmentacao_discurso",
    "v11_densidade_ideias",
    "v12_certeza_incerteza",
    "v13_padroes_conectividade",
    "v14_comunicacao_pragmatica",
    "v15_prosodia_emocional",
]

DIMENSIONAL_VECTOR_DIM = len(DIMENSIONAL_VECTOR_ORDER)  # 17

# Dimensões com escala [-1, +1]; o resto é [0, 1]. Usado só para documentação/validação leve.
BIPOLAR_DIMENSIONS = {
    "v1_valencia_emocional",
    "v12_certeza_incerteza",
}

# Valor de imputação para dimensões ausentes/null (ex.: v15 quando não aplicável).
# Escolhido como ponto neutro de cada escala.
NEUTRAL_FILL = 0.0

# Papéis de cluster GEM relevantes para os caminhos emergenáveis (.epe).
CLUSTER_ROLES = ("friction", "leverage", "neutral")

# Tipos de fluxo/caminho GEM.
FLOW_KIND_DIAGNOSTIC = "diagnostic"   # .e  — o que EMERGIU (passado→presente)
PATHWAY_KIND_PROGNOSTIC = "prognostic"  # .epe — o que PODE emergir (potencial)
