from __future__ import annotations

from copy import deepcopy
from typing import Any

from plugins.services.contract_schema import (
    contract_literal_paths,
    schema_array_paths,
    schema_paths,
)

from .classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)
from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
from .mapping_requirements import (
    mappable_targets_payload,
    mapping_requirements_from_context,
    mapping_requirements_payload,
)


class FallbackProblemContextBuilder:
    """Monta o contexto estruturado enviado para as chamadas LLM."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"

    def __init__(
        self,
        *,
        classification_service: FallbackClassificationService | None = None,
        inventory_service: FallbackInventoryService | None = None,
    ) -> None:
        self.classification_service = classification_service or FALLBACK_CLASSIFICATION_SERVICE
        self.inventory_service = inventory_service or FALLBACK_INVENTORY_SERVICE

    def build_fallback_problem_context(
        self,
        *,
        validation: dict[str, Any],
        audit: dict[str, Any],
        layout: dict[str, Any],
        contract: dict[str, Any],
        manifest: dict[str, Any],
        classification: dict[str, Any],
        inventory: dict[str, Any],
        inventory_key: str | None,
    ) -> dict[str, Any]:
        """Monta o pacote estruturado que limita o problema para a futura LLM."""
        rejected_rules = self.classification_service.rejected_rules(validation)
        unresolved_required = self.classification_service.unresolved_required_audit_items(audit)
        broken_fields = self._broken_output_fields(unresolved_required)
        origin_files = self._collect_origin_files(
            rejected_rules=rejected_rules,
            unresolved_required=unresolved_required,
            layout=layout,
            broken_fields=broken_fields,
        )
        inventory_policy = self.inventory_service.inventory_usage_policy(
            classification=classification,
            rejected_rules=rejected_rules,
            unresolved_required=unresolved_required,
        )
        if (
            inventory_policy["uso_inventario"] == self.inventory_service.REQUIRED
            and not inventory.get("items")
        ):
            raise RuntimeError(
                "Inventario da extracao obrigatorio para este escopo de fallback, "
                "mas inventory.json nao foi encontrado ou esta vazio."
            )
        inventory_has_items = bool(inventory.get("items"))
        should_select_artifacts = (
            inventory_policy["uso_inventario"]
            in {self.inventory_service.REQUIRED, self.inventory_service.RECOMMENDED}
            and inventory_has_items
        )
        use_full_inventory = classification.get("fallback_scope") == self.CREATION_SCOPE
        context = {
            "_paths_fixos_do_contrato": sorted(
                contract_literal_paths(contract.get("schema_saida", {}))
            ),
            "escopo_permitido": classification.get("fallback_scope"),
            "llm_constraints": {
                "chamar_llm": bool(classification.get("llm_permitida", False)),
                "permitir_correcao_parcial": classification.get("fallback_scope") == self.PARTIAL_SCOPE,
                "permitir_regeneracao_total": classification.get("fallback_scope") == self.FULL_REMAP_SCOPE,
                "nao_gerar_schema_saida_resolvido": True,
                "nao_inventar_campos_fora_do_contrato": True,
                "alterar_apenas_layout_signature_candidato": True,
                "permitir_reescrever_fontes_relevantes": True,
                "permitir_reescrever_regras_deteccao_mudanca": True,
                "permitir_reescrever_mapeamento_canonico": True,
                "permitir_atualizar_metadados_estruturais_de_evidencia": True,
                "nao_alterar_referencia_contrato_semantico": True,
                "nao_alterar_regras_execucao_governanca": True,
                "nao_definir_versao_artefato_final": True,
                "nao_alterar_layouts_versionados_existentes": True,
                "selecionar_artefatos_por_llm_usando_inventario": should_select_artifacts,
                "chunking_apenas_com_estado_acumulado": True,
                "layout_completo_permitido": classification.get("fallback_scope")
                in {self.FULL_REMAP_SCOPE, self.CREATION_SCOPE},
            },
            "falha": {
                "status_compatibilidade": validation.get("status_compatibilidade", {}),
                "codigos_falha": classification.get("codigos_falha", []),
                "motivos": classification.get("motivos", []),
                "campos_quebrados": broken_fields,
                "regras_reprovadas": [
                    self._truncate_json(rule)
                    for rule in rejected_rules
                ],
                "campos_obrigatorios_nao_resolvidos": [
                    self._truncate_json(item)
                    for item in unresolved_required
                ],
            },
            "layout_signature_relevante": self._relevant_layout_context(
                layout=layout,
                broken_fields=broken_fields,
                origin_files=origin_files,
            ),
            "contrato_semantico_relevante": self._relevant_contract_context(
                contract=contract,
                broken_fields=broken_fields,
            ),
            "inventario_extracao": {
                "object_key": inventory_key,
                "politica_uso": inventory_policy,
                "resumo": self.inventory_service.inventory_summary(
                    inventory,
                    full=use_full_inventory,
                ),
                "inventario_completo_enviado": use_full_inventory,
                "selecao_por_llm_obrigatoria": (
                    inventory_policy["uso_inventario"] == self.inventory_service.REQUIRED
                ),
                "selecao_por_llm_recomendada": (
                    inventory_policy["uso_inventario"] == self.inventory_service.RECOMMENDED
                ),
                "selecao_por_llm_habilitada": should_select_artifacts,
            },
            "manifesto_extracao_ref": {
                "artifact_uris_count": len(manifest.get("artifact_uris", []))
                if isinstance(manifest.get("artifact_uris"), list)
                else 0,
            },
            "debug_metadata": {
                "tipo_artefato": "fallback_problem_context",
                "status": "contexto_montado",
                "manifesto_extracao_ref": {
                    "artifact_uris_count": len(manifest.get("artifact_uris", []))
                    if isinstance(manifest.get("artifact_uris"), list)
                    else 0,
                },
                "inventory_key": inventory_key,
                "inventory_policy": inventory_policy,
            },
            "_manifesto_extracao_completo": manifest,
        }
        context["llm_payloads"] = self.build_llm_payloads(context)
        return context

    def build_llm_payloads(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Monta payloads especificos por escopo e etapa LLM."""
        scope = str(context.get("escopo_permitido", "")).strip()
        if scope == self.PARTIAL_SCOPE:
            return {
                "artifact_selection": self.build_partial_artifact_selection_payload(context),
                "candidate_generation": self.build_partial_candidate_payload(context),
            }
        if scope == self.CREATION_SCOPE:
            return {
                "artifact_selection": self.build_initial_creation_artifact_selection_payload(context),
                "candidate_generation": self.build_initial_creation_candidate_payload(context),
            }
        if scope == self.FULL_REMAP_SCOPE:
            return {
                "artifact_selection": self.build_full_remap_artifact_selection_payload(context),
                "candidate_generation": self.build_full_remap_candidate_payload(context),
            }
        return {
            "artifact_selection": self._base_artifact_selection_payload(
                context,
                tipo_payload="selecao_artefatos_fallback_nao_suportado",
            ),
            "candidate_generation": self._base_candidate_payload(
                context,
                tipo_payload="layout_candidato_fallback_nao_suportado",
            ),
        }

    @staticmethod
    def build_partial_artifact_selection_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da primeira chamada LLM para correcao parcial."""
        return FallbackProblemContextBuilder._base_artifact_selection_payload(
            context,
            tipo_payload="selecao_artefatos_correcao_parcial",
            include_failure=True,
            include_relevant_layout=True,
        )

    @staticmethod
    def build_partial_candidate_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da chamada LLM que gera candidato de correcao parcial."""
        return FallbackProblemContextBuilder._base_candidate_payload(
            context,
            tipo_payload="layout_candidato_correcao_parcial",
            include_failure=True,
            include_relevant_layout=True,
            include_base_validation_context=True,
        )

    @staticmethod
    def build_initial_creation_artifact_selection_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da primeira chamada LLM para criacao inicial de layout."""
        payload = FallbackProblemContextBuilder._base_artifact_selection_payload(
            context,
            tipo_payload="selecao_artefatos_criacao_inicial",
            include_failure=False,
            include_relevant_layout=False,
        )
        payload["objetivo"] = {
            "selecionar_fontes_para_criar_layout_signature": True,
            "nao_resolver_valores_finais": True,
        }
        return payload

    @staticmethod
    def build_initial_creation_candidate_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da chamada LLM que gera o primeiro layout candidato."""
        return FallbackProblemContextBuilder._base_candidate_payload(
            context,
            tipo_payload="layout_candidato_criacao_inicial",
            include_failure=False,
            include_relevant_layout=False,
            include_base_validation_context=False,
        )

    @staticmethod
    def build_full_remap_artifact_selection_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da primeira chamada LLM para regeneracao total."""
        payload = FallbackProblemContextBuilder._base_artifact_selection_payload(
            context,
            tipo_payload="selecao_artefatos_regeneracao_total",
            include_failure=False,
            include_relevant_layout=False,
        )
        payload["falha_resumida"] = FallbackProblemContextBuilder._failure_summary(context)
        weak_ref = FallbackProblemContextBuilder._weak_layout_reference(context)
        if weak_ref:
            payload["layout_anterior_como_referencia_fraca"] = weak_ref
        return payload

    @staticmethod
    def build_full_remap_candidate_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Payload da chamada LLM que gera candidato completo de regeneracao."""
        payload = FallbackProblemContextBuilder._base_candidate_payload(
            context,
            tipo_payload="layout_candidato_regeneracao_total",
            include_failure=False,
            include_relevant_layout=False,
            include_base_validation_context=False,
        )
        base_ref = context.get("layout_signature_base_ref")
        if isinstance(base_ref, dict) and base_ref:
            payload["base_layout_signature"] = {
                **base_ref,
                "uso": "linhagem_e_referencia_fraca",
            }
        payload["falha_resumida"] = FallbackProblemContextBuilder._failure_summary(context)
        payload["regras_de_saida"] = {
            "gerar_layout_signature_candidato_completo": True,
            "nao_gerar_schema_saida_resolvido": True,
            "nao_gerar_valores_finais": True,
        }
        return payload

    @staticmethod
    def _base_artifact_selection_payload(
        context: dict[str, Any],
        *,
        tipo_payload: str,
        include_failure: bool = True,
        include_relevant_layout: bool = True,
    ) -> dict[str, Any]:
        """Base compartilhada dos payloads de selecao de artefatos."""
        payload: dict[str, Any] = {
            "tipo_payload": tipo_payload,
            "escopo_permitido": context.get("escopo_permitido"),
            "contrato_semantico_relevante": (
                FallbackProblemContextBuilder._artifact_selection_contract_context(
                    context.get("contrato_semantico_relevante", {})
                )
            ),
            "inventario_extracao": context.get("inventario_extracao", {}),
        }
        if include_failure:
            payload["falha"] = context.get("falha", {})
        if include_relevant_layout:
            payload["layout_signature_relevante"] = context.get("layout_signature_relevante", {})
        return payload

    @staticmethod
    def _artifact_selection_contract_context(contract_context: Any) -> dict[str, Any]:
        """Projeta o contrato para a selecao sem expor estrutura de mapeamento.

        A primeira chamada precisa conhecer a semantica das entidades e os poucos
        campos que requerem evidencia. Paths, arrays e metricas completas sao
        necessarios ao validador e a geracao do candidato, nao a selecao.
        """
        if not isinstance(contract_context, dict):
            return {}

        semantic = contract_context.get("contrato_semantico", {})
        requirements = mapping_requirements_from_context(
            contract_context
        )
        identification = contract_context.get("identificacao", {})
        return {
            "identificacao": identification if isinstance(identification, dict) else {},
            "contrato_semantico": {
                "entidades": (
                    semantic.get("entidades", {}) if isinstance(semantic, dict) else {}
                ),
                "requisitos_mapeamento": mapping_requirements_payload(requirements),
            },
        }

    @staticmethod
    def _base_candidate_payload(
        context: dict[str, Any],
        *,
        tipo_payload: str,
        include_failure: bool = True,
        include_relevant_layout: bool = True,
        include_base_validation_context: bool = True,
    ) -> dict[str, Any]:
        """Base compartilhada dos payloads de geracao de candidato."""
        scope = context.get("escopo_permitido")
        payload: dict[str, Any] = {
            "tipo_payload": tipo_payload,
            "escopo_permitido": scope,
            "contexto_execucao": FallbackProblemContextBuilder._candidate_execution_context(
                context
            ),
            "contrato_semantico_relevante": context.get("contrato_semantico_relevante", {}),
            "alvos_mapeaveis": FallbackProblemContextBuilder._mappable_targets(
                context.get("contrato_semantico_relevante", {})
            ),
            "exemplo_estrutura_layout_signature": (
                FallbackProblemContextBuilder._layout_signature_structure_example(context)
            ),
        }
        if include_failure:
            payload["falha"] = context.get("falha", {})
        if include_relevant_layout:
            payload["layout_signature_relevante"] = context.get("layout_signature_relevante", {})
        base_ref = context.get("layout_signature_base_ref")
        if base_ref is not None:
            payload["layout_signature_base_ref"] = base_ref
        if include_base_validation_context:
            payload["layout_signature_base_validation_context"] = context.get(
                "layout_signature_base_validation_context",
                {},
            )
        return payload

    @staticmethod
    def _layout_signature_structure_example(context: dict[str, Any]) -> dict[str, Any]:
        """Define um exemplo executavel da estrutura esperada do candidato."""
        execution_context = FallbackProblemContextBuilder._candidate_execution_context(context)
        scope = context.get("escopo_permitido")
        base_ref = context.get("layout_signature_base_ref")
        return {
            "modelo_resposta_no_nivel_raiz": {
                "tipo_artefato": "layout_signature_candidato",
                "status_layout": "candidato",
                "escopo_correcao": scope,
                "document_id": execution_context.get("document_id"),
                "execution_id_origem": execution_context.get("execution_id_origem"),
                "base_layout_signature": (
                    None if scope == FallbackProblemContextBuilder.CREATION_SCOPE else base_ref
                ),
                "fontes_relevantes": {},
                "regras_deteccao_mudanca": [],
                "mapeamento_canonico": {
                    "campo.permitido": {
                        "tipo_origem": "celula_de_tabela",
                        "arquivo_origem": "tables/table001.json",
                        "obrigatorio": True,
                    }
                },
                "metadados_estruturais_evidencia": {},
            },
            "secoes_necessarias": {
                "fontes_relevantes": "objeto JSON",
                "regras_deteccao_mudanca": "lista JSON",
                "mapeamento_canonico": "objeto JSON nao vazio",
                "metadados_estruturais_evidencia": "objeto JSON",
            },
            "tipos_origem_permitidos": [
                "valor_fixo",
                "campo_derivado",
                "campo_json",
                "bloco_textual",
                "cabecalho_de_tabela",
                "celula_de_tabela",
                "linhas_de_tabela",
                "juncao_de_registros_json",
            ],
            "formatos_de_origem": {
                "valor_fixo": {
                    "tipo_origem": "valor_fixo",
                    "valor_fixo": "valor estavel declarado pelo layout",
                    "obrigatorio": True,
                },
                "campo_derivado": {
                    "tipo_origem": "campo_derivado",
                    "campo_origem": "outro.path.ja.resolvido",
                    "obrigatorio": True,
                },
                "campo_json": {
                    "tipo_origem": "campo_json",
                    "arquivo_origem": "manifesto_execucao.json",
                    "caminho_json": "campo.publicado.no.artefato",
                    "obrigatorio": True,
                },
                "bloco_textual": {
                    "tipo_origem": "bloco_textual",
                    "arquivo_origem": "blocks/blocks.jsonl",
                    "padrao": "expressao regular que encontra o valor",
                    "obrigatorio": True,
                },
                "cabecalho_de_tabela": {
                    "tipo_origem": "cabecalho_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "seletor_coluna": {
                        "indice_coluna_esperado": 1,
                    },
                    "obrigatorio": True,
                },
                "celula_de_tabela": {
                    "tipo_origem": "celula_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "seletor_linha": {
                        "coluna_rotulo": 0,
                        "valor_aceito": "rotulo exatamente observado",
                        "indice_linha_esperado": 0,
                    },
                    "seletor_coluna": {
                        "indice_coluna_esperado": 1,
                    },
                    "obrigatorio": True,
                },
                "linhas_de_tabela": {
                    "tipo_origem": "linhas_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "linha_inicial": 0,
                    "linha_final": 10,
                    "indices_colunas": [0, 1],
                    "obrigatorio": True,
                },
                "juncao_de_registros_json": {
                    "tipo_origem": "juncao_de_registros_json",
                    "fontes": [
                        {
                            "arquivo_origem": "charts/chart001.json",
                            "caminho_chave": "periodo",
                            "campos": [
                                {"campo_saida": "valor_a", "caminho_json": "valor"}
                            ],
                        },
                        {
                            "arquivo_origem": "charts/chart002.json",
                            "caminho_chave": "periodo",
                            "campos": [
                                {"campo_saida": "valor_b", "caminho_json": "valor"}
                            ],
                        },
                    ],
                    "obrigatorio": True,
                },
            },
            "exemplo_de_mapeamento": {
                "valor_fixo": {
                    "campo.de_saida": {
                        "tipo_origem": "valor_fixo",
                        "valor_fixo": "unidades",
                        "obrigatorio": True,
                    }
                },
                "celula_de_tabela_com_seletores": {
                    "colecao[dimensao=valor].medidas[papel=referencia]": {
                        "tipo_origem": "celula_de_tabela",
                        "arquivo_origem": "tables/table001.json",
                        "papel": "referencia",
                        "seletor_linha": {
                            "tipo_match": "exato",
                            "coluna_rotulo": 0,
                            "valor_aceito": "rotulo observado",
                            "indice_linha_esperado": 12,
                        },
                        "seletor_coluna": {
                            "indice_coluna_esperado": 1,
                            "contexto_observado": "valor publicado",
                        },
                        "obrigatorio": True,
                    }
                },
            },
        }

    @staticmethod
    def _candidate_execution_context(context: dict[str, Any]) -> dict[str, Any]:
        """Monta somente os identificadores que o candidato precisa devolver."""
        fallback_context = context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            fallback_context = {}
        scope = context.get("escopo_permitido")
        base_ref = context.get("layout_signature_base_ref")
        return {
            "document_id": fallback_context.get("document_id"),
            "execution_id_origem": fallback_context.get("execution_id"),
            "escopo_correcao": scope,
            "base_layout_signature": (
                None if scope == FallbackProblemContextBuilder.CREATION_SCOPE else base_ref
            ),
        }

    @staticmethod
    def _failure_summary(context: dict[str, Any]) -> dict[str, Any]:
        """Resumo de falha para fluxos de redescoberta ampla."""
        failure = context.get("falha", {})
        if not isinstance(failure, dict):
            return {}
        return {
            "codigos_falha": failure.get("codigos_falha", []),
            "motivos": failure.get("motivos", []),
        }

    @staticmethod
    def _weak_layout_reference(context: dict[str, Any]) -> dict[str, Any]:
        """Referencia fraca ao layout anterior, usada apenas como pista."""
        layout_context = context.get("layout_signature_relevante", {})
        if not isinstance(layout_context, dict) or not layout_context:
            return {}
        identification = layout_context.get("identificacao", {})
        return {
            "entidade": (
                identification.get("entidade") or identification.get("empresa")
                if isinstance(identification, dict)
                else None
            ),
            "tipo_documento": (
                identification.get("tipo_documento")
                if isinstance(identification, dict)
                else None
            ),
            "fontes_relevantes_antigas": layout_context.get("fontes_relevantes", []),
            "observacao": (
                "usar apenas como pista; redescobrir fontes pelo inventario atual"
            ),
        }

    @staticmethod
    def _broken_output_fields(unresolved_required: list[dict[str, Any]]) -> list[str]:
        """Lista campos de saida afetados por falhas de resolucao."""
        fields = {
            str(item.get("campo_saida", "")).strip()
            for item in unresolved_required
            if str(item.get("campo_saida", "")).strip()
        }
        return sorted(fields)

    def _collect_origin_files(
        self,
        *,
        rejected_rules: list[dict[str, Any]],
        unresolved_required: list[dict[str, Any]],
        layout: dict[str, Any],
        broken_fields: list[str],
    ) -> list[str]:
        """Coleta arquivos de extracao que explicam as falhas classificadas."""
        origin_files: set[str] = set()

        for rule in rejected_rules:
            evidence = rule.get("evidencia", {})
            if isinstance(evidence, dict):
                origin = str(evidence.get("arquivo_origem", "")).strip()
                if origin:
                    origin_files.add(origin)

        for item in unresolved_required:
            origin = str(item.get("arquivo_origem", "")).strip()
            if origin:
                origin_files.add(origin)

        mapping = layout.get("mapeamento_canonico", {})
        if isinstance(mapping, dict):
            for field in broken_fields:
                entry = mapping.get(field)
                if isinstance(entry, dict):
                    origin = str(entry.get("arquivo_origem", "")).strip()
                    if origin:
                        origin_files.add(origin)

        return sorted(origin_files)

    def _relevant_layout_context(
        self,
        *,
        layout: dict[str, Any],
        broken_fields: list[str],
        origin_files: list[str],
    ) -> dict[str, Any]:
        """Recorta o layout signature para os trechos ligados a falha."""
        mapping = layout.get("mapeamento_canonico", {})
        relevant_mapping: dict[str, Any] = {}
        if isinstance(mapping, dict):
            for path, entry in mapping.items():
                if not isinstance(entry, dict):
                    continue
                origin = str(entry.get("arquivo_origem", "")).strip()
                path_text = str(path)
                if path_text in broken_fields or origin in origin_files:
                    relevant_mapping[path_text] = self._truncate_json(entry)

        rules = layout.get("regras_deteccao_mudanca", [])
        relevant_rules: list[Any] = []
        if isinstance(rules, list):
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                origin = str(rule.get("arquivo_origem", "")).strip()
                if origin and origin in origin_files:
                    relevant_rules.append(self._truncate_json(rule))

        return {
            "identificacao": {
                "entidade": layout.get("entidade") or layout.get("empresa"),
                "tipo_documento": layout.get("tipo_documento"),
                "versao_artefato": layout.get("versao_artefato"),
                "contrato_semantico_ref": layout.get("contrato_semantico_ref"),
            },
            "mapeamento_canonico_relevante": relevant_mapping,
            "regras_deteccao_mudanca_relevantes": relevant_rules,
            "fontes_relevantes": origin_files,
        }

    def _relevant_contract_context(
        self,
        *,
        contract: dict[str, Any],
        broken_fields: list[str],
    ) -> dict[str, Any]:
        """Recorta o contrato semantico sem incluir conteudo desnecessario."""
        semantic = contract.get("contrato_semantico", {})
        if not isinstance(semantic, dict):
            semantic = {}
        schema_saida = contract.get("schema_saida", {})
        fixed_paths = contract_literal_paths(schema_saida)
        relevant_requirements = self._dynamic_mapping_requirements(
            semantic.get("requisitos_mapeamento", {})
            if isinstance(semantic, dict)
            else {},
            fixed_paths=set(fixed_paths),
        )
        structure = {
            "campos_raiz": sorted(
                schema_saida.keys()
                if isinstance(schema_saida, dict)
                else []
            ),
            "paths_permitidos": sorted(schema_paths(schema_saida) - set(fixed_paths)),
            "arrays_que_exigem_seletor": sorted(schema_array_paths(schema_saida)),
        }
        return {
            "identificacao": {
                "nome": contract.get("nome"),
                "versao": contract.get("versao"),
                "dominio": contract.get("dominio"),
            },
            "contrato_semantico": {
                "entidades": semantic.get("entidades", {}),
                "metricas": semantic.get("metricas", {}),
                "requisitos_mapeamento": relevant_requirements,
            },
            "estrutura_schema_saida": structure,
        }

    @staticmethod
    def _dynamic_mapping_requirements(
        requirements: Any,
        *,
        fixed_paths: set[str],
    ) -> dict[str, Any]:
        """Remove do payload os contextos ja resolvidos por literais do contrato."""
        if not isinstance(requirements, dict):
            return {}
        projected = deepcopy(requirements)
        fields = projected.get("campos_obrigatorios", [])
        if not isinstance(fields, list):
            return projected

        for requirement in fields:
            if not isinstance(requirement, dict):
                continue
            path = str(requirement.get("path", "")).strip()
            parent_path, separator, _leaf = path.rpartition(".")
            if not separator:
                continue
            observations = requirement.get("observacoes_obrigatorias", [])
            if not isinstance(observations, list):
                continue
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                context_fields = observation.get("campos_contexto_obrigatorios", [])
                if not isinstance(context_fields, list):
                    continue
                observation["campos_contexto_obrigatorios"] = [
                    field
                    for field in context_fields
                    if f"{parent_path}.{str(field).strip()}" not in fixed_paths
                ]
        return projected

    @staticmethod
    def _mappable_targets(contract_context: Any) -> list[dict[str, Any]]:
        """Deriva alvos explicitamente declarados pelo contrato para a LLM."""
        requirements = mapping_requirements_from_context(
            contract_context
        )
        structure = contract_context.get("estrutura_schema_saida", {})
        array_paths = (
            structure.get("arrays_que_exigem_seletor", [])
            if isinstance(structure, dict)
            else []
        )
        if not isinstance(array_paths, list):
            array_paths = []
        return mappable_targets_payload(requirements, array_paths=array_paths)

    def _schema_fragments_for_fields(
        self,
        schema_saida: Any,
        broken_fields: list[str],
    ) -> dict[str, Any]:
        """Extrai fragmentos do schema_saida relacionados aos campos quebrados."""
        if not isinstance(schema_saida, dict):
            return {}
        if not broken_fields:
            return self._truncate_json(schema_saida, max_depth=2)

        fragments: dict[str, Any] = {}
        for field in broken_fields:
            root = field.split(".", maxsplit=1)[0]
            if root in schema_saida:
                fragments[root] = self._truncate_json(schema_saida[root], max_depth=4)
        return fragments


    def _truncate_json(self, value: Any, *, max_depth: int = 5) -> Any:
        """Reduz estruturas grandes para caberem no contexto de problema."""
        if max_depth <= 0:
            return "<truncado>"
        if isinstance(value, dict):
            return {
                str(key): self._truncate_json(item, max_depth=max_depth - 1)
                for key, item in list(value.items())[:20]
            }
        if isinstance(value, list):
            return [
                self._truncate_json(item, max_depth=max_depth - 1)
                for item in value[:8]
            ]
        if isinstance(value, str) and len(value) > 800:
            return f"{value[:800]}..."
        return value


FALLBACK_PROBLEM_CONTEXT_BUILDER = FallbackProblemContextBuilder()
