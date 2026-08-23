from __future__ import annotations

import unittest
from typing import Any

from document_intelligence.application.use_cases.resolution import (
    ResolutionAuditBuilder,
    ResolutionOutputPublisher,
)


class _MemoryArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def put_json(self, *, object_key: str, payload: dict[str, Any]) -> str:
        self.items[object_key] = payload
        return f"minio://teste/{object_key}"


class ResolutionOutputsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loaded = {
            "runtime": {"dag_name": "dag_resolve_schema_saida"},
            "execution": {"execution_id": "run-1", "document_id": "doc-1"},
            "layout_signature": {"entidade": {"slug": "exemplo"}},
            "output_keys": {
                "validacao_layout_signature": "run/validacao.json",
                "schema_saida_resolvido": "run/schema.json",
                "auditoria_resolucao": "run/auditoria.json",
            },
        }
        self.validation = {"status_compatibilidade": {"status": "compativel"}}
        self.resolved = {
            "schema_saida": {"periodo_referencia": "2026-06-30"},
            "auditoria_resolucao": [
                {"status_resolucao": "resolvido"},
                {"status_resolucao": "nao_resolvido"},
            ],
        }

    def test_audit_builder_keeps_resolution_summary(self) -> None:
        audit = ResolutionAuditBuilder().build(
            loaded=self.loaded,
            validation=self.validation,
            resolved=self.resolved,
        )

        self.assertEqual(audit["summary"]["campos_mapeamento_resolvidos"], 1)
        self.assertEqual(audit["summary"]["campos_mapeamento_com_falha"], 1)
        self.assertEqual(audit["summary"]["entidade"], {"slug": "exemplo"})

    def test_output_publisher_writes_the_three_stable_artifacts(self) -> None:
        store = _MemoryArtifactStore()
        audit = ResolutionAuditBuilder().build(
            loaded=self.loaded,
            validation=self.validation,
            resolved=self.resolved,
        )

        persisted = ResolutionOutputPublisher(store).persist(  # type: ignore[arg-type]
            loaded=self.loaded,
            validation=self.validation,
            resolved=self.resolved,
            audit=audit,
        )

        self.assertEqual(len(store.items), 3)
        self.assertIn("run/schema.json", store.items)
        self.assertEqual(persisted["schema_saida_resolvido_uri"], "minio://teste/run/schema.json")


if __name__ == "__main__":
    unittest.main()
