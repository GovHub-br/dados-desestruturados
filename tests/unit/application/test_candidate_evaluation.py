"""Testes do portao de regras de negocio na avaliacao off-line.

O ponto central: separar "candidato invalido" de "contexto que nao permite
validar". Confundir os dois faria a metrica medir a idade do artefato historico
em vez da qualidade do candidato.
"""

from __future__ import annotations

import json

from document_processing.application.use_cases.fallback.candidate_evaluation import (
    contexto_de_validacao,
    validar_candidato,
)

DOCUMENTO = "doc-1"
EXECUCAO = "dag_detecta_pdf_e_extrai__cury__2T26"

CONTRATO = {
    "identificacao": {"nome": "construtoras", "versao": "1.0.0"},
    "contrato_semantico": {
        "entidades": {},
        "metricas": {},
        "requisitos_mapeamento": {
            "campos_obrigatorios": [{"path": "vendas.total"}],
        },
    },
    "estrutura_schema_saida": {
        "campos_raiz": ["vendas"],
        "paths_permitidos": ["vendas", "vendas.total"],
        "arrays_que_exigem_seletor": [],
    },
}


def _mensagens(contrato=CONTRATO) -> list[dict[str, str]]:
    """Reproduz a conversa persistida: prosa e blocos JSON alternados."""
    return [
        {"role": "system", "content": "Esta e uma criacao inicial de layout."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "contexto_execucao": {
                        "document_id": DOCUMENTO,
                        "escopo_correcao": "criacao_inicial_layout",
                        "execution_id_origem": EXECUCAO,
                        "base_layout_signature": None,
                    }
                }
            ),
        },
        {"role": "system", "content": "O proximo bloco contem a semantica."},
        {
            "role": "user",
            "content": json.dumps({"contrato_semantico_relevante": contrato}),
        },
    ]


def _candidato(**ajustes):
    base = {
        "tipo_artefato": "layout_signature_candidato",
        "status_layout": "candidato",
        "escopo_correcao": "criacao_inicial_layout",
        "document_id": DOCUMENTO,
        "execution_id_origem": EXECUCAO,
        "base_layout_signature": None,
        "mapeamento_canonico": {
            "vendas.total": {
                "tipo_origem": "campo_json",
                "arquivo_origem": "tables/table001.json",
                "caminho_json": "total",
                "obrigatorio": True,
            }
        },
    }
    base.update(ajustes)
    return base


def test_contexto_e_reconstruido_das_mensagens():
    """Escopo e linhagem vem do bloco enviado a LLM, nao do metadata do item."""
    contexto = contexto_de_validacao(_mensagens())
    assert contexto["escopo_permitido"] == "criacao_inicial_layout"
    assert contexto["fallback_context"]["execution_id"] == EXECUCAO
    assert contexto["contrato_semantico_relevante"] == CONTRATO


def test_candidato_coerente_e_aprovado():
    resultado = validar_candidato(_candidato(), mensagens=_mensagens())
    assert resultado.validavel is True
    assert resultado.valido is True


def test_campo_fora_do_contrato_reprova():
    """A comparacao de conjuntos nao veria isso; o validador ve."""
    candidato = _candidato(
        mapeamento_canonico={
            "vendas.inventado": {
                "tipo_origem": "campo_json",
                "arquivo_origem": "tables/table001.json",
                "caminho_json": "x",
            }
        }
    )
    resultado = validar_candidato(candidato, mensagens=_mensagens())
    assert resultado.validavel is True
    assert resultado.valido is False
    assert "fora do schema_saida" in resultado.motivo


def test_linhagem_divergente_reprova():
    resultado = validar_candidato(
        _candidato(execution_id_origem="outra-execucao"), mensagens=_mensagens()
    )
    assert resultado.validavel is True
    assert resultado.valido is False


def test_contrato_em_formato_antigo_nao_e_validavel():
    """Execucao historica nao vira reprovacao: e ausencia de julgamento."""
    antigo = {
        **CONTRATO,
        "contrato_semantico": {
            "entidades": {},
            "metricas": {},
            "requisitos_mapeamento": {"campos_obrigatorios": ["vendas.total"]},
        },
    }
    resultado = validar_candidato(_candidato(), mensagens=_mensagens(antigo))
    assert resultado.validavel is False
    assert resultado.valido is False
    assert "Contexto nao validavel" in resultado.motivo


def test_mensagens_sem_contexto_nao_sao_validaveis():
    resultado = validar_candidato(_candidato(), mensagens=[])
    assert resultado.validavel is False


def test_resposta_malformada_nao_levanta_excecao():
    """Avaliacao off-line nunca pode quebrar quem a chama."""
    resultado = validar_candidato("nao e um objeto", mensagens=_mensagens())
    assert resultado.validavel is True
    assert resultado.valido is False
