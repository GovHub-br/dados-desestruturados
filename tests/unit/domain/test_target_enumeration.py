"""Fase 1 do plano da assinatura: a lista fechada de chaves sai do contrato.

Cada teste e definido sobre objetos do contrato (requisito, observacao,
seletor, array, chave de item) e sobre a identidade do documento. Os contratos
publicados entram como fixtures para que uma mudanca neles seja vista aqui.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_processing.domain.contracts.mapping_requirements import (
    mapping_requirements_from_context,
)
from document_processing.domain.contracts.schema import contract_literal_paths, schema_paths
from document_processing.domain.fallback.target_enumeration import (
    MARCADOR_EVIDENCIA,
    TargetEnumerationError,
    describe_unexpected_key,
    enumerate_target_entries,
    expected_entries_payload,
    match_mapping_keys,
)

CONTRATOS = Path("infra/minio-bootstrap/contracts")
ABECIP = Path("resultados_construtoras/abecip/contratos/abecip/v2.1.1/contrato_semantico_abecip.json")


def _publicado(dominio: str, versao: str) -> dict:
    caminho = next((CONTRATOS / dominio / versao).glob("*.json"))
    return json.loads(caminho.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def construtoras() -> dict:
    return _publicado("construtoras", "v1.9.0")


@pytest.fixture(scope="module")
def bancos() -> dict:
    return _publicado("bancos", "v2.2.0")


@pytest.fixture(scope="module")
def abecip() -> dict:
    return json.loads(ABECIP.read_text(encoding="utf-8"))


IDENTIDADE = {"entidade": "cury", "periodo": "2T26"}


# --- construtoras: identidade + papel, tudo fechado pelo codigo -------------


def test_construtoras_fecha_uma_chave_por_observacao_e_por_contexto(construtoras):
    entradas = enumerate_target_entries(contract_context=construtoras, document_identity=IDENTIDADE)
    chaves = [entrada.chave for entrada in entradas]
    # 2 requisitos x 3 observacoes x (valor + periodo). escopo_periodo e literal
    # do contrato e nao gera entrada.
    assert len(chaves) == 12
    assert (
        "balancos_das_empresas.lancamentos.dados[empresa=cury]"
        ".valores[papel_periodo=periodo_referencia].valor"
    ) in chaves
    assert (
        "balancos_das_empresas.lancamentos.dados[empresa=cury]"
        ".valores[papel_periodo=periodo_referencia].periodo"
    ) in chaves
    assert not any(chave.endswith(".escopo_periodo") for chave in chaves)
    assert not any(entrada.filtros_pendentes for entrada in entradas)


def test_construtoras_herda_obrigatorio_da_observacao(construtoras):
    entradas = enumerate_target_entries(contract_context=construtoras, document_identity=IDENTIDADE)
    por_papel = {entrada.chave: entrada.obrigatorio for entrada in entradas}
    assert por_papel[
        "balancos_das_empresas.vendas.dados[empresa=cury].valores[papel_periodo=periodo_referencia].valor"
    ]
    assert not por_papel[
        "balancos_das_empresas.vendas.dados[empresa=cury].valores[papel_periodo=mesmo_periodo_ano_anterior].valor"
    ]
    # O contexto irmao herda o mesmo obrigatorio da observacao.
    assert not por_papel[
        "balancos_das_empresas.vendas.dados[empresa=cury].valores[papel_periodo=mesmo_periodo_ano_anterior].periodo"
    ]


def test_construtoras_nao_deixa_campo_livre_porque_a_raiz_e_derivada(construtoras):
    entradas = enumerate_target_entries(contract_context=construtoras, document_identity=IDENTIDADE)
    assert not [entrada for entrada in entradas if entrada.papel_no_alvo == "livre"]


def test_filtro_de_identidade_usa_o_slug_recebido_nao_o_nome(construtoras):
    identidade = {"entidade": "eztc3", "entidade_nome": "EZTEC"}
    entradas = enumerate_target_entries(contract_context=construtoras, document_identity=identidade)
    assert all("[empresa=eztc3]" in entrada.chave for entrada in entradas)


def test_identidade_sem_o_atributo_exigido_falha_antes_da_llm(construtoras):
    with pytest.raises(TargetEnumerationError) as excecao:
        enumerate_target_entries(contract_context=construtoras, document_identity={"periodo": "2T26"})
    assert "identidade_documento" in str(excecao.value)
    assert "entidade" in str(excecao.value)


# --- bancos: seletor do contrato + rotulo que so o documento conhece --------


def test_bancos_deixa_pendente_somente_o_filtro_de_evidencia(bancos):
    entradas = enumerate_target_entries(contract_context=bancos, document_identity={"entidade": "itau"})
    valor = next(
        entrada
        for entrada in entradas
        if entrada.requisito == "indicadores_percentuais.dados.valores.valor"
        and entrada.seletores == {"indicador": "inadimplencia_90_dias"}
        and entrada.papel_no_alvo == "valor"
    )
    assert valor.chave == (
        "indicadores_percentuais.dados[indicador=inadimplencia_90_dias]"
        f".valores[periodo={MARCADOR_EVIDENCIA}].valor"
    )
    assert valor.filtros_pendentes == ("indicadores_percentuais.dados.valores",)
    assert valor.payload()["filtros_pendentes"] == {"indicadores_percentuais.dados.valores": "periodo"}


@pytest.mark.parametrize(
    ("chave", "aceita"),
    [
        ("indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[periodo=Jun/26].valor", True),
        ("indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[periodo=Mar/26].valor", True),
        # O marcador e um nome de origem nunca sao rotulos.
        ("indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[periodo=<evidencia>].valor", False),
        ("indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[periodo=evidencia].valor", False),
        # Chave do array errada (o caso que ADR 0011 fechou no validador).
        ("indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[indicador=x].valor", False),
        # Array atravessado sem filtro.
        ("indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores.valor", False),
        # Seletor do contrato trocado por rotulo do documento.
        ("indicadores_percentuais.dados[indicador=NPL 90d].valores[periodo=Jun/26].valor", False),
    ],
)
def test_entrada_pendente_aceita_uma_instancia_por_rotulo(bancos, chave, aceita):
    entradas = enumerate_target_entries(contract_context=bancos, document_identity={"entidade": "itau"})
    assert any(entrada.matches(chave) for entrada in entradas) is aceita


def test_bancos_mantem_como_livres_as_folhas_de_raiz_nao_derivadas(bancos):
    entradas = enumerate_target_entries(contract_context=bancos, document_identity={"entidade": "itau"})
    livres = {entrada.chave for entrada in entradas if entrada.papel_no_alvo == "livre"}
    # periodo_referencia e derivada do manifesto; os comparativos nao sao.
    assert livres == {
        "periodos_disponiveis.periodo_comparativo_anterior",
        "periodos_disponiveis.mesmo_periodo_ano_anterior",
    }
    assert all(not entrada.obrigatorio for entrada in entradas if entrada.papel_no_alvo == "livre")


# --- abecip: colecao inteira, contrato sem chaves_de_item -------------------


def test_requisito_no_proprio_array_vira_colecao_sem_filtro(abecip):
    entradas = enumerate_target_entries(contract_context=abecip, document_identity={"entidade": "abecip"})
    colecoes = {entrada.chave: entrada for entrada in entradas if entrada.modo_array == "colecao"}
    assert "financiamentos_imobiliarios.serie_mensal_sbpe" in colecoes
    entrada = colecoes["financiamentos_imobiliarios.serie_mensal_sbpe"]
    assert entrada.matches("financiamentos_imobiliarios.serie_mensal_sbpe")
    assert not entrada.matches("financiamentos_imobiliarios.serie_mensal_sbpe[periodo=x]")
    assert not entrada.matches("financiamentos_imobiliarios.serie_mensal_sbpe.valor")


# --- propriedades validas para qualquer contrato ---------------------------


@pytest.mark.parametrize("nome", ["construtoras", "bancos", "abecip"])
def test_toda_chave_esta_em_paths_permitidos_e_toda_observacao_obrigatoria_tem_entrada(nome, request):
    contrato = request.getfixturevalue(nome)
    entradas = enumerate_target_entries(contract_context=contrato, document_identity=IDENTIDADE)
    permitidos = schema_paths(contrato["schema_saida"]) - set(contract_literal_paths(contrato["schema_saida"]))
    assert {entrada.path_normalizado for entrada in entradas} <= permitidos
    assert len({entrada.chave for entrada in entradas}) == len(entradas)
    for requisito in mapping_requirements_from_context(contrato, validate_schema_paths=False):
        for observacao in requisito.observations:
            if not observacao.required:
                continue
            assert any(
                entrada.requisito == requisito.path
                and entrada.seletores == observacao.selectors
                and entrada.papel_no_alvo == "valor"
                and entrada.obrigatorio
                for entrada in entradas
            ), (requisito.path, observacao.selectors)


def test_payload_e_compacto_e_omite_o_que_nao_existe(construtoras):
    entradas = enumerate_target_entries(contract_context=construtoras, document_identity=IDENTIDADE)
    payload = expected_entries_payload(entradas)
    assert set(payload[0]) == {"chave", "requisito", "campo", "papel_no_alvo", "obrigatorio", "modo_array", "seletores"}
    assert "filtros_pendentes" not in payload[0]


# --- comparacao chave a chave e mensagens do reparo -------------------------


def test_match_separa_esperadas_instancias_e_intrusas(bancos):
    entradas = enumerate_target_entries(contract_context=bancos, document_identity={"entidade": "itau"})
    geradas = [
        "indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[periodo=Jun/26].valor",
        "indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[periodo=Mar/26].valor",
        "indicadores_percentuais.dados[indicador=inadimplencia_90_dias].valores[periodo=Jun/26].periodo",
        "indicadores_percentuais.dados[indicador=inadimplencia_90_dias].instituicao",
    ]
    resultado = match_mapping_keys(entradas, geradas)
    assert resultado.nao_esperadas == (
        "indicadores_percentuais.dados[indicador=inadimplencia_90_dias].instituicao",
    )
    # Duas instancias da mesma entrada pendente contam uma vez como cobertura.
    assert len({entrada.chave for entrada in resultado.por_chave.values() if entrada}) == 2
    assert all(
        entrada.seletores != {"indicador": "inadimplencia_90_dias"} or entrada.campo not in {"valor", "periodo"}
        for entrada in resultado.obrigatorias_sem_chave
    )


def test_mensagem_de_chave_intrusa_aponta_a_chave_esperada_do_mesmo_campo(construtoras):
    entradas = enumerate_target_entries(contract_context=construtoras, document_identity=IDENTIDADE)
    # O caso Direcional do lote 7: o nome da origem no lugar do valor.
    mensagem = describe_unexpected_key(
        "balancos_das_empresas.lancamentos.dados[empresa=identidade_documento]"
        ".valores[papel_periodo=periodo_referencia].valor",
        entradas,
    )
    assert "[empresa=cury]" in mensagem
    assert "copie-as exatamente" in mensagem
    # Campo que a DAG 2 preenche sozinha: a instrucao e remover, nao trocar.
    mensagem = describe_unexpected_key("balancos_das_empresas.lancamentos.dados[empresa=cury].empresa", entradas)
    assert "Remova a chave" in mensagem


# --- declaracoes do contrato que mudam a enumeracao -------------------------


def _contrato_minimo(chaves_de_item: dict, observacoes: list[dict]) -> dict:
    return {
        "schema_saida": {
            "grupo": {
                "itens": [
                    {"nome": "string", "valores": [{"periodo": "string", "valor": "number | null"}]}
                ]
            }
        },
        "contrato_semantico": {
            "chaves_de_item": chaves_de_item,
            "requisitos_mapeamento": {
                "campos_obrigatorios": [
                    {"path": "grupo.itens.valores.valor", "observacoes_obrigatorias": observacoes}
                ]
            },
        },
    }


def test_atributo_identidade_escolhe_o_periodo_no_lugar_da_entidade():
    contrato = _contrato_minimo(
        {
            "grupo.itens": {"chave": "nome", "origem_valor": "identidade_documento"},
            "grupo.itens.valores": {
                "chave": "periodo",
                "origem_valor": "identidade_documento",
                "atributo_identidade": "periodo",
            },
        },
        [{"seletores": {"nome": "x"}, "campos_contexto_obrigatorios": ["periodo"]}],
    )
    entradas = enumerate_target_entries(
        contract_context=contrato, document_identity={"entidade": "acme", "periodo": "1T26"}
    )
    assert "grupo.itens[nome=x].valores[periodo=1T26].valor" in {entrada.chave for entrada in entradas}


def test_seletor_da_observacao_vence_a_identidade_quando_o_contrato_o_declara():
    contrato = _contrato_minimo(
        {"grupo.itens": {"chave": "nome", "origem_valor": "identidade_documento"}},
        [{"seletores": {"nome": "declarado"}, "campos_contexto_obrigatorios": []}],
    )
    entradas = enumerate_target_entries(
        contract_context=contrato, document_identity={"entidade": "acme"}
    )
    chaves = {entrada.chave for entrada in entradas}
    assert "grupo.itens[nome=declarado].valores[<chave>=<evidencia>].valor" in chaves


def test_array_de_seletor_sem_o_seletor_na_observacao_e_contrato_inconsistente():
    contrato = _contrato_minimo(
        {"grupo.itens": {"chave": "nome", "origem_valor": "seletor_observacao"}},
        [{"seletores": {"papel": "ref"}, "campos_contexto_obrigatorios": []}],
    )
    with pytest.raises(TargetEnumerationError) as excecao:
        enumerate_target_entries(contract_context=contrato, document_identity={"entidade": "acme"})
    assert "seletor_observacao" in str(excecao.value)


def test_contrato_legado_poe_o_seletor_no_array_mais_interno_sem_chave():
    contrato = _contrato_minimo(
        {},
        [{"seletores": {"papel": "ref"}, "campos_contexto_obrigatorios": ["periodo"]}],
    )
    entradas = enumerate_target_entries(contract_context=contrato, document_identity={"entidade": "acme"})
    chave = next(entrada for entrada in entradas if entrada.papel_no_alvo == "valor").chave
    assert chave == "grupo.itens[<chave>=<evidencia>].valores[papel=ref].valor"
    assert next(entrada for entrada in entradas if entrada.papel_no_alvo == "valor").matches(
        "grupo.itens[nome=qualquer].valores[papel=ref].valor"
    )
