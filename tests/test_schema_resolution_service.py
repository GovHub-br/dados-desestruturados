from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from document_processing.application.use_cases.resolution.resolve_schema import SchemaResolutionService
from document_processing.domain.contracts.schema import apply_contract_literals


def test_schema_template_keeps_contract_literals_and_nulls_type_descriptors() -> None:
    schema = SchemaResolutionService._build_schema_template(
        {
            "titulo": "string",
            "tipo": "valor_bruto",
            "tipo_operacao": "lancamento",
            "indicador": "numero_de_unidades",
            "unidade": "unidades",
            "valor": "number | null",
        }
    )

    assert schema == {
        "titulo": None,
        "tipo": "valor_bruto",
        "tipo_operacao": "lancamento",
        "indicador": "numero_de_unidades",
        "unidade": "unidades",
        "valor": None,
    }


def test_contract_literals_override_redundant_layout_values() -> None:
    resolved = apply_contract_literals(
        {
            "tipo_operacao": "venda",
            "unidade": "milhares",
            "valor": 10,
        },
        {
            "tipo_operacao": "lancamento",
            "unidade": "unidades",
            "valor": "number",
        },
    )

    assert resolved == {
        "tipo_operacao": "lancamento",
        "unidade": "unidades",
        "valor": 10,
    }


def test_contract_value_enumerations_do_not_override_resolved_values() -> None:
    resolved = apply_contract_literals(
        {"modalidade": "aquisicao", "tipo_periodo": "acumulado_ano"},
        {
            "modalidade": "construcao | aquisicao | total",
            "tipo_periodo": "mensal | acumulado_ano",
        },
    )

    assert resolved == {
        "modalidade": "aquisicao",
        "tipo_periodo": "acumulado_ano",
    }


def test_resolution_ignores_layout_mapping_for_contract_literal() -> None:
    with TemporaryDirectory() as directory:
        resolved = SchemaResolutionService().resolve_canonical_mapping(
            loaded={
                "contrato_semantico": {
                    "schema_saida": {
                        "medida": {"unidade": "unidades", "valor": "number"}
                    }
                },
                "layout_signature": {
                    "mapeamento_canonico": {
                        "medida.unidade": {
                            "tipo_origem": "valor_fixo",
                            "valor_fixo": "milhares",
                        },
                        "medida.valor": {
                            "tipo_origem": "valor_fixo",
                            "valor_fixo": 10,
                        },
                    }
                },
                "extraction_root": Path(directory),
            },
            validation={"status_compatibilidade": {"status": "compativel"}},
        )

    assert resolved["schema_saida"] == {"medida": {"unidade": "unidades", "valor": 10}}
    fixed_audit = resolved["auditoria_resolucao"][0]
    assert fixed_audit["evidencia"] == {
        "origem": "literal_do_contrato_semantico",
        "mapeamento_ignorado": True,
    }


def test_root_periods_come_only_from_declared_derivations() -> None:
    """Sem ``derivacoes`` o codigo nao adivinha campos de raiz; com elas, preenche."""
    from document_processing.domain.contracts.capabilities import apply_derivations, derivations

    schema_template = {
        "periodo_referencia": "string",
        "periodos_disponiveis": {
            "periodo_referencia": "string",
            "periodo_comparativo_anterior": "string | null",
            "mesmo_periodo_ano_anterior": "string | null",
        },
        "grupo": {"dados": [{"empresa": "string", "valores": [{"periodo": "string"}]}]},
    }
    resolved_by_path = {
        "grupo.dados[empresa=Cury].valores[papel_periodo=periodo_referencia].periodo": "2T26",
        "grupo.dados[empresa=Cury].valores[papel_periodo=periodo_comparativo_anterior].periodo": "1T26",
        "grupo.dados[empresa=Cury].valores[papel_periodo=mesmo_periodo_ano_anterior].periodo": "2T25",
    }

    def fresh() -> dict:
        return {
            "periodo_referencia": None,
            "periodos_disponiveis": {
                "periodo_referencia": None,
                "periodo_comparativo_anterior": None,
                "mesmo_periodo_ano_anterior": None,
            },
        }

    sem_derivacoes = {"schema_saida": schema_template}
    schema_saida = fresh()
    apply_derivations(
        schema_saida,
        derivations(sem_derivacoes),
        contract=sem_derivacoes,
        manifest={},
        resolved_by_path=resolved_by_path,
    )
    assert schema_saida == fresh()

    def observacao(papel: str) -> dict:
        return {"tipo": "observacao", "campo": "periodo", "seletor": {"papel_periodo": papel}}

    com_derivacoes = {
        "schema_saida": schema_template,
        "contrato_semantico": {
            "derivacoes": [
                {"destino": "periodo_referencia", "origem": observacao("periodo_referencia")},
                {"destino": "periodos_disponiveis.periodo_referencia", "origem": observacao("periodo_referencia")},
                {"destino": "periodos_disponiveis.periodo_comparativo_anterior", "origem": observacao("periodo_comparativo_anterior")},
                {"destino": "periodos_disponiveis.mesmo_periodo_ano_anterior", "origem": observacao("mesmo_periodo_ano_anterior")},
            ]
        },
    }
    schema_saida = fresh()
    apply_derivations(
        schema_saida,
        derivations(com_derivacoes),
        contract=com_derivacoes,
        manifest={},
        resolved_by_path=resolved_by_path,
    )
    assert schema_saida["periodo_referencia"] == "2T26"
    assert schema_saida["periodos_disponiveis"] == {
        "periodo_referencia": "2T26",
        "periodo_comparativo_anterior": "1T26",
        "mesmo_periodo_ano_anterior": "2T25",
    }


def test_resolves_rows_from_multiple_table_sources() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "tables").mkdir()
        (root / "tables" / "construcao.json").write_text(
            '{"rows":[["Banco A","10"]]}', encoding="utf-8"
        )
        (root / "tables" / "aquisicao.json").write_text(
            '{"rows":[["Banco B","20"]]}', encoding="utf-8"
        )
        resolved = SchemaResolutionService().resolve_canonical_mapping(
            loaded={
                "contrato_semantico": {"schema_saida": {"itens": [{"banco": "string", "valor": "number"}]}},
                "layout_signature": {
                    "mapeamento_canonico": {
                        "itens": {
                            "tipo_origem": "linhas_de_tabelas",
                            "fontes": [
                                {
                                    "arquivo_origem": "tables/construcao.json",
                                    "linha_inicial": 0,
                                    "linha_final": 0,
                                    "valores_por_segmento": {"modalidade": "construcao"},
                                    "campos": [
                                        {"nome": "banco", "indice_coluna": 0},
                                        {"nome": "valor", "indice_coluna": 1, "tipo": "numero"},
                                    ],
                                },
                                {
                                    "arquivo_origem": "tables/aquisicao.json",
                                    "linha_inicial": 0,
                                    "linha_final": 0,
                                    "valores_por_segmento": {"modalidade": "aquisicao"},
                                    "campos": [
                                        {"nome": "banco", "indice_coluna": 0},
                                        {"nome": "valor", "indice_coluna": 1, "tipo": "numero"},
                                    ],
                                },
                            ],
                        }
                    }
                },
                "extraction_root": root,
            },
            validation={"status_compatibilidade": {"status": "compativel"}},
        )

    assert resolved["schema_saida"]["itens"] == [
        {"banco": "Banco A", "valor": 10.0, "modalidade": "construcao"},
        {"banco": "Banco B", "valor": 20.0, "modalidade": "aquisicao"},
    ]


def test_normalizes_declared_text_replacements_in_table_rows() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "tables").mkdir()
        (root / "tables" / "serie.json").write_text(
            '{"rows":[["1no","10"]]}', encoding="utf-8"
        )
        resolved = SchemaResolutionService().resolve_canonical_mapping(
            loaded={
                "contrato_semantico": {"schema_saida": {"itens": [{"mes": "string", "valor": "number"}]}},
                "layout_signature": {"mapeamento_canonico": {"itens": {
                    "tipo_origem": "linhas_de_tabela",
                    "arquivo_origem": "tables/serie.json",
                    "linha_inicial": 0,
                    "linha_final": 0,
                    "campos": [
                        {"nome": "mes", "indice_coluna": 0, "substituicoes": {"1no": "Out"}},
                        {"nome": "valor", "indice_coluna": 1, "tipo": "numero"},
                    ],
                }}},
                "extraction_root": root,
            },
            validation={"status_compatibilidade": {"status": "compativel"}},
        )

    assert resolved["schema_saida"]["itens"] == [{"mes": "Out", "valor": 10.0}]


class SchemaResolutionServiceTest(unittest.TestCase):
    """Espelhos unittest para o ambiente Airflow, que nao instala pytest."""

    def test_schema_template_keeps_contract_literals(self) -> None:
        test_schema_template_keeps_contract_literals_and_nulls_type_descriptors()

    def test_contract_literals_override_redundant_layout_values(self) -> None:
        test_contract_literals_override_redundant_layout_values()

    def test_resolution_ignores_layout_mapping_for_contract_literal(self) -> None:
        test_resolution_ignores_layout_mapping_for_contract_literal()

    def test_root_periods_come_only_from_declared_derivations(self) -> None:
        test_root_periods_come_only_from_declared_derivations()

    def test_resolves_rows_from_multiple_table_sources(self) -> None:
        test_resolves_rows_from_multiple_table_sources()

    def test_normalizes_declared_text_replacements_in_table_rows(self) -> None:
        test_normalizes_declared_text_replacements_in_table_rows()
