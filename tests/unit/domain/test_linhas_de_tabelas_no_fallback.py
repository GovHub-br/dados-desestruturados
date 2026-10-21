"""O fallback precisa poder pedir uma colecao que o documento publica em varias tabelas.

O resolvedor da DAG 2 ja le ``linhas_de_tabelas`` (uma instrucao com ``fontes``, uma por
tabela fisica), mas o candidato da LLM recusava o tipo. Na ABECIP, depois que o Docling
passou a separar a pagina das modalidades em tres tabelas, a LLM so conseguiu mapear uma
delas e publicou 11 de 30 linhas sem nenhum alarme (lote 13 do registro de releases).
"""

from __future__ import annotations

import pytest

from document_processing.domain.contracts.mapping_requirements import TIPOS_DE_EVIDENCIA
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.models import (
    CanonicalMappingEntry,
    LayoutSignatureCandidate,
)

_validar_tabelas = FallbackCandidateValidationService._validate_table_mappings_use_indices_only
_tem_filtro_ou_colecao = FallbackCandidateValidationService._mapping_path_has_required_array_selectors

COLECAO = "grupo.por_modalidade"
SCHEMA_PATHS = {
    f"{COLECAO}.instituicao",
    f"{COLECAO}.volume",
    f"{COLECAO}.modalidade",
}
CAMPOS = [
    {"caminho_saida": "instituicao", "indice_coluna": 0, "tipo": "texto"},
    {"caminho_saida": "volume", "indice_coluna": 1, "tipo": "numero"},
]


def _fonte(arquivo="tables/table005.json", **extra):
    fonte = {
        "arquivo_origem": arquivo,
        "linha_inicial": 0,
        "linha_final": 8,
        "valores_por_segmento": {"modalidade": "construcao"},
        "campos": CAMPOS,
    }
    fonte.update(extra)
    return fonte


def _candidato(entrada: dict) -> LayoutSignatureCandidate:
    return LayoutSignatureCandidate.model_validate(
        {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc",
            "execution_id_origem": "exec",
            "mapeamento_canonico": {COLECAO: entrada},
        }
    )


def _linhas_de_tabelas(*fontes) -> dict:
    return {"tipo_origem": "linhas_de_tabelas", "obrigatorio": True, "fontes": list(fontes)}


def test_o_modelo_do_candidato_aceita_o_tipo_de_varias_tabelas():
    CanonicalMappingEntry.model_validate(_linhas_de_tabelas(_fonte()))
    assert "linhas_de_tabelas" in TIPOS_DE_EVIDENCIA


def test_varias_fontes_validas_passam():
    candidato = _candidato(
        _linhas_de_tabelas(
            _fonte("tables/table005.json"),
            _fonte("tables/table006.json", valores_por_segmento={"modalidade": "aquisicao"}),
        )
    )
    _validar_tabelas(candidato, schema_paths=SCHEMA_PATHS)


@pytest.mark.parametrize("fontes", [None, [], "tables/table005.json", [None]])
def test_sem_fontes_validas_e_reprovado(fontes):
    entrada = {"tipo_origem": "linhas_de_tabelas", "obrigatorio": True}
    if fontes is not None:
        entrada["fontes"] = fontes
    with pytest.raises(RuntimeError) as excecao:
        _validar_tabelas(_candidato(entrada), schema_paths=SCHEMA_PATHS)
    assert "linhas_de_tabelas" in str(excecao.value)
    assert "fontes" in str(excecao.value)


def test_fonte_sem_arquivo_e_reprovada():
    fonte = _fonte()
    del fonte["arquivo_origem"]
    with pytest.raises(RuntimeError) as excecao:
        _validar_tabelas(_candidato(_linhas_de_tabelas(fonte)), schema_paths=SCHEMA_PATHS)
    assert "arquivo_origem" in str(excecao.value)


def test_fonte_sem_campos_nem_indices_e_reprovada():
    with pytest.raises(RuntimeError) as excecao:
        _validar_tabelas(
            _candidato(_linhas_de_tabelas(_fonte(campos=[]))), schema_paths=SCHEMA_PATHS
        )
    assert "campos nomeados" in str(excecao.value)


def test_campo_de_uma_fonte_segue_as_mesmas_regras_da_linhas_de_tabela():
    """Chave nao suportada e caminho fora do schema valem em cada fonte, nao so no topo."""
    invalido = [{"caminho_saida": "instituicao", "indice_coluna": 0, "nome": "x"}]
    with pytest.raises(RuntimeError) as excecao:
        _validar_tabelas(
            _candidato(_linhas_de_tabelas(_fonte(), _fonte("tables/table006.json", campos=invalido))),
            schema_paths=SCHEMA_PATHS,
        )
    assert "chaves nao suportadas" in str(excecao.value)

    fora = [{"caminho_saida": "inexistente", "indice_coluna": 0}]
    with pytest.raises(RuntimeError) as excecao:
        _validar_tabelas(
            _candidato(_linhas_de_tabelas(_fonte(campos=fora))), schema_paths=SCHEMA_PATHS
        )
    assert "nao pertence ao item" in str(excecao.value)


def test_a_linhas_de_tabela_de_um_arquivo_continua_valida_como_antes():
    entrada = {
        "tipo_origem": "linhas_de_tabela",
        "arquivo_origem": "tables/table007.json",
        "faixas_linhas": [{"linha_inicial": 0, "linha_final": 11}],
        "campos": CAMPOS,
        "obrigatorio": True,
    }
    _validar_tabelas(_candidato(entrada), schema_paths=SCHEMA_PATHS)


def test_colecao_inteira_por_varias_tabelas_nao_exige_filtro_no_path():
    """Como na linhas_de_tabela: o path da colecao entra sem [chave=valor]."""
    array_paths = {COLECAO}
    for tipo in ("linhas_de_tabela", "linhas_de_tabelas"):
        assert _tem_filtro_ou_colecao(COLECAO, array_paths, mapping_entry={"tipo_origem": tipo}) is True
    assert _tem_filtro_ou_colecao(COLECAO, array_paths, mapping_entry={"tipo_origem": "celula_de_tabela"}) is False


# --- o que a LLM le: texto dos blocos e exemplo de formato -------------------


def test_os_tres_blocos_que_descrevem_colecoes_citam_o_tipo_de_varias_tabelas():
    from document_processing.application.use_cases.fallback.candidate_prompts import (
        candidate_contract_instruction,
    )
    from document_processing.application.use_cases.fallback.unit_mapping_prompts import (
        unit_mapping_artifacts_instruction,
        unit_mapping_structure_instruction,
    )

    for texto in (
        unit_mapping_structure_instruction(),
        unit_mapping_artifacts_instruction(),
        candidate_contract_instruction(),
    ):
        assert "linhas_de_tabelas" in texto
    estrutura = unit_mapping_structure_instruction()
    assert "mais de uma tabela" in estrutura and "fontes" in estrutura
    # a regra antiga continua dita: uma tabela so -> linhas_de_tabela.
    assert "unica tabela" in estrutura


def test_o_exemplo_de_formato_traz_o_tipo_e_passa_no_proprio_validador():
    from document_processing.application.use_cases.fallback.unit_mapping_prompts import (
        unit_mapping_structure_example,
    )

    exemplo = unit_mapping_structure_example(unit_id="u")
    assert "linhas_de_tabelas" in exemplo["tipos_origem_permitidos"]
    formato = exemplo["formatos_de_origem"]["linhas_de_tabelas"]
    assert len(formato["fontes"]) >= 2
    candidato = _candidato(formato)
    schema = {f"{COLECAO}.identificador", f"{COLECAO}.valor"}
    _validar_tabelas(candidato, schema_paths=schema)


# --- o caminho inteiro com o contrato real da ABECIP --------------------------


def _contexto_abecip():
    import json
    from pathlib import Path

    from document_processing.application.use_cases.fallback.context_builder import (
        FallbackProblemContextBuilder,
    )

    caminho = next(Path("infra/minio-bootstrap/contracts/abecip/v2.3.0").glob("*.json"))
    contrato = json.loads(caminho.read_text(encoding="utf-8"))
    builder = FallbackProblemContextBuilder()
    contexto = {
        "escopo_permitido": "criacao_inicial_layout",
        "fallback_context": {"document_id": "doc", "execution_id": "exec", "manifest_key": "m", "entity_slug": "abecip"},
        "contrato_semantico_relevante": builder._relevant_contract_context(contract=contrato, broken_fields=[]),
        "inventario_extracao": {"resumo": {"items": []}},
        "identidade_documento": {"entidade": "abecip", "entidade_nome": "ABECIP", "periodo": "2026-05"},
        "_paths_fixos_do_contrato": [],
        "layout_signature_base_ref": None,
    }
    contexto["llm_payloads"] = builder.build_llm_payloads(contexto)
    return contexto


def _tabela(arquivo, caminhos_colunas, fim=11, segmento=None):
    entrada = {
        "tipo_origem": "linhas_de_tabela",
        "arquivo_origem": arquivo,
        "faixas_linhas": [{"linha_inicial": 0, "linha_final": fim}],
        "campos": [
            {"caminho_saida": c, "indice_coluna": i, "tipo": "numero" if i else "texto"}
            for i, c in enumerate(caminhos_colunas)
        ],
        "obrigatorio": True,
    }
    return entrada


def _candidato_abecip(modalidade: dict) -> dict:
    periodo = "periodo.rotulo_publicado"
    return {
        "tipo_artefato": "layout_signature_candidato",
        "status_layout": "candidato",
        "escopo_correcao": "criacao_inicial_layout",
        "document_id": "doc",
        "execution_id_origem": "exec",
        "base_layout_signature": None,
        "fontes_relevantes": {},
        "regras_deteccao_mudanca": [],
        "campos_nao_mapeados": [],
        "metadados_estruturais_evidencia": {},
        "mapeamento_canonico": {
            "financiamentos_imobiliarios.serie_mensal_sbpe": _tabela(
                "tables/table003.json", [periodo, "unidades_financiadas", "volume_financiado_milhoes"]
            ),
            "financiamentos_imobiliarios.serie_historica_anual": _tabela(
                "tables/table004.json", [periodo, "unidades_financiadas", "volume_financiado_milhoes"]
            ),
            "financiamentos_imobiliarios.por_modalidade_e_instituicao": modalidade,
            "poupanca_sbpe.saldos_mensais": _tabela("tables/table002.json", [periodo, "saldo_milhoes"]),
            "poupanca_sbpe.captacoes_liquidas_mensais": _tabela(
                "tables/table002.json", [periodo, "captacao_liquida_milhoes"]
            ),
        },
    }


def _fonte_abecip(arquivo, modalidade, fim):
    return {
        "arquivo_origem": arquivo,
        "linha_inicial": 0,
        "linha_final": fim,
        "valores_por_segmento": {"modalidade": modalidade},
        "campos": [
            {"caminho_saida": "instituicao_financeira", "indice_coluna": 0, "tipo": "texto"},
            {"caminho_saida": "volume_mensal_milhoes", "indice_coluna": 1, "tipo": "numero"},
            {"caminho_saida": "unidades_mensais", "indice_coluna": 2, "tipo": "numero"},
        ],
    }


def test_candidato_da_abecip_com_a_pagina_das_modalidades_em_tres_tabelas_passa_no_validador_completo():
    contexto = _contexto_abecip()
    modalidade = _linhas_de_tabelas(
        _fonte_abecip("tables/table005.json", "construcao", 8),
        _fonte_abecip("tables/table006.json", "aquisicao", 9),
        _fonte_abecip("tables/table007.json", "total", 10),
    )
    modelo = FallbackCandidateValidationService().validate_candidate_layout(_candidato_abecip(modalidade), contexto)
    entrada = modelo.mapeamento_canonico["financiamentos_imobiliarios.por_modalidade_e_instituicao"]
    assert entrada.tipo_origem == "linhas_de_tabelas"


def test_o_mesmo_candidato_com_campo_fora_do_schema_numa_das_fontes_e_recusado_com_a_causa():
    contexto = _contexto_abecip()
    ruim = _fonte_abecip("tables/table006.json", "aquisicao", 9)
    ruim["campos"][1]["caminho_saida"] = "volume_inventado"
    modalidade = _linhas_de_tabelas(_fonte_abecip("tables/table005.json", "construcao", 8), ruim)
    with pytest.raises(RuntimeError, match="volume_inventado"):
        FallbackCandidateValidationService().validate_candidate_layout(_candidato_abecip(modalidade), contexto)
