"""``chaves_de_item`` e ``derivacoes``: o contrato dirige o que antes era codigo.

Um contrato sem os blocos cai no legado; um contrato com os blocos e validado
contra o proprio ``schema_saida`` para que um path errado falhe na leitura, e
nao em silencio na resolucao.
"""

from __future__ import annotations

import pytest

from document_processing.domain.contracts.capabilities import (
    ContractCapabilitiesError,
    Derivation,
    apply_derivations,
    derivations,
    field_type,
    item_keys,
    uses_generic_resolution,
)

SCHEMA = {
    "fonte": "string",
    "instituicao": "string",
    "periodo_referencia": "string",
    "periodos_disponiveis": {"periodo_referencia": "string"},
    "serie": {
        "tipo": "valor_bruto",
        "dados": [
            {
                "instituicao": "string",
                "indicador": "string",
                "valores": [{"periodo": "string", "escopo_periodo": "string", "valor": "number | null"}],
            }
        ],
    },
}


def _contrato(**semantic):
    return {"fonte": "Fonte declarada", "schema_saida": SCHEMA, "contrato_semantico": semantic}


def test_contrato_sem_blocos_fica_no_legado():
    assert item_keys(_contrato()) == {}
    assert derivations(_contrato()) == ()
    assert uses_generic_resolution(_contrato()) is False


def test_chaves_de_item_lidas_e_ligam_o_modo_generico():
    contrato = _contrato(chaves_de_item={"serie.dados": "indicador", "serie.dados.valores": "periodo"})
    assert item_keys(contrato) == {"serie.dados": "indicador", "serie.dados.valores": "periodo"}
    assert uses_generic_resolution(contrato) is True


def test_chave_de_item_fora_dos_arrays_e_recusada():
    with pytest.raises(ContractCapabilitiesError, match="nao sao arrays"):
        item_keys(_contrato(chaves_de_item={"serie.tipo": "x"}))


def test_chave_pode_ser_papel_que_nao_e_campo_do_item():
    """Construtoras identifica ``valores`` por ``papel_periodo``, que o item nao tem."""
    contrato = _contrato(chaves_de_item={"serie.dados.valores": "papel_periodo"})
    assert item_keys(contrato) == {"serie.dados.valores": "papel_periodo"}


@pytest.mark.parametrize(
    "ruim, trecho",
    [
        ([{"destino": "fonte", "origem": {"tipo": "planilha", "campo": "x"}}], "origem desconhecida"),
        ([{"destino": "inexistente", "origem": {"tipo": "contrato", "campo": "fonte"}}], "fora do schema_saida"),
        ([{"destino": "fonte", "origem": {"tipo": "observacao", "campo": "periodo"}}], "exige origem.seletor"),
        ([{"destino": "fonte", "origem": {"tipo": "contrato"}}], "sem origem.campo"),
    ],
)
def test_derivacao_invalida_falha_na_leitura(ruim, trecho):
    with pytest.raises(ContractCapabilitiesError, match=trecho):
        derivations(_contrato(derivacoes=ruim))


def test_field_type_le_descritor_atraves_de_arrays():
    assert field_type(SCHEMA, "serie.dados.valores.valor") == "number | null"
    assert field_type(SCHEMA, "serie.dados.valores.periodo") == "string"
    assert field_type(SCHEMA, "serie.tipo") is None  # literal, nao descritor
    assert field_type(SCHEMA, "nao.existe") is None


def _saida_vazia():
    return {
        "fonte": None,
        "instituicao": None,
        "periodo_referencia": None,
        "periodos_disponiveis": {"periodo_referencia": None},
        "serie": {
            "tipo": "valor_bruto",
            "dados": [
                {"instituicao": None, "indicador": "npl", "valores": [{"periodo": "2T26", "escopo_periodo": None, "valor": 1.9}]},
                {"instituicao": "ja preenchida", "indicador": "roe", "valores": []},
            ],
        },
    }


def test_derivacoes_de_contrato_manifesto_e_wildcard_preenchem_so_nulos():
    contrato = _contrato(
        derivacoes=[
            {"destino": "fonte", "origem": {"tipo": "contrato", "campo": "fonte"}},
            {"destino": "instituicao", "origem": {"tipo": "manifesto", "campo": "candidate.entity_name"}},
            {"destino": "serie.dados[*].instituicao", "origem": {"tipo": "manifesto", "campo": "candidate.entity_name"}},
            {"destino": "periodo_referencia", "origem": {"tipo": "manifesto", "campo": "candidate.period_label"}},
            {"destino": "periodos_disponiveis.periodo_referencia", "origem": {"tipo": "manifesto", "campo": "candidate.ausente"}},
        ]
    )
    saida = _saida_vazia()
    auditoria = apply_derivations(
        saida,
        derivations(contrato),
        contract=contrato,
        manifest={"candidate": {"entity_name": "Banco X", "period_label": "2T26"}},
        resolved_by_path={},
    )
    assert saida["fonte"] == "Fonte declarada"
    assert saida["instituicao"] == "Banco X"
    assert saida["periodo_referencia"] == "2T26"
    assert saida["serie"]["dados"][0]["instituicao"] == "Banco X"
    assert saida["serie"]["dados"][1]["instituicao"] == "ja preenchida"
    assert saida["periodos_disponiveis"]["periodo_referencia"] is None
    por_destino = {item["destino"]: item for item in auditoria}
    assert por_destino["serie.dados[*].instituicao"]["destinos_escritos"] == 1
    assert por_destino["periodos_disponiveis.periodo_referencia"]["status"] == "sem_origem"


def test_derivacao_de_observacao_reproduz_a_regra_de_construtoras():
    contrato = _contrato(
        derivacoes=[
            {
                "destino": "periodo_referencia",
                "origem": {"tipo": "observacao", "seletor": {"papel_periodo": "referencia"}, "campo": "periodo"},
            }
        ]
    )
    saida = _saida_vazia()
    resolved = {
        "serie.dados[indicador=a].valores[papel_periodo=referencia].periodo": "1T26",
        "serie.dados[indicador=b].valores[papel_periodo=referencia]": {"periodo": "1T26", "valor": 3},
        "serie.dados[indicador=a].valores[papel_periodo=anterior].periodo": "4T25",
    }
    auditoria = apply_derivations(saida, derivations(contrato), contract=contrato, manifest=None, resolved_by_path=resolved)
    assert saida["periodo_referencia"] == "1T26"
    assert auditoria[0]["status"] == "derivado"


def test_observacao_divergente_avisa_e_nao_preenche():
    contrato = _contrato(
        derivacoes=[
            {"destino": "periodo_referencia", "origem": {"tipo": "observacao", "seletor": {"p": "r"}, "campo": "periodo"}}
        ]
    )
    saida = _saida_vazia()
    resolved = {"serie.dados[i=a].valores[p=r].periodo": "1T26", "serie.dados[i=b].valores[p=r].periodo": "2T26"}
    auditoria = apply_derivations(saida, derivations(contrato), contract=contrato, manifest=None, resolved_by_path=resolved)
    assert saida["periodo_referencia"] is None
    assert auditoria[0]["status"] == "divergente"
    assert auditoria[0]["valor"] == ["1T26", "2T26"]


def test_derivation_payload_reproduz_a_declaracao():
    d = Derivation("x", "observacao", "periodo", (("papel_periodo", "referencia"),))
    assert d.payload() == {
        "destino": "x",
        "origem": {"tipo": "observacao", "campo": "periodo", "seletor": {"papel_periodo": "referencia"}},
    }
