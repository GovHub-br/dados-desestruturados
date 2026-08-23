from __future__ import annotations

import unittest

from document_processing.domain.contracts.mapping_requirements import (
    mapping_requirements_from_context,
)
from document_processing.domain.contracts.schema import apply_contract_literals
from document_processing.domain.layouts.paths import parse_mapping_path


class FoundationModulesTest(unittest.TestCase):
    """Caracteriza as regras puras migradas na fase inicial da reorganização."""

    def test_mapping_path_keeps_explicit_array_selector(self) -> None:
        parsed = parse_mapping_path("dados[empresa=Exemplo].valores[papel=atual].valor")

        self.assertEqual(parsed[0]["field"], "dados")
        self.assertEqual(parsed[0]["selector"], ("empresa", "Exemplo"))
        self.assertEqual(parsed[1]["selector"], ("papel", "atual"))
        self.assertEqual(parsed[2]["field"], "valor")

    def test_contract_literals_take_precedence_over_layout_values(self) -> None:
        result = apply_contract_literals(
            {"tipo": "valor_dinamico", "valor": 12},
            {"tipo": "valor_bruto", "valor": "number"},
        )

        self.assertEqual(result, {"tipo": "valor_bruto", "valor": 12})

    def test_mapping_requirements_preserve_optional_observation(self) -> None:
        context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [
                        {
                            "path": "metricas.dados.valores.valor",
                            "observacoes_obrigatorias": [
                                {
                                    "seletores": {"papel_periodo": "referencia"},
                                    "campos_contexto_obrigatorios": ["periodo"],
                                },
                                {
                                    "obrigatorio": False,
                                    "seletores": {"papel_periodo": "anterior"},
                                    "campos_contexto_obrigatorios": ["periodo"],
                                },
                            ],
                        }
                    ]
                }
            },
            "estrutura_schema_saida": {
                "paths_permitidos": [
                    "metricas.dados.valores.valor",
                    "metricas.dados.valores.periodo",
                ]
            },
        }

        requirements = mapping_requirements_from_context(context)

        self.assertEqual(len(requirements), 1)
        self.assertTrue(requirements[0].observations[0].required)
        self.assertFalse(requirements[0].observations[1].required)


if __name__ == "__main__":
    unittest.main()
