from __future__ import annotations

import json
import unittest
from pathlib import Path

from document_intelligence.application.use_cases.fallback.context_builder import (
    FallbackProblemContextBuilder,
)
from document_intelligence.domain.fallback.models import LayoutArtifactSelection


FIXTURES = Path(__file__).parents[2] / "fixtures" / "fallback"


class FallbackPayloadSnapshotsTest(unittest.TestCase):
    def test_initial_creation_payloads_keep_the_documented_shape(self) -> None:
        expected = json.loads((FIXTURES / "payload_shapes.json").read_text())
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {
                "document_id": "documento-exemplo",
                "execution_id": "execucao-exemplo",
            },
            "contrato_semantico_relevante": {
                "identificacao": {"dominio": "exemplo", "versao": "v1.0.0"},
                "contrato_semantico": {
                    "entidades": {},
                    "metricas": {},
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {"path": "observacoes.valor"}
                        ]
                    },
                },
                "estrutura_schema_saida": {
                    "paths_permitidos": ["observacoes.valor"],
                    "arrays_que_exigem_seletor": [],
                },
            },
            "inventario_extracao": {"resumo": {"items": []}},
        }

        payloads = FallbackProblemContextBuilder().build_llm_payloads(context)
        expected_shapes = expected["criacao_inicial_layout"]

        self.assertEqual(
            sorted(payloads["artifact_selection"]),
            expected_shapes["artifact_selection"],
        )
        self.assertEqual(
            sorted(payloads["candidate_generation"]),
            expected_shapes["candidate_generation"],
        )

    def test_selection_response_fixture_remains_compatible_with_domain_contract(self) -> None:
        response = json.loads((FIXTURES / "llm_selection_response.json").read_text())

        selection = LayoutArtifactSelection.model_validate(response)

        self.assertEqual(selection.artifact_paths[0].path, "tables/table001.json")
        self.assertEqual(
            selection.artifact_paths[0].coberturas[0].campo_saida,
            "observacoes.valor",
        )


if __name__ == "__main__":
    unittest.main()
