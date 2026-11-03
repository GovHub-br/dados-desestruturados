"""O que sai do resolvedor e o que passa no validador obedece ao contrato, nao ao que a LLM lembrou de declarar.

Regressoes da auditoria da ABECIP (lote 16, tentativa 3): em 2026-02 a LLM omitiu ``"tipo": "numero"``
e 138 valores sairam como texto; o periodo de ``valores_por_segmento`` saiu na chave plana
``"periodo.rotulo_publicado"``; em 2026-07 a modalidade foi gravada fora do dominio do contrato.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_linhas_de_tabelas_no_fallback import (
    _candidato_abecip,
    _contexto_abecip,
    _fonte_abecip,
    _linhas_de_tabelas,
)

from document_processing.application.use_cases.resolution.resolve_schema import ResolveSchemaUseCase
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)


def _contrato_abecip() -> dict:
    caminho = next(Path("infra/minio-bootstrap/contracts/abecip/v2.3.0").glob("*.json"))
    return json.loads(caminho.read_text(encoding="utf-8"))


def _resolver(tmp_path: Path, tabelas: dict[str, list[list[str]]], mapeamento: dict) -> dict:
    for arquivo, linhas in tabelas.items():
        destino = tmp_path / arquivo
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({"rows": linhas}), encoding="utf-8")
    carregado = {
        "contrato_semantico": _contrato_abecip(),
        "layout_signature": {"mapeamento_canonico": mapeamento},
        "extraction_root": str(tmp_path),
        "manifest": {},
    }
    validacao = {"status_compatibilidade": {"status": "compativel"}}
    return ResolveSchemaUseCase().resolve_canonical_mapping(carregado, validacao)["schema_saida"]


SERIE = [["Jan", "35.701", "12.125"], ["Fev", "35.139", "11.776"]]


def test_campo_number_do_contrato_sai_numero_mesmo_sem_tipo_na_instrucao(tmp_path):
    mapeamento = {
        "financiamentos_imobiliarios.serie_mensal_sbpe": {
            "tipo_origem": "linhas_de_tabela",
            "arquivo_origem": "tables/table004.json",
            "campos": [
                {"caminho_saida": "periodo.rotulo_publicado", "indice_coluna": 0},
                {"caminho_saida": "unidades_financiadas", "indice_coluna": 1},
                {"caminho_saida": "volume_financiado_milhoes", "indice_coluna": 2},
            ],
        }
    }
    serie = _resolver(tmp_path, {"tables/table004.json": SERIE}, mapeamento)["financiamentos_imobiliarios"]["serie_mensal_sbpe"]
    assert [(i["unidades_financiadas"], i["volume_financiado_milhoes"]) for i in serie] == [(35701.0, 12125.0), (35139.0, 11776.0)]
    # o rotulo e string no contrato e continua texto
    assert [i["periodo"]["rotulo_publicado"] for i in serie] == ["Jan", "Fev"]


def test_texto_que_nao_e_numero_num_campo_number_vira_nulo(tmp_path):
    mapeamento = {
        "financiamentos_imobiliarios.serie_mensal_sbpe": {
            "tipo_origem": "linhas_de_tabela",
            "arquivo_origem": "tables/table004.json",
            "campos": [{"caminho_saida": "unidades_financiadas", "indice_coluna": 1}],
        }
    }
    serie = _resolver(tmp_path, {"tables/table004.json": [["Jan", "n.d."]]}, mapeamento)["financiamentos_imobiliarios"]["serie_mensal_sbpe"]
    assert serie[0]["unidades_financiadas"] is None


def test_chave_com_ponto_em_valores_por_segmento_sai_aninhada(tmp_path):
    fonte = {
        "arquivo_origem": "tables/table006.json",
        "campos": [
            {"caminho_saida": "instituicao_financeira", "indice_coluna": 0},
            {"caminho_saida": "volume_mensal_milhoes", "indice_coluna": 1},
        ],
        "valores_por_segmento": {"modalidade": "construcao", "periodo.rotulo_publicado": "FEV/2026"},
    }
    mapeamento = {
        "financiamentos_imobiliarios.por_modalidade_e_instituicao": {"tipo_origem": "linhas_de_tabelas", "fontes": [fonte]}
    }
    itens = _resolver(tmp_path, {"tables/table006.json": [["CAIXA", "2.173,1"]]}, mapeamento)["financiamentos_imobiliarios"][
        "por_modalidade_e_instituicao"
    ]
    assert itens[0]["periodo"]["rotulo_publicado"] == "FEV/2026"
    assert "periodo.rotulo_publicado" not in itens[0]
    assert itens[0]["volume_mensal_milhoes"] == 2173.1


def test_valor_fixo_fora_do_dominio_do_contrato_e_recusado_com_os_valores_admitidos():
    contexto = _contexto_abecip()
    modalidade = _linhas_de_tabelas(
        _fonte_abecip("tables/table005.json", "construcao", 8),
        _fonte_abecip("tables/table006.json", "aquisicao", 9),
        _fonte_abecip("tables/table007.json", "Aquisicao e Construcao", 10),
    )
    with pytest.raises(RuntimeError, match=r"fora do dominio.*'Aquisicao e Construcao'.*'total'"):
        FallbackCandidateValidationService().validate_candidate_layout(_candidato_abecip(modalidade), contexto)


def test_valor_fixo_do_dominio_com_caixa_diferente_tambem_e_recusado():
    contexto = _contexto_abecip()
    modalidade = _linhas_de_tabelas(_fonte_abecip("tables/table005.json", "Construcao", 8))
    with pytest.raises(RuntimeError, match="fora do dominio"):
        FallbackCandidateValidationService().validate_candidate_layout(_candidato_abecip(modalidade), contexto)


def test_campo_sem_dominio_no_contrato_aceita_qualquer_valor_fixo():
    """instituicao_financeira nao tem dominio: valor fixo livre continua valido."""
    contexto = _contexto_abecip()
    fonte = _fonte_abecip("tables/table005.json", "construcao", 8)
    fonte["valores_por_segmento"]["instituicao_financeira"] = "QUALQUER"
    fonte["campos"] = [c for c in fonte["campos"] if c["caminho_saida"] != "instituicao_financeira"]
    FallbackCandidateValidationService().validate_candidate_layout(_candidato_abecip(_linhas_de_tabelas(fonte)), contexto)
