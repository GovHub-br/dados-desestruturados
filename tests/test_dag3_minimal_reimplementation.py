from __future__ import annotations

import json
import unittest
from http.client import IncompleteRead
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from document_processing.application.use_cases.fallback.context_builder import (
    FallbackProblemContextBuilder,
)
from document_processing.application.use_cases.fallback.inventory import FallbackInventoryService
from document_processing.application.use_cases.fallback.prompts import (
    candidate_artifacts_instruction,
)
from document_processing.application.use_cases.fallback.service import FallbackLlmService
from document_processing.application.use_cases.resolution.resolve_schema import SchemaResolutionService
from document_processing.domain.contracts.mapping_requirements import (
    mapping_requirements_from_context,
    mapping_requirements_payload,
)
from document_processing.domain.fallback.artifact_selection_validation import (
    ArtifactSelectionValidationError,
    ArtifactSelectionValidationService,
)
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
    UnmappedRequiredFieldsError,
)
from document_processing.domain.fallback.mapping_plan import MappingPlanService
from document_processing.domain.fallback.models import (
    CanonicalMappingEntry,
    LayoutArtifactSelection,
    LayoutSignatureCandidate,
)
from document_processing.infrastructure.llm.client import FallbackLlmClient, FallbackLlmClientError
from document_processing.infrastructure.llm.http_client import HttpClient


class _ConfigLoader:
    def load_local_platform_config(self) -> SimpleNamespace:
        return SimpleNamespace(
            dominio="construtoras",
            minio_bucket="ocr-cidades",
            minio_layout_prefix="layouts/construtoras",
            fallback_llm_provider="openai",
            fallback_llm_model="fake-model",
        )


class _MinioRecorder:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def put_json(self, *, object_key: str, payload: dict[str, Any]) -> str:
        self.writes.append((object_key, payload))
        return f"minio://ocr-cidades/{object_key}"


class _MinioContracts:
    def __init__(self) -> None:
        self.objects = {
            "contratos/abecip/v2.0.1/contrato_semantico_abecip.json": {"versao": "2.0.1"},
            "contratos/abecip/v2.1.0/contrato_semantico_abecip.json": {"versao": "2.1.0"},
        }

    def list_object_keys(self, *, prefix: str, suffix: str | None = None) -> list[str]:
        return [
            key for key in self.objects
            if key.startswith(prefix) and (suffix is None or key.endswith(suffix))
        ]

    def get_json(self, *, object_key: str) -> dict[str, Any]:
        return self.objects[object_key]


class _RetryingLlm:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        *,
        system_prompt: str | None = None,
        user_payload: dict[str, Any] | None = None,
        messages: list[dict[str, str]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], str]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "messages": messages,
                "response_schema": response_schema,
            }
        )
        if len(self.calls) == 1:
            raise FallbackLlmClientError(
                "Conteudo da LLM nao e JSON valido.",
                raw_content='{"tipo_artefato": "layout_signature_candidato"',
            )
        parsed = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "correcao_parcial_mapeamento",
            "document_id": "doc-1",
            "execution_id_origem": "dag1__20260709T120000Z",
            "base_layout_signature": {
                "versao": "1.0.0",
                "object_key": "layouts/construtoras/cury/v1.0.0/layout_signature_deterministico.json",
            },
            "fontes_relevantes": {},
            "regras_deteccao_mudanca": [],
            "mapeamento_canonico": {
                "periodo_referencia": {
                    "tipo_origem": "valor_fixo",
                    "obrigatorio": True,
                }
            },
            "metadados_estruturais_evidencia": {},
            "publicacao_automatica_habilitada": True,
        }
        return parsed, '{"tipo_artefato":"layout_signature_candidato"}'


class _CandidateModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str, exclude_none: bool = False) -> dict[str, Any]:
        return self.payload


class _CandidateValidator:
    def validate_candidate_layout(
        self,
        candidate: dict[str, Any],
        fallback_problem_context: dict[str, Any],
    ) -> _CandidateModel:
        return _CandidateModel(candidate)


class _SelectionRetryingLlm:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        *,
        system_prompt: str | None = None,
        user_payload: dict[str, Any] | None = None,
        messages: list[dict[str, str]] | None = None,
        response_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], str]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "messages": messages,
                "response_schema": response_schema,
            }
        )
        path = "metrics/metrics.jsonl" if len(self.calls) == 1 else "tables/table002.json"
        return (
            {
                "tipo_artefato": "selecao_artefatos_layout",
                "artifact_paths": [
                    {
                        "path": path,
                        "motivo": "Fonte de unidades lancadas.",
                        "coberturas": [
                            {
                                "campo_saida": "balancos.lancamentos.dados.valores.valor",
                                "ancoras": ["Unidades lançadas"],
                            }
                        ],
                    }
                ],
            },
            '{"tipo_artefato":"selecao_artefatos_layout"}',
        )


class _SelectionSchemaRetryingLlm(_SelectionRetryingLlm):
    """Simula a troca indevida de campo_saida por campo na primeira resposta."""

    def generate_json(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
        parsed, raw = super().generate_json(**kwargs)
        if len(self.calls) == 1:
            coverage = parsed["artifact_paths"][0]["coberturas"][0]
            coverage["campo"] = coverage.pop("campo_saida")
            coverage.pop("ancoras")
        return parsed, raw


class _SelectionInventory:
    MAX_CHUNKS_PER_ARTIFACT = 8

    def load_selected_extraction_artifacts(
        self,
        *,
        manifest: dict[str, Any],
        artifact_paths: list[str],
        get_bytes: Any,
    ) -> dict[str, Any]:
        path = artifact_paths[0]
        text = "Outra metrica" if path.startswith("metrics/") else "Unidades lançadas"
        return {path: {"conteudo": text}}

    @staticmethod
    def enrich_selected_jsonl_anchor_evidence(
        *,
        loaded_artifacts: dict[str, Any],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return loaded_artifacts


class _BlockLlm:
    """Simula as duas chamadas de cada unidade sem depender de um dominio real."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, **kwargs: Any) -> tuple[dict[str, Any], str]:
        self.calls.append(kwargs)
        payload = kwargs.get("user_payload") or {}
        if not payload:
            messages = kwargs.get("messages") or []
            user_blocks = [
                message.get("content", "")
                for message in messages
                if message.get("role") == "user"
            ]
            for content in reversed(user_blocks):
                try:
                    candidate = json.loads(content)
                except json.JSONDecodeError:
                    continue
                if "unidade_mapeamento" in candidate:
                    payload = candidate
                    break
        unit = payload.get("unidade_mapeamento", {})
        unit_id = unit.get("id")
        if "inventario_extracao" in payload:
            field = unit["campos_saida"][0]
            anchor = "Financiamentos" if unit_id == "financiamentos" else "Poupanca"
            return {
                "tipo_artefato": "selecao_artefatos_layout",
                "artifact_paths": [{
                    "path": f"tables/{unit_id}.json",
                    "motivo": "Tabela da unidade.",
                    "coberturas": [{"campo_saida": field, "ancoras": [anchor]}],
                }],
            }, "{}"
        field = unit["campos_saida"][0]
        return {
            "tipo_artefato": "fragmento_layout_signature",
            "unidade_mapeamento": unit_id,
            "mapeamento_canonico": {
                field: {
                    "tipo_origem": "bloco_textual",
                    "arquivo_origem": f"tables/{unit_id}.json",
                }
            },
            "fontes_relevantes": {"arquivo": f"tables/{unit_id}.json"},
            "metadados_estruturais_evidencia": {},
        }, "{}"


class _BlockInventory(_SelectionInventory):
    def load_selected_extraction_artifacts(self, **kwargs: Any) -> dict[str, Any]:
        path = kwargs["artifact_paths"][0]
        anchor = "Financiamentos" if "financiamentos" in path else "Poupanca"
        return {path: {"conteudo": anchor}}


class Dag3MinimalReimplementationTest(unittest.TestCase):
    def test_inventory_summary_for_llm_selection_exposes_only_tables_and_charts(self) -> None:
        inventory = FallbackInventoryService()

        summary = inventory.inventory_summary(
            {
                "summary": {"tables": 1, "charts": 1, "blocks": 1},
                "collections": {
                    "tables": "tables/metadata.json",
                    "charts": "charts/metadata.json",
                    "blocks": "blocks/metadata.json",
                },
                "items": [
                    {"kind": "table", "path": "tables/table001.json"},
                    {"kind": "chart", "path": "charts/chart001.json"},
                    {"kind": "block", "path": "blocks/blocks.jsonl"},
                ],
            },
            full=True,
        )

        self.assertEqual(
            [item["path"] for item in summary["items"]],
            ["tables/table001.json", "charts/chart001.json"],
        )
        self.assertEqual(summary["collections"], {
            "charts": "charts/metadata.json",
            "tables": "tables/metadata.json",
        })
        self.assertEqual(summary["summary"], {"charts": 1, "tables": 1})

    def test_creation_with_multiple_roots_uses_deterministic_mapping_units(self) -> None:
        minio = _MinioRecorder()
        llm = _BlockLlm()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
            llm_client=llm,  # type: ignore[arg-type]
            inventory_service=_BlockInventory(),  # type: ignore[arg-type]
        )
        contract_context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [
                        {"path": "financiamentos.valor"},
                        {"path": "poupanca.saldo"},
                    ]
                }
            },
            "estrutura_schema_saida": {
                "campos_raiz": ["financiamentos", "poupanca"],
                "paths_permitidos": ["financiamentos.valor", "poupanca.saldo"],
                "arrays_que_exigem_seletor": [],
            },
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {
                "entity_slug": "entidade",
                "document_id": "doc-1",
                "execution_id": "execution-1",
                "manifest_key": "execucao/manifesto.json",
                "fallback_execution_id": "fallback-1",
            },
            "llm_constraints": {
                "chamar_llm": True,
                "selecionar_artefatos_por_llm_usando_inventario": True,
            },
            "contrato_semantico_relevante": contract_context,
            "_manifesto_extracao_completo": {},
            "_paths_fixos_do_contrato": [],
            "llm_payloads": {
                "artifact_selection": {
                    "inventario_extracao": {
                        "resumo": {"items": [
                            {"path": "tables/financiamentos.json"},
                            {"path": "tables/poupanca.json"},
                        ]}
                    },
                    "contrato_semantico_relevante": contract_context,
                },
                "candidate_generation": {
                    "escopo_permitido": "criacao_inicial_layout",
                    "contexto_execucao": {},
                    "contrato_semantico_relevante": contract_context,
                    "alvos_mapeaveis": [
                        {"campo_saida": "financiamentos.valor"},
                        {"campo_saida": "poupanca.saldo"},
                    ],
                },
            },
        }

        result = service.generate_candidate_layout(context)

        self.assertEqual(result["modo_geracao"], "por_blocos_deterministicos")
        self.assertEqual(len(result["unidades_mapeamento"]), 2)
        self.assertEqual(
            set(result["candidate_layout"]["mapeamento_canonico"]),
            {"financiamentos.valor", "poupanca.saldo"},
        )
        written_keys = {key for key, _payload in minio.writes}
        self.assertIn(
            "fallback/construtoras/entidade/document_id=doc-1/execution_id=fallback-1/"
            "unidades/financiamentos/entrada_llm_selecao_artefatos.json",
            written_keys,
        )
        self.assertIn(
            "fallback/construtoras/entidade/document_id=doc-1/execution_id=fallback-1/"
            "unidades/poupanca/fragmento_layout_signature.json",
            written_keys,
        )
        fragment_call = next(call for call in llm.calls if call.get("messages"))
        messages = fragment_call["messages"]
        self.assertEqual(
            len([message for message in messages if message["role"] == "system"]),
            5,
        )
        message_text = "\n".join(message["content"] for message in messages)
        self.assertIn("exemplo_estrutura_mapeamento_unidade", message_text)
        self.assertIn("linhas_de_tabela", message_text)
        self.assertIn("tipos_origem_permitidos", message_text)

    def test_mapping_plan_groups_contract_roots_and_keeps_context_fields(self) -> None:
        contract_context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [
                        {
                            "path": "financiamentos.observacoes.valor",
                            "observacoes_obrigatorias": [
                                {
                                    "seletores": {"modalidade": "aquisição"},
                                    "campos_contexto_obrigatorios": ["periodo"],
                                }
                            ],
                        },
                        {"path": "poupanca.saldo"},
                    ]
                }
            },
            "estrutura_schema_saida": {
                "campos_raiz": ["financiamentos", "poupanca"],
                "paths_permitidos": [
                    "financiamentos.observacoes.valor",
                    "financiamentos.observacoes.periodo",
                    "poupanca.saldo",
                ],
                "arrays_que_exigem_seletor": ["financiamentos.observacoes"],
            },
        }

        units = MappingPlanService().build(contract_context)

        self.assertEqual([unit.id for unit in units], ["financiamentos", "poupanca"])
        self.assertEqual(
            units[0].mapping_paths,
            (
                "financiamentos.observacoes.periodo",
                "financiamentos.observacoes.valor",
            ),
        )
        self.assertIn(
            "financiamentos.observacoes.periodo",
            units[0].subschema["paths_permitidos"],
        )

    def test_fragment_validation_accepts_only_one_mapping_unit(self) -> None:
        contract_context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [
                        {"path": "financiamentos.valor"},
                        {"path": "poupanca.saldo"},
                    ]
                }
            },
            "estrutura_schema_saida": {
                "campos_raiz": ["financiamentos", "poupanca"],
                "paths_permitidos": ["financiamentos.valor", "poupanca.saldo"],
                "arrays_que_exigem_seletor": [],
            },
        }
        unit = MappingPlanService().build(contract_context)[0]
        fragment = {
            "tipo_artefato": "fragmento_layout_signature",
            "unidade_mapeamento": "financiamentos",
            "mapeamento_canonico": {
                "financiamentos.valor": {
                    "tipo_origem": "bloco_textual",
                    "arquivo_origem": "blocks/blocks.jsonl",
                }
            },
            "fontes_relevantes": {},
            "metadados_estruturais_evidencia": {},
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {
                "document_id": "doc-1",
                "execution_id": "execution-1",
            },
            "contrato_semantico_relevante": contract_context,
            "_paths_fixos_do_contrato": [],
        }

        validated = FallbackCandidateValidationService().validate_layout_fragment(
            fragment,
            unit=unit,
            fallback_problem_context=context,
        )

        self.assertIn("financiamentos.valor", validated.mapeamento_canonico)

    def test_fragment_allows_collection_root_with_table_rows_mapping(self) -> None:
        contract_context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [{"path": "serie.observacoes"}]
                }
            },
            "estrutura_schema_saida": {
                "campos_raiz": ["serie"],
                "paths_permitidos": [
                    "serie",
                    "serie.observacoes",
                    "serie.observacoes.periodo",
                    "serie.observacoes.periodo.rotulo",
                    "serie.observacoes.valor",
                ],
                "arrays_que_exigem_seletor": ["serie.observacoes"],
            },
        }
        unit = MappingPlanService().build(contract_context)[0]
        fragment = {
            "tipo_artefato": "fragmento_layout_signature",
            "unidade_mapeamento": "serie",
            "mapeamento_canonico": {
                "serie.observacoes": {
                    "tipo_origem": "linhas_de_tabela",
                    "arquivo_origem": "tables/serie.json",
                    "linha_inicial": 0,
                    "linha_final": 3,
                    "campos": [
                        {"caminho_saida": "periodo.rotulo", "indice_coluna": 0},
                        {"caminho_saida": "valor", "indice_coluna": 1, "tipo": "numero"},
                    ],
                }
            },
            "fontes_relevantes": {},
            "metadados_estruturais_evidencia": {},
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {"document_id": "doc-1", "execution_id": "execution-1"},
            "contrato_semantico_relevante": contract_context,
            "_paths_fixos_do_contrato": [],
        }

        validated = FallbackCandidateValidationService().validate_layout_fragment(
            fragment, unit=unit, fallback_problem_context=context
        )

        self.assertEqual(
            validated.mapeamento_canonico["serie.observacoes"].tipo_origem,
            "linhas_de_tabela",
        )

    def test_table_rows_preserve_nested_output_fields(self) -> None:
        item = SchemaResolutionService._table_row_with_named_fields(
            ["jan/2026", "12,5"],
            row_index=4,
            start=0,
            fields=[
                {"caminho_saida": "periodo.rotulo_publicado", "indice_coluna": 0},
                {"caminho_saida": "valor", "indice_coluna": 1, "tipo": "numero"},
            ],
        )

        self.assertEqual(item["periodo"]["rotulo_publicado"], "jan/2026")
        self.assertEqual(item["valor"], 12.5)

    def test_small_table_evidence_keeps_all_rows(self) -> None:
        inventory = FallbackInventoryService()
        content = json.dumps(
            {"schema": ["mes", "valor"], "rows": [["jan", "1"], ["fev", "2"]]}
        ).encode("utf-8")

        artifact = inventory.load_artifact_for_llm(
            "tables/serie.json", get_bytes=lambda _key: content
        )

        self.assertEqual(artifact["sample"]["modo_linhas"], "completo")
        self.assertEqual(len(artifact["sample"]["rows"]), 2)

    def test_jsonl_anchor_evidence_searches_beyond_initial_sample(self) -> None:
        inventory = FallbackInventoryService()
        path = "blocks/blocks.jsonl"
        content = "\n".join(
            json_line
            for index in range(1, 20)
            for json_line in [
                '{"text":"bloco sem evidencia"}'
                if index < 19
                else '{"text":"Financiamentos com Recursos Livres"}'
            ]
        ).encode("utf-8")
        selection = LayoutArtifactSelection.model_validate(
            {
                "tipo_artefato": "selecao_artefatos_layout",
                "artifact_paths": [
                    {
                        "path": path,
                        "motivo": "Contem a secao procurada.",
                        "coberturas": [
                            {
                                "campo_saida": "recursos_livres.observacoes",
                                "ancoras": ["Recursos Livres"],
                            }
                        ],
                    }
                ],
            }
        )
        manifest = {
            "artifact_uris": [
                "minio://ocr-cidades/execucao/extraction/blocks/blocks.jsonl"
            ]
        }
        loaded = inventory.load_selected_extraction_artifacts(
            manifest=manifest,
            artifact_paths=[path],
            get_bytes=lambda _key: content,
        )
        self.assertEqual(len(loaded[path]["sample"]), 5)

        enriched = inventory.enrich_selected_jsonl_anchor_evidence(
            manifest=manifest,
            artifact_selection=selection,
            loaded_artifacts=loaded,
            get_bytes=lambda _key: content,
        )

        self.assertEqual(enriched[path]["evidencias_ancoras"][0]["linha"], 19)
        ArtifactSelectionValidationService().validate_coverage(
            artifact_selection=selection,
            selection_payload={
                "contrato_semantico_relevante": {
                    "contrato_semantico": {
                        "requisitos_mapeamento": {
                            "campos_obrigatorios": [
                                {"path": "recursos_livres.observacoes"}
                            ]
                        }
                    }
                }
            },
            loaded_artifacts=enriched,
        )

    def test_http_incomplete_read_is_normalized_as_runtime_error(self) -> None:
        class _Response:
            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: Any) -> None:
                return None

            def read(self) -> bytes:
                raise IncompleteRead(b"", 1)

        with patch("document_processing.infrastructure.llm.http_client.urlopen", return_value=_Response()):
            with self.assertRaisesRegex(RuntimeError, "Falha ao chamar API"):
                HttpClient().post_json("https://llm.example/v1/chat/completions", {})

    def test_fallback_uses_active_contract_instead_of_historical_manifest_uri(self) -> None:
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=_MinioContracts(),
        )
        fallback_context = {
            "domain": "abecip",
            "contrato_semantico_uri": (
                "minio://ocr-cidades/contratos/abecip/v2.0.1/"
                "contrato_semantico_abecip.json"
            ),
        }

        key, contract = service.load_semantic_contract(fallback_context)

        self.assertEqual(
            key,
            "contratos/abecip/v2.1.0/contrato_semantico_abecip.json",
        )
        self.assertEqual(contract["versao"], "2.1.0")
        self.assertEqual(
            fallback_context["contrato_semantico_uri"],
            "minio://ocr-cidades/contratos/abecip/v2.1.0/contrato_semantico_abecip.json",
        )

    def test_client_accepts_ordered_instruction_messages(self) -> None:
        messages = FallbackLlmClient._build_chat_messages(
            system_prompt=None,
            user_payload=None,
            messages=[
                {"role": "system", "content": "Explique o contrato."},
                {"role": "user", "content": '{"contrato": {}}'},
                {"role": "system", "content": "Agora use os artefatos."},
                {"role": "user", "content": '{"artefatos": {}}'},
            ],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[2]["content"], "Agora use os artefatos.")

    def test_table_cell_projects_scalar_for_terminal_mapping_path(self) -> None:
        resolved_cell = {
            "periodo": "2T26",
            "escopo_periodo": "trimestre",
            "valor": 6549.0,
        }

        scalar = SchemaResolutionService._project_table_cell_value(
            mapping_path=(
                "balancos.lancamentos.dados[empresa=Cury]."
                "valores[papel_periodo=periodo_referencia].valor"
            ),
            resolved_cell=resolved_cell,
            raw_value="6549",
        )
        record = SchemaResolutionService._project_table_cell_value(
            mapping_path=(
                "balancos.lancamentos.dados[empresa=Cury]."
                "valores[papel_periodo=periodo_referencia]"
            ),
            resolved_cell=resolved_cell,
            raw_value="6549",
        )

        company = SchemaResolutionService._project_table_cell_value(
            mapping_path="balancos.lancamentos.dados[empresa=Cury].empresa",
            resolved_cell=resolved_cell,
            raw_value="Cury",
        )

        self.assertEqual(scalar, 6549.0)
        self.assertEqual(record, resolved_cell)
        self.assertEqual(company, "Cury")

    def test_artifact_instruction_allows_using_only_semantically_adequate_sources(self) -> None:
        instruction = candidate_artifacts_instruction()

        self.assertIn("nem todo arquivo precisa ser usado", instruction)
        self.assertIn("fontes com granularidades diferentes", instruction)

    def test_relevant_contract_context_keeps_semantics_without_truncation_marker(self) -> None:
        builder = FallbackProblemContextBuilder()
        contract = {
            "nome": "Contrato de teste",
            "versao": "1.0.0",
            "dominio": "teste",
            "contrato_semantico": {
                "entidades": {"nivel_1": {"nivel_2": {"nivel_3": "preservado"}}},
                "metricas": {"grupo": {"indicador": {"descricao": "valor bruto"}}},
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [{"path": "grupo.dados.valores.valor"}]
                },
            },
            "schema_saida": {
                "grupo": {"dados": [{"valores": [{"valor": "number"}]}]},
            },
        }

        relevant = builder._relevant_contract_context(contract=contract, broken_fields=[])

        self.assertIn("estrutura_schema_saida", relevant)
        self.assertIn(
            "grupo.dados.valores.valor",
            relevant["estrutura_schema_saida"]["paths_permitidos"],
        )
        self.assertNotIn("<truncado>", str(relevant))

    def test_relevant_contract_context_hides_contract_literals_from_llm(self) -> None:
        relevant = FallbackProblemContextBuilder()._relevant_contract_context(
            contract={
                "schema_saida": {
                    "medida": {
                        "unidade": "unidades",
                        "valor": "number",
                    }
                }
            },
            broken_fields=[],
        )

        paths = relevant["estrutura_schema_saida"]["paths_permitidos"]
        self.assertIn("medida.valor", paths)
        self.assertNotIn("medida.unidade", paths)

    def test_relevant_contract_context_does_not_require_literal_context_field(self) -> None:
        relevant = FallbackProblemContextBuilder()._relevant_contract_context(
            contract={
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {
                                "path": "serie.observacoes.valor",
                                "observacoes_obrigatorias": [
                                    {
                                        "seletores": {"papel": "referencia"},
                                        "campos_contexto_obrigatorios": [
                                            "periodo",
                                            "escopo",
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                },
                "schema_saida": {
                    "serie": {
                        "observacoes": [
                            {
                                "periodo": "string",
                                "escopo": "trimestre",
                                "valor": "number",
                            }
                        ]
                    }
                },
            },
            broken_fields=[],
        )

        observation = (
            relevant["contrato_semantico"]["requisitos_mapeamento"]
            ["campos_obrigatorios"][0]["observacoes_obrigatorias"][0]
        )
        self.assertEqual(observation["campos_contexto_obrigatorios"], ["periodo"])

    def test_candidate_rejects_mapping_for_contract_literal(self) -> None:
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag1",
            "base_layout_signature": None,
            "mapeamento_canonico": {
                "medida.unidade": {
                    "tipo_origem": "valor_fixo",
                    "valor_fixo": "unidades",
                }
            },
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {"document_id": "doc-1", "execution_id": "dag1"},
            "_paths_fixos_do_contrato": ["medida.unidade"],
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [{"path": "medida.valor"}]
                    }
                },
                "estrutura_schema_saida": {
                    "campos_raiz": ["medida"],
                    "paths_permitidos": ["medida", "medida.valor"],
                    "arrays_que_exigem_seletor": [],
                },
            },
        }

        with self.assertRaisesRegex(RuntimeError, "valor fixo do contrato"):
            FallbackCandidateValidationService().validate_candidate_layout(candidate, context)

    def test_candidate_rejects_positional_array_index_as_correctable_validation_error(self) -> None:
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag1",
            "base_layout_signature": None,
            "mapeamento_canonico": {
                "serie.observacoes[0].valor": {
                    "tipo_origem": "valor_fixo",
                    "valor_fixo": 10,
                }
            },
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {"document_id": "doc-1", "execution_id": "dag1"},
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [{"path": "serie.observacoes.valor"}]
                    }
                },
                "estrutura_schema_saida": {
                    "campos_raiz": ["serie"],
                    "paths_permitidos": ["serie.observacoes.valor"],
                    "arrays_que_exigem_seletor": ["serie.observacoes"],
                },
            },
        }

        with self.assertRaisesRegex(RuntimeError, "indices posicionais como \[0\]"):
            FallbackCandidateValidationService().validate_candidate_layout(candidate, context)

    def test_mappable_targets_follow_contract_declaration_not_path_name(self) -> None:
        targets = FallbackProblemContextBuilder._mappable_targets(
            {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {"path": "poupanca.saldo_final"},
                            {
                                "path": "ranking_bancario.instituicoes.volume_contratado",
                                "observacoes_obrigatorias": [
                                    {
                                        "seletores": {"instituicao": "Banco A"},
                                        "campos_contexto_obrigatorios": ["instituicao"],
                                    }
                                ],
                            },
                        ]
                    }
                },
                "estrutura_schema_saida": {
                    "paths_permitidos": [
                        "poupanca.saldo_final",
                        "ranking_bancario.instituicoes",
                        "ranking_bancario.instituicoes.volume_contratado",
                        "ranking_bancario.instituicoes.instituicao",
                    ],
                    "arrays_que_exigem_seletor": ["ranking_bancario.instituicoes"],
                },
            }
        )

        self.assertEqual(
            targets,
            [
                {
                    "campo_saida": "poupanca.saldo_final",
                    "arrays_que_exigem_seletor": [],
                },
                {
                    "campo_saida": "ranking_bancario.instituicoes.volume_contratado",
                    "arrays_que_exigem_seletor": ["ranking_bancario.instituicoes"],
                    "observacoes_obrigatorias": [
                        {
                            "seletores": {"instituicao": "Banco A"},
                            "campos_contexto_obrigatorios": ["instituicao"],
                        }
                    ],
                },
            ],
        )

    def test_candidate_requires_declared_observation_context_fields(self) -> None:
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag1",
            "base_layout_signature": None,
            "mapeamento_canonico": {
                "serie.observacoes[periodo=referencia].valor": {
                    "tipo_origem": "valor_fixo",
                    "valor_fixo": 10,
                },
                "serie.observacoes[periodo=referencia].competencia": {
                    "tipo_origem": "valor_fixo",
                    "valor_fixo": "2026-06",
                },
            },
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {"document_id": "doc-1", "execution_id": "dag1"},
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {
                                "path": "serie.observacoes.valor",
                                "observacoes_obrigatorias": [
                                    {
                                        "seletores": {"periodo": "referencia"},
                                        "campos_contexto_obrigatorios": [
                                            "competencia",
                                            "escopo",
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                },
                "estrutura_schema_saida": {
                    "campos_raiz": ["serie"],
                    "paths_permitidos": [
                        "serie",
                        "serie.observacoes",
                        "serie.observacoes.valor",
                        "serie.observacoes.competencia",
                        "serie.observacoes.escopo",
                    ],
                    "arrays_que_exigem_seletor": ["serie.observacoes"],
                },
            },
        }

        with self.assertRaisesRegex(RuntimeError, "serie.observacoes.escopo"):
            FallbackCandidateValidationService().validate_candidate_layout(candidate, context)

    def test_candidate_accepts_explicit_evidence_gap_for_required_field(self) -> None:
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag1",
            "base_layout_signature": None,
            "campos_nao_mapeados": [
                {
                    "path": "serie.observacoes.valor",
                    "seletores": {"papel_periodo": "referencia"},
                    "motivo": "A tabela nao possui a coluna exigida.",
                    "artefatos_verificados": ["tables/table001.json"],
                }
            ],
            "mapeamento_canonico": {},
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {"document_id": "doc-1", "execution_id": "dag1"},
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {
                                "path": "serie.observacoes.valor",
                                "observacoes_obrigatorias": [
                                    {
                                        "seletores": {"papel_periodo": "referencia"},
                                        "campos_contexto_obrigatorios": ["periodo"],
                                    }
                                ],
                            }
                        ]
                    }
                },
                "estrutura_schema_saida": {
                    "campos_raiz": ["serie"],
                    "paths_permitidos": [
                        "serie.observacoes.valor",
                        "serie.observacoes.periodo",
                    ],
                    "arrays_que_exigem_seletor": ["serie.observacoes"],
                },
            },
        }

        with self.assertRaises(UnmappedRequiredFieldsError) as raised:
            FallbackCandidateValidationService().validate_candidate_layout(candidate, context)

        self.assertEqual(raised.exception.fields[0].path, "serie.observacoes.valor")

    def test_optional_observation_not_mapped_is_persisted_without_blocking(self) -> None:
        minio = _MinioRecorder()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
        )
        candidate = LayoutSignatureCandidate.model_validate(
            {
                "tipo_artefato": "layout_signature_candidato",
                "status_layout": "candidato",
                "escopo_correcao": "criacao_inicial_layout",
                "document_id": "doc-1",
                "execution_id_origem": "execution-1",
                "mapeamento_canonico": {
                    "serie.observacoes[papel_periodo=referencia].valor": {
                        "tipo_origem": "celula_de_tabela"
                    }
                },
            }
        )
        contract_context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [
                        {
                            "path": "serie.observacoes.valor",
                            "observacoes_obrigatorias": [
                                {
                                    "seletores": {"papel_periodo": "referencia"},
                                    "campos_contexto_obrigatorios": [],
                                },
                                {
                                    "seletores": {"papel_periodo": "anterior"},
                                    "campos_contexto_obrigatorios": [],
                                    "obrigatorio": False,
                                },
                            ],
                        }
                    ]
                }
            },
            "estrutura_schema_saida": {
                "paths_permitidos": ["serie.observacoes.valor"],
            },
        }

        service._persist_unmapped_optional_observations(
            fallback_context={
                "entity_slug": "entidade",
                "document_id": "doc-1",
                "execution_id": "execution-1",
                "manifest_key": "execucao/manifesto.json",
                "fallback_execution_id": "fallback-1",
            },
            candidate=candidate,
            candidate_validation_context={
                "contrato_semantico_relevante": contract_context,
            },
            artifact_paths=["tables/table001.json"],
        )

        diagnosis = next(
            payload for key, payload in minio.writes if "campos_nao_mapeados" in key
        )
        self.assertEqual(diagnosis["status"], "observacoes_opcionais_nao_comprovadas")
        self.assertFalse(diagnosis["bloqueia_publicacao"])
        self.assertEqual(
            diagnosis["campos_nao_mapeados"][0]["seletores"],
            {"papel_periodo": "anterior"},
        )
        self.assertFalse(diagnosis["campos_nao_mapeados"][0]["obrigatorio"])

    def test_explicit_evidence_gap_stops_candidate_retries_and_persists_diagnosis(self) -> None:
        class AbstainingLlm:
            def __init__(self) -> None:
                self.calls = 0

            def generate_json(self, **_kwargs: Any) -> tuple[dict[str, Any], str]:
                self.calls += 1
                response = {
                    "tipo_artefato": "layout_signature_candidato",
                    "status_layout": "candidato",
                    "escopo_correcao": "criacao_inicial_layout",
                    "document_id": "doc-1",
                    "execution_id_origem": "execution-1",
                    "base_layout_signature": None,
                    "campos_nao_mapeados": [
                        {
                            "path": "medida.valor",
                            "seletores": {},
                            "motivo": "A tabela nao contem o valor exigido.",
                            "artefatos_verificados": ["tables/table001.json"],
                        }
                    ],
                    "mapeamento_canonico": {},
                }
                return response, json.dumps(response)

        minio = _MinioRecorder()
        llm = AbstainingLlm()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
            llm_client=llm,  # type: ignore[arg-type]
        )
        contract_context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [{"path": "medida.valor"}]
                }
            },
            "estrutura_schema_saida": {
                "campos_raiz": ["medida"],
                "paths_permitidos": ["medida.valor"],
                "arrays_que_exigem_seletor": [],
            },
        }
        context = {
            "escopo_permitido": "criacao_inicial_layout",
            "fallback_context": {
                "entity_slug": "entidade",
                "document_id": "doc-1",
                "execution_id": "execution-1",
                "manifest_key": "execucao/manifesto.json",
                "fallback_execution_id": "fallback-1",
            },
            "llm_constraints": {
                "chamar_llm": True,
                "selecionar_artefatos_por_llm_usando_inventario": False,
            },
            "contrato_semantico_relevante": contract_context,
            "_paths_fixos_do_contrato": [],
            "llm_payloads": {
                "artifact_selection": {},
                "candidate_generation": {
                    "escopo_permitido": "criacao_inicial_layout",
                    "contexto_execucao": {},
                    "contrato_semantico_relevante": contract_context,
                    "alvos_mapeaveis": [{"campo_saida": "medida.valor"}],
                    "exemplo_estrutura_layout_signature": {},
                },
            },
        }

        with self.assertRaisesRegex(RuntimeError, "evidencia insuficiente"):
            service.generate_candidate_layout(context)

        self.assertEqual(llm.calls, 1)
        diagnosis = next(
            payload for key, payload in minio.writes if "campos_nao_mapeados" in key
        )
        self.assertEqual(
            diagnosis["status"], "evidencia_insuficiente_para_requisito_obrigatorio"
        )

    def test_candidate_prompt_instructs_the_model_to_abstain_from_missing_evidence(self) -> None:
        instruction = candidate_artifacts_instruction()

        self.assertIn("campos_nao_mapeados", instruction)
        self.assertIn("nao deduza", instruction)

    def test_artifact_selection_coverage_requires_real_evidence_per_required_value(self) -> None:
        validator = ArtifactSelectionValidationService()
        selection = LayoutArtifactSelection.model_validate(
            {
                "tipo_artefato": "selecao_artefatos_layout",
                "artifact_paths": [
                    {
                        "path": "tables/lancamentos.json",
                        "motivo": "Fonte de lancamentos.",
                        "coberturas": [
                            {
                                "campo_saida": "balancos.lancamentos.dados.valores.valor",
                                "ancoras": ["LANCAMENTOS", "Unidades"],
                            }
                        ],
                    },
                    {
                        "path": "tables/vendas.json",
                        "motivo": "Fonte de vendas.",
                        "coberturas": [
                            {
                                "campo_saida": "balancos.vendas.dados.valores.valor",
                                "ancoras": ["VENDAS", "Unidades"],
                            }
                        ],
                    },
                ],
            }
        )
        payload = {
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {"path": "balancos.lancamentos.dados.valores.valor"},
                            {"path": "balancos.vendas.dados.valores.valor"},
                        ]
                    }
                },
                "schema_saida_paths": [
                    "balancos.lancamentos.dados.valores.valor",
                    "balancos.vendas.dados.valores.valor",
                ]
            }
        }
        loaded = {
            "tables/lancamentos.json": {"sample": {"rows": [["Lançamentos", "Unidades"]]}},
            "tables/vendas.json": {"sample": {"rows": [["Vendas", "Unidades"]]}},
        }

        validator.validate_coverage(
            artifact_selection=selection,
            selection_payload=payload,
            loaded_artifacts=loaded,
        )

    def test_artifact_selection_coverage_rejects_claim_without_anchor(self) -> None:
        validator = ArtifactSelectionValidationService()
        selection = LayoutArtifactSelection.model_validate(
            {
                "tipo_artefato": "selecao_artefatos_layout",
                "artifact_paths": [
                    {
                        "path": "tables/vendas.json",
                        "motivo": "Alega cobrir os dois blocos.",
                        "coberturas": [
                            {
                                "campo_saida": "balancos.lancamentos.dados.valores.valor",
                                "ancoras": ["LANCAMENTOS", "Unidades"],
                            },
                            {
                                "campo_saida": "balancos.vendas.dados.valores.valor",
                                "ancoras": ["VENDAS", "Unidades"],
                            },
                        ],
                    }
                ],
            }
        )
        payload = {
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {"path": "balancos.lancamentos.dados.valores.valor"},
                            {"path": "balancos.vendas.dados.valores.valor"},
                        ]
                    }
                },
                "schema_saida_paths": [
                    "balancos.lancamentos.dados.valores.valor",
                    "balancos.vendas.dados.valores.valor",
                ]
            }
        }

        with self.assertRaises(ArtifactSelectionValidationError):
            validator.validate_coverage(
                artifact_selection=selection,
                selection_payload=payload,
                loaded_artifacts={
                    "tables/vendas.json": {"sample": {"rows": [["Vendas", "Unidades"]]}}
                },
            )

    def test_json_parse_error_preserves_raw_content(self) -> None:
        with self.assertRaises(FallbackLlmClientError) as raised:
            FallbackLlmClient._parse_json_content('{"campo":')

        self.assertEqual(raised.exception.raw_content, '{"campo":')

    def test_empty_openai_content_preserves_response_metadata(self) -> None:
        response = {
            "id": "completion-1",
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "content": "",
                        "reasoning_content": "raciocinio do modelo",
                    },
                }
            ],
            "usage": {"completion_tokens": 8192, "reasoning_tokens": 8000},
        }

        with self.assertRaises(FallbackLlmClientError) as raised:
            FallbackLlmClient._extract_openai_content(
                response,
                response_metadata=FallbackLlmClient._openai_response_metadata(response),
            )

        metadata = raised.exception.response_metadata
        self.assertEqual(metadata["finish_reason"], "length")
        self.assertTrue(metadata["reasoning_content_presente"])
        self.assertEqual(metadata["reasoning_content_caracteres"], len("raciocinio do modelo"))

    def test_fallback_prefix_uses_dag3_execution_id(self) -> None:
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=_MinioRecorder(),
        )

        prefix = service._fallback_prefix(
            {
                "company_slug": "cury",
                "document_id": "doc-1",
                "execution_id": "dag1__old",
                "fallback_execution_id": "dag_valida_e_fallback_llm__manual__20260709",
            }
        )

        self.assertIn(
            "execution_id=dag_valida_e_fallback_llm__manual__20260709",
            prefix,
        )
        self.assertNotIn("execution_id=dag1__old", prefix)

    def test_persists_raw_selection_response_when_coverage_is_rejected(self) -> None:
        minio = _MinioRecorder()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
        )

        service._persist_llm_error(
            fallback_context={
                "company_slug": "cury",
                "document_id": "doc-1",
                "execution_id": "dag1__old",
                "fallback_execution_id": "dag3__manual",
            },
            stage="selecao_artefatos",
            attempt=0,
            error=ArtifactSelectionValidationError("cobertura insuficiente"),
            raw_response='{"artifact_paths": []}',
        )

        self.assertEqual(len(minio.writes), 1)
        self.assertEqual(minio.writes[0][1]["raw_response"], {"artifact_paths": []})

    def test_preserves_invalid_raw_response_as_text_in_error_artifact(self) -> None:
        minio = _MinioRecorder()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
        )

        service._persist_llm_error(
            fallback_context={
                "company_slug": "cury",
                "document_id": "doc-1",
                "execution_id": "dag1__old",
                "fallback_execution_id": "dag3__manual",
            },
            stage="layout_signature_candidato",
            attempt=0,
            error=FallbackLlmClientError("JSON truncado"),
            raw_response='{"mapeamento_canonico":',
        )

        self.assertEqual(
            minio.writes[0][1]["raw_response"],
            '{"mapeamento_canonico":',
        )

    def test_omits_raw_response_when_it_duplicates_parsed_error_response(self) -> None:
        minio = _MinioRecorder()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
        )

        parsed_response = {"artifact_paths": []}
        service._persist_llm_error(
            fallback_context={
                "company_slug": "cury",
                "document_id": "doc-1",
                "execution_id": "dag1__old",
                "fallback_execution_id": "dag3__manual",
            },
            stage="selecao_artefatos",
            attempt=0,
            error=ArtifactSelectionValidationError("cobertura insuficiente"),
            parsed_response=parsed_response,
            raw_response='{"artifact_paths": []}',
        )

        payload = minio.writes[0][1]
        self.assertEqual(payload["parsed_response"], parsed_response)
        self.assertNotIn("raw_response", payload)

    def test_artifact_selection_retries_with_coverage_error(self) -> None:
        minio = _MinioRecorder()
        llm = _SelectionRetryingLlm()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
            llm_client=llm,  # type: ignore[arg-type]
            inventory_service=_SelectionInventory(),  # type: ignore[arg-type]
        )
        payload = {
            "inventario_extracao": {
                "resumo": {
                    "items": [
                        {"path": "metrics/metrics.jsonl"},
                        {"path": "tables/table002.json"},
                    ]
                }
            },
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {"path": "balancos.lancamentos.dados.valores.valor"}
                        ]
                    }
                },
                "estrutura_schema_saida": {
                    "paths_permitidos": [
                        "balancos.lancamentos.dados.valores.valor"
                    ]
                }
            },
        }
        selection, _raw, loaded = service.select_relevant_artifacts(
            payload,
            fallback_context={
                "company_slug": "cury",
                "document_id": "doc-1",
                "execution_id": "dag1__old",
                "fallback_execution_id": "dag3__manual",
            },
            manifest={},
        )

        self.assertEqual(selection.artifact_paths[0].path, "tables/table002.json")
        self.assertIn("tables/table002.json", loaded)
        self.assertEqual(len(llm.calls), 2)
        repair = llm.calls[1]["user_payload"]["correcao_selecao_artefatos"]
        self.assertIn("ancoras ausentes", repair["erro_validacao"])
        self.assertEqual(repair["tentativa"], 1)
        evidence = llm.calls[1]["user_payload"]["artefatos_carregados_para_correcao"]
        self.assertIn("metrics/metrics.jsonl", evidence)

    def test_artifact_selection_retries_when_llm_uses_invalid_coverage_keys(self) -> None:
        minio = _MinioRecorder()
        llm = _SelectionSchemaRetryingLlm()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
            llm_client=llm,  # type: ignore[arg-type]
            inventory_service=_SelectionInventory(),  # type: ignore[arg-type]
        )
        payload = {
            "inventario_extracao": {"resumo": {"items": [{"path": "tables/table002.json"}]}},
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {"path": "balancos.lancamentos.dados.valores.valor"}
                        ]
                    }
                }
            },
        }

        selection, _raw, _loaded = service.select_relevant_artifacts(
            payload,
            fallback_context={
                "company_slug": "cury",
                "document_id": "doc-1",
                "execution_id": "dag1__old",
                "fallback_execution_id": "dag3__manual",
            },
            manifest={},
        )

        self.assertEqual(selection.artifact_paths[0].path, "tables/table002.json")
        self.assertEqual(len(llm.calls), 2)
        retry = llm.calls[1]["user_payload"]["correcao_selecao_artefatos"]
        self.assertIn("campo_saida", retry["erro_validacao"])
        self.assertIn("ancoras", retry["erro_validacao"])
        self.assertTrue(
            any("erro_llm_selecao_artefatos" in key for key, _payload in minio.writes)
        )

    def test_candidate_generation_retries_invalid_json_and_persists_attempts(self) -> None:
        minio = _MinioRecorder()
        llm = _RetryingLlm()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
            llm_client=llm,  # type: ignore[arg-type]
            candidate_validator=_CandidateValidator(),  # type: ignore[arg-type]
        )

        result = service.generate_candidate_layout(
            {
                "tipo_artefato": "fallback_problem_context",
                "status": "contexto_montado",
                "manifesto_extracao_ref": {"artifact_uris_count": 10},
                "modo_criacao_inicial_layout": True,
                "fallback_context": {
                    "company_slug": "cury",
                    "document_id": "doc-1",
                    "execution_id": "dag1__20260709T120000Z",
                    "manifest_key": "raw/construtoras/cury/manifesto_execucao.json",
                    "fallback_execution_id": "dag_valida_e_fallback_llm__manual__1",
                },
                "llm_constraints": {
                    "chamar_llm": True,
                    "selecionar_artefatos_por_llm_usando_inventario": False,
                },
                "falha": {},
                "llm_payloads": {
                    "artifact_selection": {
                        "tipo_payload": "selecao_artefatos_correcao_parcial",
                        "inventario_extracao": {"resumo": {"items": []}},
                    },
                    "candidate_generation": {
                        "tipo_payload": "layout_candidato_correcao_parcial",
                        "escopo_permitido": "correcao_parcial_mapeamento",
                        "llm_constraints": {"chamar_llm": True},
                        "layout_candidate_lineage": {
                            "document_id": "doc-1",
                            "execution_id_origem": "dag1__20260709T120000Z",
                            "fallback_execution_id": "dag_valida_e_fallback_llm__manual__1",
                        },
                        "contrato_semantico_relevante": {},
                        "falha": {},
                    },
                },
            }
        )

        self.assertEqual(result["correction_attempts_used"], 1)
        self.assertEqual(len(llm.calls), 2)
        first_messages = llm.calls[0]["messages"]
        self.assertIsNotNone(first_messages)
        first_message_text = "\n".join(message["content"] for message in first_messages or [])
        self.assertIn("contexto_execucao", first_message_text)
        self.assertIn("exemplo_estrutura_layout_signature", first_message_text)
        self.assertNotIn("fallback_execution_id", first_message_text)

        written_keys = {object_key for object_key, _payload in minio.writes}
        self.assertIn(
            "fallback/construtoras/cury/document_id=doc-1/"
            "execution_id=dag_valida_e_fallback_llm__manual__1/"
            "entrada_llm_layout_signature_candidato.json",
            written_keys,
        )
        first_input = next(
            payload
            for object_key, payload in minio.writes
            if object_key.endswith("entrada_llm_layout_signature_candidato.json")
        )
        self.assertIn("messages", first_input)
        self.assertNotIn("user_payload", first_input)
        self.assertIn(
            "fallback/construtoras/cury/document_id=doc-1/"
            "execution_id=dag_valida_e_fallback_llm__manual__1/"
            "erro_llm_layout_signature_candidato.json",
            written_keys,
        )
        self.assertIn(
            "fallback/construtoras/cury/document_id=doc-1/"
            "execution_id=dag_valida_e_fallback_llm__manual__1/"
            "entrada_llm_layout_signature_candidato_tentativa_1.json",
            written_keys,
        )
        self.assertIn(
            "fallback/construtoras/cury/document_id=doc-1/"
            "execution_id=dag_valida_e_fallback_llm__manual__1/"
            "resposta_llm_layout_signature_candidato_tentativa_1.json",
            written_keys,
        )

    def test_payload_builders_create_different_payloads_by_scope(self) -> None:
        partial_context = {
            "escopo_permitido": "correcao_parcial_mapeamento",
            "llm_constraints": {"chamar_llm": True},
            "falha": {"campos_quebrados": ["periodo_referencia"]},
            "contrato_semantico_relevante": {
                "contrato_semantico": {
                    "metricas": {"grupo": {"indicador": {"descricao": "valor bruto"}}},
                    "requisitos_mapeamento": {
                        "campos_obrigatorios": [
                            {"path": "balancos.lancamentos.dados.valores.valor"}
                        ]
                    }
                },
                "estrutura_schema_saida": {
                    "campos_raiz": ["periodo_referencia"],
                    "paths_permitidos": [
                        "periodo_referencia",
                        "balancos.lancamentos.dados.valores.valor",
                    ],
                    "arrays_que_exigem_seletor": [],
                }
            },
            "layout_signature_relevante": {"mapeamento_canonico_relevante": {"periodo_referencia": {}}},
            "inventario_extracao": {"resumo": {"items": [{"path": "tables/table001.json"}]}},
            "fallback_context": {
                "document_id": "doc-1",
                "execution_id": "dag1",
                "fallback_execution_id": "dag3",
            },
            "layout_signature_base_ref": {"object_key": "layouts/x/current.json"},
            "layout_signature_base_validation_context": {"mapeamento_canonico_paths": ["periodo_referencia"]},
        }
        initial_context = {
            **partial_context,
            "escopo_permitido": "criacao_inicial_layout",
            "layout_signature_relevante": {},
            "layout_signature_base_ref": None,
        }

        partial_payloads = FallbackProblemContextBuilder().build_llm_payloads(partial_context)
        initial_payloads = FallbackProblemContextBuilder().build_llm_payloads(initial_context)

        self.assertEqual(
            partial_payloads["artifact_selection"]["tipo_payload"],
            "selecao_artefatos_correcao_parcial",
        )
        self.assertIn("falha", partial_payloads["artifact_selection"])
        self.assertIn("layout_signature_relevante", partial_payloads["artifact_selection"])
        selection_contract = partial_payloads["artifact_selection"]["contrato_semantico_relevante"]
        self.assertNotIn("estrutura_schema_saida", selection_contract)
        self.assertEqual(
            selection_contract["contrato_semantico"]["metricas"],
            {"grupo": {"indicador": {"descricao": "valor bruto"}}},
        )
        self.assertEqual(
            selection_contract["contrato_semantico"]["requisitos_mapeamento"]["campos_obrigatorios"],
            [{"path": "balancos.lancamentos.dados.valores.valor"}],
        )
        self.assertEqual(
            initial_payloads["artifact_selection"]["tipo_payload"],
            "selecao_artefatos_criacao_inicial",
        )
        self.assertNotIn("falha", initial_payloads["artifact_selection"])
        self.assertNotIn("layout_signature_relevante", initial_payloads["artifact_selection"])
        self.assertNotIn("regras_de_saida", initial_payloads["candidate_generation"])
        self.assertNotIn("llm_constraints", initial_payloads["candidate_generation"])
        self.assertNotIn("layout_candidate_lineage", initial_payloads["candidate_generation"])
        output_contract = initial_payloads["candidate_generation"]["exemplo_estrutura_layout_signature"]
        self.assertEqual(
            output_contract["modelo_resposta_no_nivel_raiz"]["tipo_artefato"],
            "layout_signature_candidato",
        )
        self.assertIsNone(
            output_contract["modelo_resposta_no_nivel_raiz"]["base_layout_signature"]
        )
        self.assertIn("celula_de_tabela", output_contract["tipos_origem_permitidos"])
        self.assertTrue(
            {"campo_json", "linhas_de_tabela", "juncao_de_registros_json"}.issubset(
                output_contract["tipos_origem_permitidos"]
            )
        )
        self.assertIn(
            "celula_de_tabela_com_seletores",
            output_contract["exemplo_de_mapeamento"],
        )

    def test_initial_layout_skeleton_is_composed_outside_llm_candidate(self) -> None:
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=_MinioRecorder(),
        )
        skeleton = service._build_initial_layout_skeleton(
            contract_key="contratos/construtoras/v1.2.0/contrato_semantico_construtora.json",
            contract={"versao": "1.2.0"},
            manifest_key="execucoes/construtoras/extracao/mrv/manifesto_execucao.json",
            manifest={
                "input_pdf_uri": "minio://ocr-cidades/documentos-origem/mrv/mrv.pdf",
                "candidate": {"company_name": "MRV", "period_label": "1T26"},
            },
            fallback_context={
                "company_slug": "mrv",
                "document_id": "doc-1",
                "execution_id": "dag1__1T26",
                "manifest_key": "execucoes/construtoras/extracao/mrv/manifesto_execucao.json",
                "trigger_origin_dag": "dag_resolve_schema_saida",
            },
        )
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag1__1T26",
            "mapeamento_canonico": {"periodo_referencia": {"tipo_origem": "valor_fixo"}},
        }

        revalidation_layout = service._compose_initial_layout_for_revalidation(
            initial_layout_skeleton=skeleton,
            candidate=candidate,
            candidate_key="fallback/construtoras/mrv/layout_signature_candidato.json",
        )

        self.assertEqual(revalidation_layout["entidade"], {"slug": "mrv", "nome": "MRV"})
        self.assertEqual(
            revalidation_layout["referencia_contrato_semantico"]["arquivo"],
            "contrato_semantico_construtora.json",
        )
        self.assertEqual(revalidation_layout["documento_origem"]["periodo"], "1T26")
        self.assertTrue(revalidation_layout["regras_execucao"]["extrair_valores_brutos"])
        self.assertEqual(
            revalidation_layout["mapeamento_canonico"],
            candidate["mapeamento_canonico"],
        )

    def test_candidate_accepts_all_dag2_mapping_origins(self) -> None:
        for origin in ("campo_json", "linhas_de_tabela", "juncao_de_registros_json"):
            self.assertEqual(
                CanonicalMappingEntry(tipo_origem=origin).tipo_origem,
                origin,
            )

    def test_initial_candidate_revalidates_com_deterministic_skeleton(self) -> None:
        minio = _MinioRecorder()
        service = FallbackLlmService(
            config_loader=_ConfigLoader(),
            minio_client=minio,
        )
        candidate = {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag1__1T26",
            "mapeamento_canonico": {"periodo_referencia": {"tipo_origem": "valor_fixo"}},
        }
        loaded_context = {
            "fallback_context": {
                "company_slug": "mrv",
                "document_id": "doc-1",
                "execution_id": "dag1__1T26",
                "manifest_key": "execucoes/construtoras/extracao/mrv/manifesto_execucao.json",
                "trigger_origin_dag": "dag_resolve_schema_saida",
                "fallback_execution_id": "dag3__manual",
            },
            "object_keys": {"layout_signature_base": None},
            "initial_layout_skeleton": {
                "tipo_artefato": "layout_signature_com_mapeamento_canonico_deterministico",
                "entidade": {"slug": "mrv", "nome": "MRV"},
                "referencia_contrato_semantico": {"arquivo": "contrato.json", "versao": "1"},
                "documento_origem": {"document_id": "doc-1"},
                "regras_execucao": {"modo_resolucao": "deterministico"},
            },
        }

        persisted = service.persist_candidate_layout(
            {"candidate_layout": candidate},
            loaded_context,
        )
        revalidation_conf = service.build_revalidation_conf(persisted, loaded_context)

        self.assertEqual(
            revalidation_conf["candidate_layout_object_key"],
            persisted["candidate_layout_object_key"],
        )
        self.assertEqual(
            revalidation_conf["layout_signature_object_key"],
            persisted["revalidation_layout_object_key"],
        )
        self.assertNotIn("contrato_semantico_uri", revalidation_conf)
        revalidation_payload = next(
            payload
            for key, payload in minio.writes
            if key == persisted["revalidation_layout_object_key"]
        )
        self.assertEqual(
            revalidation_payload["entidade"],
            {"slug": "mrv", "nome": "MRV"},
        )
        self.assertEqual(
            revalidation_payload["mapeamento_canonico"],
            candidate["mapeamento_canonico"],
        )

    def test_optional_observation_does_not_become_blocking_requirement(self) -> None:
        contract_context = {
            "contrato_semantico": {
                "requisitos_mapeamento": {
                    "campos_obrigatorios": [
                        {
                            "path": "serie.valores.valor",
                            "observacoes_obrigatorias": [
                                {
                                    "seletores": {"papel": "referencia"},
                                    "campos_contexto_obrigatorios": ["periodo"],
                                },
                                {
                                    "seletores": {"papel": "comparativo"},
                                    "campos_contexto_obrigatorios": ["periodo"],
                                    "obrigatorio": False,
                                },
                            ],
                        }
                    ]
                }
            },
            "estrutura_schema_saida": {
                "paths_permitidos": [
                    "serie.valores.valor",
                    "serie.valores.periodo",
                ]
            },
        }

        requirements = mapping_requirements_from_context(contract_context)

        self.assertTrue(requirements[0].observations[0].required)
        self.assertFalse(requirements[0].observations[1].required)
        self.assertEqual(
            mapping_requirements_payload(requirements)["campos_obrigatorios"][0]
            ["observacoes_obrigatorias"][1]["obrigatorio"],
            False,
        )


if __name__ == "__main__":
    unittest.main()
