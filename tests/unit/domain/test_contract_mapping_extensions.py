"""P1: chaves_de_item com origem do valor, papeis e evidencia_esperada."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from document_processing.domain.contracts.capabilities import (
    ContractCapabilitiesError,
    item_key_origins,
    item_key_specs,
    item_keys,
)
from document_processing.domain.contracts.mapping_requirements import (
    TIPOS_DE_EVIDENCIA,
    MappingRequirementsError,
    mapping_requirements_from_context,
    role_specs_from_context,
    roles_payload,
)
from document_processing.domain.fallback.models import SupportedMappingOrigin

CONTRATOS = Path("infra/minio-bootstrap/contracts")


def _contrato(chaves, requisitos=None):
    return {
        "schema_saida": {"g": {"dados": [{"k": "string", "valores": [{"periodo": "string", "valor": "number | null"}]}]}},
        "contrato_semantico": {
            "chaves_de_item": chaves,
            "requisitos_mapeamento": requisitos
            or {
                "campos_obrigatorios": [
                    {
                        "path": "g.dados.valores.valor",
                        "observacoes_obrigatorias": [
                            {"seletores": {"papel": "ref"}, "campos_contexto_obrigatorios": ["periodo"]},
                            {"seletores": {"papel": "ant"}, "campos_contexto_obrigatorios": ["periodo"], "obrigatorio": False},
                        ],
                    }
                ]
            },
        },
    }


def test_chaves_de_item_aceita_forma_curta_e_completa() -> None:
    contrato = _contrato({"g.dados": "k", "g.dados.valores": {"chave": "papel", "origem_valor": "seletor_observacao"}})
    assert item_keys(contrato) == {"g.dados": "k", "g.dados.valores": "papel"}
    assert item_key_origins(contrato) == {"g.dados.valores": "seletor_observacao"}
    assert item_key_specs(contrato)["g.dados"].origem_valor is None


def test_origem_valor_desconhecida_e_recusada() -> None:
    with pytest.raises(ContractCapabilitiesError, match="origem_valor"):
        item_key_specs(_contrato({"g.dados": {"chave": "k", "origem_valor": "adivinhar"}}))


def test_papeis_precisam_cobrir_os_seletores_usados() -> None:
    requisitos = _contrato({})["contrato_semantico"]["requisitos_mapeamento"]
    requisitos["papeis"] = {"papel": {"ref": {"descricao": "referencia"}}}
    with pytest.raises(MappingRequirementsError, match="nao declarados: \\['ant'\\]"):
        role_specs_from_context(_contrato({}, requisitos))
    requisitos["papeis"]["papel"]["ant"] = {"descricao": "anterior", "derivacao": {"relacao": "anterior", "passo": 1}}
    specs = role_specs_from_context(_contrato({}, requisitos))
    assert [spec.papel for spec in specs] == ["ref", "ant"]
    assert roles_payload(specs)["papel"]["ant"]["derivacao"] == {"relacao": "anterior", "passo": 1}


def test_papeis_de_seletor_inexistente_sao_recusados() -> None:
    requisitos = _contrato({})["contrato_semantico"]["requisitos_mapeamento"]
    requisitos["papeis"] = {"outro": {"x": {"descricao": "y"}}}
    with pytest.raises(MappingRequirementsError, match="nao e seletor"):
        role_specs_from_context(_contrato({}, requisitos))


def test_evidencia_esperada_valida_campo_e_tipo() -> None:
    requisitos = _contrato({})["contrato_semantico"]["requisitos_mapeamento"]
    campo = requisitos["campos_obrigatorios"][0]
    campo["evidencia_esperada"] = {"valor": "celula_de_tabela", "periodo": "cabecalho_de_tabela"}
    parsed = mapping_requirements_from_context(_contrato({}, requisitos), validate_schema_paths=False)
    assert parsed[0].evidencia_esperada == {"valor": "celula_de_tabela", "periodo": "cabecalho_de_tabela"}
    campo["evidencia_esperada"] = {"inexistente": "celula_de_tabela"}
    with pytest.raises(MappingRequirementsError, match="campo desconhecido"):
        mapping_requirements_from_context(_contrato({}, requisitos), validate_schema_paths=False)
    campo["evidencia_esperada"] = {"valor": "adivinhacao"}
    with pytest.raises(MappingRequirementsError, match="tipo_origem desconhecido"):
        mapping_requirements_from_context(_contrato({}, requisitos), validate_schema_paths=False)


def test_tipos_de_evidencia_espelham_o_modelo_do_layout() -> None:
    assert TIPOS_DE_EVIDENCIA == frozenset(get_args(SupportedMappingOrigin))


@pytest.mark.parametrize(
    "arquivo",
    [
        "construtoras/v1.9.0/contrato_semantico_construtora.json",
        "bancos/v2.2.0/contrato_semantico_bancos.json",
    ],
)
def test_contratos_publicados_declaram_as_extensoes(arquivo: str) -> None:
    contrato = json.loads((CONTRATOS / arquivo).read_text(encoding="utf-8"))
    assert item_key_origins(contrato), "todo array declara a origem do valor da chave"
    requisitos = mapping_requirements_from_context(contrato, validate_schema_paths=False)
    assert all(requisito.evidencia_esperada for requisito in requisitos)
    role_specs_from_context(contrato)
