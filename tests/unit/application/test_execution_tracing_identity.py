"""Testes da identidade e da duracao nos traces vivos.

Sem `execution_id` no metadata, o replay de datasets e o comparador de releases
nao conseguem parear execucoes: os dois usam documento mais execucao como chave.
E a duracao precisa sair do intervalo dos artefatos, nao da distancia ate o
instante da projecao, que roda depois e produz numero negativo.
"""

from __future__ import annotations

from document_processing.application.use_cases.observability.execution_tracing import (
    AtlasExecutionTracer,
)
from document_processing.domain.observability import end_to_end_metrics

_id_da_chave = AtlasExecutionTracer._execution_id_from_key


def test_execution_id_sai_do_caminho_do_artefato():
    chave = (
        "execucoes/bancos/extracao/itau/ano=2026/periodo=2T26/"
        "document_id=79e8245d/execution_id=dag_detecta_pdf_e_extrai__itau__2T26/"
        "extraction/manifesto_execucao.json"
    )
    assert _id_da_chave(chave) == "dag_detecta_pdf_e_extrai__itau__2T26"


def test_caminho_sem_execution_id_devolve_vazio():
    assert _id_da_chave("execucoes/bancos/extracao/itau/manifesto.json") == ""
    assert _id_da_chave(None) == ""


def test_duracao_ausente_nao_vira_zero():
    """"Nao aplicavel" e "instantaneo" nao podem cair na mesma media."""
    nomes = {
        m.name
        for m in end_to_end_metrics(
            sucesso=False,
            exigiu_llm=True,
            duracao_segundos=None,
            apto_para_bronze=False,
        )
    }
    assert "e2e_duracao_segundos" not in nomes


def test_duracao_presente_e_emitida():
    metricas = {
        m.name: m.value
        for m in end_to_end_metrics(
            sucesso=True,
            exigiu_llm=True,
            duracao_segundos=12.5,
            apto_para_bronze=True,
        )
    }
    assert metricas["e2e_duracao_segundos"] == 12.5
