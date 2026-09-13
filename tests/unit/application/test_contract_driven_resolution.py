"""Bifurcacao generico/legado dirigida por ``chaves_de_item``.

O mesmo ``resolved_cell`` e o mesmo path produzem resultados diferentes conforme
o contrato declare ou nao como identificar seus itens. O legado (construtoras)
precisa sair identico ao que saia antes; o generico nao pode nomear campo nenhum.
"""

from __future__ import annotations

import pytest

from document_processing.application.use_cases.resolution.contract_semantic_helpers import (
    ContractSemanticHelpersMixin,
)
from document_processing.application.use_cases.resolution.source_mapping_resolvers import (
    SourceMappingResolversMixin,
)
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)

SCHEMA = {
    "serie": {
        "tipo": "valor_bruto",
        "dados": [
            {
                "indicador": "string",
                "valores": [{"periodo": "string", "escopo_periodo": "string", "valor": "number | null"}],
            }
        ],
    }
}
LEGADO = {"schema_saida": SCHEMA, "contrato_semantico": {}}
GENERICO = {
    "schema_saida": SCHEMA,
    "contrato_semantico": {
        "chaves_de_item": {"serie.dados": "indicador", "serie.dados.valores": "periodo"},
        "metricas": {
            "grupo": {
                "tipo": "grupo_metricas_brutas",
                "indicadores": {
                    "resultado_recorrente": {"sinonimos": ["Lucro Liquido Recorrente", "lucro recorrente"]},
                    "carteira_de_credito": {"sinonimos": ["Carteira ampliada"]},
                },
            }
        },
    },
}
CELULA = {"periodo": "2T26", "escopo_periodo": "trimestre", "valor": 3014.0}
_projetar = SourceMappingResolversMixin._project_table_cell_value


# --- projecao da celula -----------------------------------------------------


def test_legado_mantem_observacao_inteira_e_cabecalho_por_nome():
    base = "serie.dados[indicador=x].valores[papel_periodo=ref]"
    assert _projetar(mapping_path=base, resolved_cell=CELULA, raw_value="3.014", contrato=LEGADO) == CELULA
    assert _projetar(mapping_path=f"{base}.periodo", resolved_cell=CELULA, raw_value="3.014", contrato=LEGADO) == "2T26"
    assert _projetar(mapping_path=f"{base}.valor", resolved_cell=CELULA, raw_value="3.014", contrato=LEGADO) == 3014.0
    assert _projetar(mapping_path=f"{base}.outro", resolved_cell=CELULA, raw_value="3.014", contrato=LEGADO) == "3.014"


def test_sem_contrato_e_o_mesmo_que_legado():
    base = "serie.dados[indicador=x].valores[papel_periodo=ref]"
    assert _projetar(mapping_path=base, resolved_cell=CELULA, raw_value="3.014") == CELULA


def test_generico_decide_pelo_tipo_da_folha_no_contrato():
    base = "serie.dados[indicador=x].valores[periodo=2T26]"
    assert _projetar(mapping_path=f"{base}.valor", resolved_cell=CELULA, raw_value="3.014", contrato=GENERICO) == 3014.0
    # ``periodo`` e string no contrato: a celula vira texto bruto, nao o cabecalho.
    assert _projetar(mapping_path=f"{base}.periodo", resolved_cell=CELULA, raw_value="3.014", contrato=GENERICO) == "3.014"
    assert _projetar(mapping_path=f"{base}.valor", resolved_cell={"valor": None}, raw_value=None, contrato=GENERICO) is None


def test_generico_recusa_observacao_inteira():
    with pytest.raises(RuntimeError, match="termina no array"):
        _projetar(
            mapping_path="serie.dados[indicador=x].valores[periodo=2T26]",
            resolved_cell=CELULA,
            raw_value="3.014",
            contrato=GENERICO,
        )


# --- contexto semantico -----------------------------------------------------


class _Helper(ContractSemanticHelpersMixin):
    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(str(value).lower().split())


def test_generico_expande_sinonimos_somente_do_indicador_selecionado():
    aceitos = _Helper()._expand_accepted_labels_from_contract(
        contrato=GENERICO,
        values=["Lucro líquido recorrente"],
        mapping_path="serie.dados[indicador=resultado_recorrente].valores[periodo=2T26].valor",
        resolved_by_path={},
    )
    assert "lucro recorrente" in aceitos
    assert "lucro liquido recorrente" in aceitos
    assert "carteira ampliada" not in aceitos


def test_legado_nao_le_seletores_do_path():
    """No legado o contexto vem de campos irmaos resolvidos; o seletor nao basta."""
    aceitos = _Helper()._expand_accepted_labels_from_contract(
        contrato={**LEGADO, "contrato_semantico": GENERICO["contrato_semantico"] | {"chaves_de_item": {}}},
        values=["Lucro líquido recorrente"],
        mapping_path="serie.dados[indicador=resultado_recorrente].valores[periodo=2T26].valor",
        resolved_by_path={},
    )
    assert aceitos == {"lucro líquido recorrente"}


# --- chave de item no validador ---------------------------------------------

_violacao = FallbackCandidateValidationService._describe_item_key_violation
CHAVES = {"serie.dados": "indicador", "serie.dados.valores": "periodo"}


def test_sem_chaves_declaradas_nada_e_verificado():
    assert _violacao("serie.dados[x=1].valores[indicador=2].valor", {}) is None


def test_chave_de_outro_array_e_nomeada():
    mensagem = _violacao("serie.dados[indicador=npl].valores[indicador=npl].valor", CHAVES)
    assert "identificado por 'periodo'" in mensagem
    assert "'indicador' identifica serie.dados" in mensagem


def test_chave_desconhecida_e_nomeada():
    mensagem = _violacao("serie.dados[indicador=npl].valores[papel=ref].valor", CHAVES)
    assert "nao identifica nenhum array declarado" in mensagem


def test_observacao_inteira_e_recusada_com_chaves():
    mensagem = _violacao("serie.dados[indicador=npl].valores[periodo=2T26]", CHAVES)
    assert "termina no array serie.dados.valores" in mensagem


def test_path_correto_passa():
    assert _violacao("serie.dados[indicador=npl].valores[periodo=2T26].valor", CHAVES) is None
    assert _violacao("serie.dados", CHAVES) is None  # colecao inteira por linhas_de_tabela


def test_validador_de_candidato_aplica_a_chave_do_contexto():
    candidato = {
        "tipo_artefato": "layout_signature_candidato",
        "status_layout": "candidato",
        "escopo_correcao": "criacao_inicial_layout",
        "document_id": "doc",
        "execution_id_origem": "exec",
        "mapeamento_canonico": {
            "serie.dados[indicador=npl].valores[indicador=npl].valor": {"tipo_origem": "valor_fixo", "valor_fixo": 1}
        },
    }
    contexto = {
        "contrato_semantico_relevante": {
            "estrutura_schema_saida": {
                "campos_raiz": ["serie"],
                "paths_permitidos": ["serie.dados.valores.valor"],
                "arrays_que_exigem_seletor": ["serie.dados", "serie.dados.valores"],
                "chaves_de_item": CHAVES,
            }
        }
    }
    with pytest.raises(RuntimeError, match="identificado por 'periodo'"):
        FallbackCandidateValidationService().validate_candidate_layout(candidato, contexto)
