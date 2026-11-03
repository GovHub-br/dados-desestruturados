"""Escopo de periodo declarado no contrato (``escopo_periodo``) e conferido no validador.

Regressoes da auditoria da ABECIP (lote 16, tentativa 3): em 2026-07 saldos e captacoes sairam da
coluna do ano anterior (o cabecalho do Docling perdeu o ano, so a contagem de meses denuncia), e em
4 meses a serie anual levou o ano em andamento (``2026*``). A regra so age se o contrato declarar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_linhas_de_tabelas_no_fallback import _candidato_abecip, _fonte_abecip, _linhas_de_tabelas

from document_processing.application.use_cases.fallback.context_builder import (
    FallbackProblemContextBuilder,
)
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.mapping_plan import MappingPlanService
from document_processing.domain.fallback.table_row_ranges import period_scope_problems

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _poupanca_de_julho() -> dict:
    """Ano anterior inteiro na coluna 1, ano de referencia ate julho na coluna 2; cabecalho sem o ano."""
    linhas = [[mes, f"75{i}.496", f"76{i}.745" if i < 7 else ""] for i, mes in enumerate(MESES)]
    return {"schema": ["Meses.", "Saldo.Saldo", "Saldo"], "rows": linhas}


def _anual_de_julho() -> dict:
    anos = [[str(a), "421.386", "56.197,59"] for a in range(2010, 2026)]
    parcial = [["2026*", "", ""]] + [[mes, "35.701", "12.125,32"] for mes in ["Janeiro", "Fevereiro"]]
    return {"schema": ["Anos.", "Unidades", "R$"], "rows": anos + parcial + [["Em 2026", "70.840", "23.901,7"]]}


def _instrucao(arquivo: str, coluna: int, **extra) -> dict:
    return {
        "tipo_origem": "linhas_de_tabela",
        "arquivo_origem": arquivo,
        "campos": [
            {"caminho_saida": "periodo.rotulo_publicado", "indice_coluna": 0},
            {"caminho_saida": "saldo_milhoes", "indice_coluna": coluna},
        ],
        **extra,
    }


TABELAS = {"tables/table002.json": _poupanca_de_julho(), "tables/table009.json": _anual_de_julho()}
SALDOS = "poupanca_sbpe.saldos_mensais"
ANUAL = "financiamentos_imobiliarios.serie_historica_anual"


def test_coluna_do_ano_anterior_tem_mais_meses_que_o_mes_de_referencia_e_e_recusada():
    problemas = period_scope_problems(
        {SALDOS: _instrucao("tables/table002.json", 1)}, TABELAS, {SALDOS: "ano_de_referencia"}, "2026-07"
    )
    assert len(problemas) == 1 and "12 linhas" in problemas[0] and "2026" in problemas[0]


def test_coluna_do_ano_de_referencia_passa_mesmo_sem_tipo_numero_nos_campos():
    assert period_scope_problems(
        {SALDOS: _instrucao("tables/table002.json", 2)}, TABELAS, {SALDOS: "ano_de_referencia"}, "2026-07"
    ) == []


def test_serie_anual_inteira_leva_o_ano_parcial_e_e_recusada_com_os_rotulos_sugeridos():
    problemas = period_scope_problems(
        {ANUAL: _instrucao("tables/table009.json", 1)}, TABELAS, {ANUAL: "anos_completos"}, "2026-07"
    )
    assert len(problemas) == 1
    assert "Janeiro" in problemas[0] and "Em 2026" in problemas[0] and "rotulo_inicial '2010'" in problemas[0] and "rotulo_final '2025'" in problemas[0]


def test_serie_anual_por_rotulos_so_com_anos_fechados_passa():
    instrucao = _instrucao("tables/table009.json", 1, rotulo_inicial="2010", rotulo_final="2025")
    assert period_scope_problems({ANUAL: instrucao}, TABELAS, {ANUAL: "anos_completos"}, "2026-07") == []


@pytest.mark.parametrize("periodo", ["2T26", "sem_periodo", "", None])
def test_sem_periodo_mensal_nao_ha_o_que_conferir(periodo):
    assert period_scope_problems(
        {SALDOS: _instrucao("tables/table002.json", 1)}, TABELAS, {SALDOS: "ano_de_referencia"}, periodo
    ) == []


def test_sem_escopo_declarado_nada_e_conferido():
    assert period_scope_problems({SALDOS: _instrucao("tables/table002.json", 1)}, TABELAS, {}, "2026-07") == []


# --- os contratos v2.4.0 (so texto) e v2.5.0 (texto + escopo) ------------------------


def _contexto(versao: str) -> dict:
    caminho = Path(f"infra/minio-bootstrap/contracts/abecip/{versao}/contrato_semantico_abecip.json")
    contrato = json.loads(caminho.read_text(encoding="utf-8"))
    builder = FallbackProblemContextBuilder()
    contexto = {
        "escopo_permitido": "criacao_inicial_layout",
        "fallback_context": {"document_id": "doc", "execution_id": "exec", "manifest_key": "m", "entity_slug": "abecip"},
        "contrato_semantico_relevante": builder._relevant_contract_context(contract=contrato, broken_fields=[]),
        "inventario_extracao": {"resumo": {"items": []}},
        "identidade_documento": {"entidade": "abecip", "entidade_nome": "ABECIP", "periodo": "2026-07"},
        "_paths_fixos_do_contrato": [],
        "layout_signature_base_ref": None,
        "artefatos_contexto_llm": TABELAS,
    }
    contexto["llm_payloads"] = builder.build_llm_payloads(contexto)
    return contexto


def _candidato_com_saldo_na_coluna(coluna: int) -> dict:
    candidato = _candidato_abecip(
        _linhas_de_tabelas(
            _fonte_abecip("tables/table005.json", "construcao", 8),
            _fonte_abecip("tables/table006.json", "aquisicao", 9),
            _fonte_abecip("tables/table007.json", "total", 10),
        )
    )
    for caminho in (SALDOS, "poupanca_sbpe.captacoes_liquidas_mensais"):
        instrucao = candidato["mapeamento_canonico"][caminho]
        instrucao.pop("faixas_linhas")
        instrucao["campos"][1]["indice_coluna"] = coluna
    return candidato


def test_contrato_com_escopo_recusa_a_coluna_do_ano_anterior():
    with pytest.raises(RuntimeError, match="escopo de periodo"):
        FallbackCandidateValidationService().validate_candidate_layout(_candidato_com_saldo_na_coluna(1), _contexto("v2.5.0"))


def test_contrato_com_escopo_aceita_a_coluna_do_ano_de_referencia():
    FallbackCandidateValidationService().validate_candidate_layout(_candidato_com_saldo_na_coluna(2), _contexto("v2.5.0"))


def test_contrato_so_com_texto_nao_confere_o_escopo():
    FallbackCandidateValidationService().validate_candidate_layout(_candidato_com_saldo_na_coluna(1), _contexto("v2.4.0"))


@pytest.mark.parametrize("versao", ["v2.4.0", "v2.5.0"])
def test_a_descricao_da_colecao_chega_ao_recorte_do_contrato_que_a_llm_recebe(versao):
    contexto = _contexto(versao)
    unidade = next(
        u for u in MappingPlanService().build(contexto["contrato_semantico_relevante"]) if SALDOS in u.mapping_paths
    )
    recorte = json.dumps(MappingPlanService.scoped_contract_context(contexto["contrato_semantico_relevante"], unidade), ensure_ascii=False)
    assert "ano de referência do boletim" in recorte
