from __future__ import annotations

import json

from typing import Any

from helpers import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from plugins.clients.llm_client import (
    FALLBACK_LLM_CLIENT,
    FallbackLlmClient,
    FallbackLlmClientError,
)
from plugins.clients.minio_storage_client import MinioStorageClient
from pydantic import ValidationError

from .fallback_llm_models import LayoutSignatureCandidate


class FallbackLlmService:
    """Carrega e valida o contexto inicial do fallback assistido por LLM."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        minio_client: MinioStorageClient | None = None,
        llm_client: FallbackLlmClient | None = None,
    ) -> None:
        """Inicializa dependencias com injecao opcional para testes."""
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._minio_client = minio_client
        self.llm_client = llm_client or FALLBACK_LLM_CLIENT

    @property
    def minio_client(self) -> MinioStorageClient:
        """Cria o cliente MinIO apenas quando o fallback precisar ler artefatos."""
        if self._minio_client is None:
            config = self.config_loader.load_local_platform_config()
            self._minio_client = MinioStorageClient(config)
        return self._minio_client

    def load_fallback_context(self, conf: dict[str, object]) -> dict[str, Any]:
        """Carrega e valida o pacote minimo de artefatos da execucao com falha."""
        fallback_context = {
            "company_slug": self._required_text(conf, "company_slug"),
            "document_id": self._required_text(conf, "document_id"),
            "execution_id": self._required_text(conf, "execution_id"),
            "manifest_key": self._required_text(conf, "manifest_key"),
            "trigger_origin_dag": self._required_text(conf, "trigger_origin_dag"),
        }

        validation_key, validation = self.load_validation_artifact(fallback_context)
        self._assert_validation_requires_fallback(validation, validation_key)
        audit_key, audit = self.load_audit_artifact(fallback_context)
        layout_key, layout = self.load_base_layout_signature(fallback_context)
        contract_key, contract = self.load_semantic_contract(fallback_context)
        manifest_key, manifest = self.load_extraction_manifest(fallback_context)
        fallback_classification = self.classify_fallback_scope(validation, audit)

        artifact_uris = manifest.get("artifact_uris")
        if not isinstance(artifact_uris, list) or not artifact_uris:
            raise RuntimeError(f"Manifesto de extracao sem artifact_uris: {manifest_key}")
        fallback_problem_context = self.build_fallback_problem_context(
            validation=validation,
            audit=audit,
            layout=layout,
            contract=contract,
            manifest=manifest,
            classification=fallback_classification,
        )
        fallback_problem_context["fallback_context"] = fallback_context
        fallback_problem_context["layout_signature_base_ref"] = {
            "versao": layout.get("versao_artefato"),
            "object_key": layout_key,
        }
        fallback_problem_context["layout_signature_base_editable_sections"] = {
            "fontes_relevantes": layout.get("fontes_relevantes", {}),
            "regras_deteccao_mudanca": layout.get("regras_deteccao_mudanca", []),
            "mapeamento_canonico": layout.get("mapeamento_canonico", {}),
        }
        fallback_problem_context["layout_signature_base_validation_context"] = {
            "mapeamento_canonico_paths": sorted(
                layout.get("mapeamento_canonico", {}).keys()
                if isinstance(layout.get("mapeamento_canonico"), dict)
                else []
            ),
            "regras_deteccao_mudanca_ids": [
                str(rule.get("id_regra"))
                for rule in layout.get("regras_deteccao_mudanca", [])
                if isinstance(rule, dict) and rule.get("id_regra")
            ],
        }

        return {
            "fallback_context": fallback_context,
            "validation_status": validation["status_compatibilidade"]["status"],
            "failure_codes": validation["status_compatibilidade"].get("codigos_alerta", []),
            "fallback_scope": fallback_classification["fallback_scope"],
            "fallback_classification": fallback_classification,
            "fallback_problem_context": fallback_problem_context,
            "llm_constraints": {
                "fallback_scope": fallback_classification["fallback_scope"],
                "chamar_llm": fallback_classification["llm_permitida"],
                "permitir_correcao_parcial": (
                    fallback_classification["fallback_scope"] == self.PARTIAL_SCOPE
                ),
                "permitir_regeneracao_total": (
                    fallback_classification["fallback_scope"] == self.FULL_REMAP_SCOPE
                ),
            },
            "object_keys": {
                "validacao_layout_signature": validation_key,
                "auditoria_resolucao": audit_key,
                "layout_signature_base": layout_key,
                "contrato_semantico": contract_key,
                "manifesto_extracao": manifest_key,
            },
            "artifact_counts": {
                "regras_executadas": len(validation.get("regras_executadas", [])),
                "auditoria_resolucao": len(audit.get("auditoria_resolucao", [])),
                "mapeamento_canonico": len(layout.get("mapeamento_canonico", {})),
                "schema_saida_campos_raiz": len(contract.get("schema_saida", {})),
                "artefatos_extracao": len(artifact_uris),
            },
        }

    def classify_fallback_scope(
        self,
        validation: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        """Classifica deterministicamente o escopo permitido para a futura LLM."""
        status_info = validation.get("status_compatibilidade")
        if not isinstance(status_info, dict):
            raise RuntimeError("Nao foi possivel classificar fallback: validacao malformada.")

        status = str(status_info.get("status", "")).strip()
        if status == "compativel":
            raise RuntimeError("Fallback recusado: validacao compativel nao aciona DAG 3.")
        if status != "incompativel":
            return self._classification(
                scope=self.UNSUPPORTED_SCOPE,
                reasons=[f"status_compatibilidade desconhecido: {status or '<vazio>'}"],
                rejected_rules=[],
                unresolved_required=[],
                failure_codes=status_info.get("codigos_alerta", []),
            )

        rejected_rules = self._rejected_rules(validation)
        unresolved_required = self._unresolved_required_audit_items(audit)
        failure_codes = status_info.get("codigos_alerta", [])

        total_reasons: list[str] = []
        partial_reasons: list[str] = []
        unsupported_reasons: list[str] = []

        for rule in rejected_rules:
            rule_type = str(rule.get("tipo_teste", "")).strip()
            rule_id = str(rule.get("id_regra", "regra_sem_id")).strip()
            if rule_type == "arquivo_existe":
                total_reasons.append(f"tabela ou artefato critico ausente em {rule_id}")
            elif rule_type == "secao_existe":
                total_reasons.append(f"secao critica ausente em {rule_id}")
            elif rule_type == "perfil_colunas_periodo_existe_em_tabela":
                if self._has_unresolved_layout_profile(rule):
                    total_reasons.append(f"perfil critico declarado no layout nao resolvido em {rule_id}")
                else:
                    partial_reasons.append(f"coluna critica ausente em {rule_id}")
            elif rule_type == "linha_existe_em_tabela":
                partial_reasons.append(f"linha critica ausente em {rule_id}")
            elif rule_type == "valor_normalizavel":
                partial_reasons.append(f"valor nao normalizavel em {rule_id}")
            else:
                unsupported_reasons.append(
                    f"tipo de regra reprovada sem classificador automatico: {rule_type or '<vazio>'}"
                )

        if len(rejected_rules) >= 3:
            total_reasons.append("multiplas regras deterministicas criticas reprovadas")

        if unresolved_required:
            if len(unresolved_required) <= 2:
                partial_reasons.append("poucos campos obrigatorios nao resolvidos")
            else:
                total_reasons.append("multiplos campos obrigatorios nao resolvidos")

            if any(str(item.get("status_resolucao", "")) == "erro" for item in unresolved_required):
                partial_reasons.append("campo obrigatorio com seletor quebrado")

        if total_reasons:
            return self._classification(
                scope=self.FULL_REMAP_SCOPE,
                reasons=total_reasons,
                rejected_rules=rejected_rules,
                unresolved_required=unresolved_required,
                failure_codes=failure_codes,
            )

        if partial_reasons:
            return self._classification(
                scope=self.PARTIAL_SCOPE,
                reasons=partial_reasons,
                rejected_rules=rejected_rules,
                unresolved_required=unresolved_required,
                failure_codes=failure_codes,
            )

        if unsupported_reasons:
            return self._classification(
                scope=self.UNSUPPORTED_SCOPE,
                reasons=unsupported_reasons,
                rejected_rules=rejected_rules,
                unresolved_required=unresolved_required,
                failure_codes=failure_codes,
            )

        return self._classification(
            scope=self.UNSUPPORTED_SCOPE,
            reasons=["validacao incompativel sem falhas classificaveis para fallback automatico"],
            rejected_rules=rejected_rules,
            unresolved_required=unresolved_required,
            failure_codes=failure_codes,
        )

    def build_fallback_problem_context(
        self,
        *,
        validation: dict[str, Any],
        audit: dict[str, Any],
        layout: dict[str, Any],
        contract: dict[str, Any],
        manifest: dict[str, Any],
        classification: dict[str, Any],
    ) -> dict[str, Any]:
        """Monta o pacote estruturado que limita o problema para a futura LLM."""
        rejected_rules = self._rejected_rules(validation)
        unresolved_required = self._unresolved_required_audit_items(audit)
        broken_fields = self._broken_output_fields(unresolved_required)
        origin_files = self._collect_origin_files(
            rejected_rules=rejected_rules,
            unresolved_required=unresolved_required,
            layout=layout,
            broken_fields=broken_fields,
        )

        return {
            "tipo_artefato": "fallback_problem_context",
            "status": "contexto_montado",
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
            "amostras_extracao": self._load_extraction_samples(
                manifest=manifest,
                origin_files=origin_files,
            ),
        }

    def generate_candidate_layout(
        self,
        fallback_problem_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Chama a LLM e valida que a resposta e um layout candidato JSON."""
        constraints = fallback_problem_context.get("llm_constraints", {})
        if not isinstance(constraints, dict) or not constraints.get("chamar_llm"):
            raise RuntimeError("Contexto de fallback nao permite chamada LLM.")

        try:
            parsed, raw_content = self.llm_client.generate_json(
                system_prompt=self._candidate_layout_system_prompt(),
                user_payload=fallback_problem_context,
            )
        except FallbackLlmClientError as exc:
            raise RuntimeError(f"Falha ao chamar LLM de fallback: {exc}") from exc

        candidate_model = self.validate_candidate_layout(
            parsed,
            fallback_problem_context,
        )
        return {
            "tipo_artefato": "resposta_llm_layout_signature_candidato",
            "candidate_layout": candidate_model.model_dump(mode="json", exclude_none=True),
            "raw_response": raw_content,
        }

    def load_validation_artifact(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o `validacao_layout_signature.json` produzido pela DAG 2."""
        key = self._resolution_artifact_key(fallback_context, "validacao_layout_signature.json")
        return key, self._load_json_object(key, "validacao_layout_signature")

    def load_audit_artifact(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o `auditoria_resolucao.json` da execucao que acionou o fallback."""
        key = self._resolution_artifact_key(fallback_context, "auditoria_resolucao.json")
        return key, self._load_json_object(key, "auditoria_resolucao")

    def load_base_layout_signature(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le a versao vigente do layout usada como base para o candidato."""
        config = self.config_loader.load_local_platform_config()
        key = (
            f"{config.minio_layout_prefix.rstrip('/')}/"
            f"{fallback_context['company_slug']}/v4.0.0/layout_signature_deterministico.json"
        )
        return key, self._load_json_object(key, "layout_signature_base")

    def load_semantic_contract(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o contrato semantico que limita os campos alteraveis pelo fallback."""
        config = self.config_loader.load_local_platform_config()
        key = f"{config.minio_contract_prefix.rstrip('/')}/v1.2.0/contrato_semantico_construtora.json"
        return key, self._load_json_object(key, "contrato_semantico")

    def load_extraction_manifest(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o manifesto de extracao para localizar os artefatos da DAG 1."""
        key = fallback_context["manifest_key"]
        return key, self._load_json_object(key, "manifesto_extracao")

    def _resolution_artifact_key(self, fallback_context: dict[str, str], filename: str) -> str:
        """Monta o object key de um artefato de resolucao da DAG 2."""
        config = self.config_loader.load_local_platform_config()
        return (
            f"{config.minio_resolution_prefix.rstrip('/')}/{fallback_context['company_slug']}/"
            f"document_id={fallback_context['document_id']}/"
            f"execution_id={fallback_context['execution_id']}/resolution/{filename}"
        )

    def _load_json_object(self, object_key: str, artifact_name: str) -> dict[str, Any]:
        """Le um JSON do MinIO e adiciona contexto ao erro de carregamento."""
        try:
            loaded = self.minio_client.get_json(object_key=object_key)
        except Exception as exc:
            raise RuntimeError(
                f"Nao foi possivel carregar {artifact_name} no MinIO: {object_key}"
            ) from exc
        return loaded

    def _classification(
        self,
        *,
        scope: str,
        reasons: list[str],
        rejected_rules: list[dict[str, Any]],
        unresolved_required: list[dict[str, Any]],
        failure_codes: Any,
    ) -> dict[str, Any]:
        """Monta a resposta padronizada da classificacao deterministica."""
        return {
            "fallback_scope": scope,
            "llm_permitida": scope != self.UNSUPPORTED_SCOPE,
            "motivos": sorted(set(reasons)),
            "codigos_falha": self._as_text_list(failure_codes),
            "metricas": {
                "regras_reprovadas": len(rejected_rules),
                "campos_obrigatorios_nao_resolvidos": len(unresolved_required),
            },
            "evidencias": {
                "regras_reprovadas": [
                    self._compact_rule_evidence(rule)
                    for rule in rejected_rules
                ],
                "campos_obrigatorios_nao_resolvidos": [
                    self._compact_audit_evidence(item)
                    for item in unresolved_required
                ],
            },
        }

    @staticmethod
    def _candidate_layout_system_prompt() -> str:
        """Prompt base que limita a LLM a devolver somente um layout candidato."""
        return (
            "Voce atua como gerador de layout signature candidato para fallback "
            "de documentos desestruturados. "
            "Recebera um contexto ja preparado pela DAG 3 contendo: falhas da DAG 2, "
            "trechos relevantes do layout signature base, contrato semantico, amostras "
            "de extracao e escopo permitido de correcao. "
            "Sua unica saida deve ser um objeto JSON valido representando "
            "layout_signature_candidato. "
            "Nao explique, nao use markdown e nao devolva texto fora do JSON. "
            "Use exatamente o document_id, execution_id_origem e base_layout_signature "
            "informados no contexto; nao invente nem altere esses identificadores. "
            "Ajuste somente o necessario para que a DAG 2 possa revalidar o candidato. "
            "As unicas secoes alteraveis sao: fontes_relevantes, regras_deteccao_mudanca, "
            "mapeamento_canonico e metadados_estruturais_evidencia. "
            "Dentro dessas secoes, voce pode atualizar seletores, arquivos de origem, "
            "caminhos de artefatos e metadados estruturais usados como evidencia. "
            "Nao gere schema_saida_resolvido. Nao escreva valores finais de negocio. "
            "Nao crie campos fora do schema_saida do contrato semantico. "
            "Nao altere referencia_contrato_semantico, regras_execucao, versao_artefato "
            "final, contrato semantico ou qualquer layout ja publicado. "
            "Nao gere analise_semantica_llm nem proposta_atualizacao_layout_signature. "
            "Se o escopo permitido for correcao_parcial_mapeamento, preserve mapeamentos "
            "nao relacionados a falha e retorne o mapeamento_canonico completo do candidato. "
            "Se for regeneracao_total_mapeamento, ainda assim "
            "mantenha o candidato limitado ao contrato semantico recebido. "
            "O JSON deve seguir este formato exato: "
            "{"
            "\"tipo_artefato\":\"layout_signature_candidato\","
            "\"status_layout\":\"candidato\","
            "\"escopo_correcao\":\"...\","
            "\"document_id\":\"...\","
            "\"execution_id_origem\":\"...\","
            "\"base_layout_signature\":{\"versao\":\"...\",\"object_key\":\"...\"},"
            "\"fontes_relevantes\":{},"
            "\"regras_deteccao_mudanca\":[],"
            "\"mapeamento_canonico\":{},"
            "\"metadados_estruturais_evidencia\":{},"
            "\"publicacao_automatica_habilitada\":true"
            "}."
        )

    def validate_candidate_layout(
        self,
        candidate: dict[str, Any],
        fallback_problem_context: dict[str, Any],
    ) -> LayoutSignatureCandidate:
        """Valida o candidato da LLM com Pydantic e regras do contrato carregado."""
        if self._contains_forbidden_llm_key(candidate):
            raise RuntimeError(
                "Resposta da LLM tentou alterar campos proibidos para o fallback."
            )

        try:
            candidate_model = LayoutSignatureCandidate.model_validate(candidate)
        except ValidationError as exc:
            raise RuntimeError(
                "Resposta da LLM nao respeita o contrato Pydantic do layout "
                f"signature candidato: {exc}"
            ) from exc

        schema_roots = self._contract_schema_roots_from_context(fallback_problem_context)
        schema_paths = self._contract_schema_paths_from_context(fallback_problem_context)
        for mapping_path in candidate_model.mapeamento_canonico:
            if not self._mapping_path_is_in_contract(
                mapping_path,
                schema_roots,
                schema_paths,
            ):
                raise RuntimeError(
                    "Resposta da LLM tentou criar candidato com mapeamento para "
                    f"campo fora do schema_saida do contrato: {mapping_path}."
                )

        allowed_scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        if allowed_scope and candidate_model.escopo_correcao != allowed_scope:
            raise RuntimeError(
                "Resposta da LLM tentou usar escopo diferente do permitido pela "
                f"classificacao deterministica: {candidate_model.escopo_correcao}."
            )
        self._validate_candidate_lineage(candidate_model, fallback_problem_context)
        self._validate_candidate_allowed_scope(candidate_model, fallback_problem_context)
        self._validate_candidate_does_not_write_final_values(candidate_model)
        self._validate_partial_candidate_does_not_remove_unrelated_mappings(
            candidate_model,
            fallback_problem_context,
        )
        return candidate_model

    @staticmethod
    def _validate_candidate_lineage(
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Confirma que o candidato usa a linhagem recebida no contexto."""
        fallback_context = fallback_problem_context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            raise RuntimeError("Contexto de fallback ausente para validar linhagem do candidato.")

        expected_document_id = str(fallback_context.get("document_id", "")).strip()
        expected_execution_id = str(fallback_context.get("execution_id", "")).strip()
        if candidate.document_id != expected_document_id:
            raise RuntimeError(
                "Layout candidato retornou document_id diferente do contexto de fallback."
            )
        if candidate.execution_id_origem != expected_execution_id:
            raise RuntimeError(
                "Layout candidato retornou execution_id_origem diferente do contexto de fallback."
            )

        base_ref = fallback_problem_context.get("layout_signature_base_ref", {})
        if not isinstance(base_ref, dict):
            raise RuntimeError("Referencia do layout base ausente para validar candidato.")
        expected_base_key = str(base_ref.get("object_key", "")).strip()
        if candidate.base_layout_signature.object_key != expected_base_key:
            raise RuntimeError(
                "Layout candidato retornou base_layout_signature.object_key diferente do layout base."
            )

    def _validate_candidate_allowed_scope(
        self,
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Garante que candidato total so apareca em ruptura estrutural ampla."""
        if candidate.escopo_correcao != self.FULL_REMAP_SCOPE:
            return
        allowed_scope = str(fallback_problem_context.get("escopo_permitido", "")).strip()
        if allowed_scope != self.FULL_REMAP_SCOPE:
            raise RuntimeError(
                "Layout candidato tentou regeneracao total sem ruptura estrutural ampla."
            )

    def _validate_candidate_does_not_write_final_values(
        self,
        candidate: LayoutSignatureCandidate,
    ) -> None:
        """Bloqueia sinais de valores finais de negocio no candidato de layout."""
        candidate_dict = candidate.model_dump(mode="json", exclude_none=True)
        forbidden_keys = {
            "valor_resolvido",
            "valor_final",
            "valor_extraido",
            "schema_saida_resolvido",
            "dados_resolvidos",
            "resultado_resolvido",
        }
        if self._contains_any_key(candidate_dict, forbidden_keys):
            raise RuntimeError(
                "Layout candidato tentou escrever valores finais em vez de seletores/layout."
            )

    def _validate_partial_candidate_does_not_remove_unrelated_mappings(
        self,
        candidate: LayoutSignatureCandidate,
        fallback_problem_context: dict[str, Any],
    ) -> None:
        """Impede que correcao parcial apague mapeamentos nao relacionados a falha."""
        if candidate.escopo_correcao != self.PARTIAL_SCOPE:
            return

        base_context = fallback_problem_context.get("layout_signature_base_validation_context", {})
        if not isinstance(base_context, dict):
            return
        base_paths_raw = base_context.get("mapeamento_canonico_paths", [])
        if not isinstance(base_paths_raw, list):
            return

        base_paths = {str(path) for path in base_paths_raw}
        candidate_paths = set(candidate.mapeamento_canonico)
        if not base_paths or not candidate_paths:
            return

        missing_paths = base_paths - candidate_paths
        if missing_paths:
            sample = sorted(missing_paths)[:10]
            raise RuntimeError(
                "Layout candidato parcial removeu mapeamentos do layout base. "
                f"Exemplos: {sample}."
            )

    @staticmethod
    def _contract_schema_roots_from_context(
        fallback_problem_context: dict[str, Any],
    ) -> set[str]:
        """Extrai campos raiz do schema_saida incluidos no contexto da LLM."""
        contract = fallback_problem_context.get("contrato_semantico_relevante", {})
        if not isinstance(contract, dict):
            return set()
        roots = contract.get("schema_saida_campos_raiz", [])
        if not isinstance(roots, list):
            return set()
        return {str(root).strip() for root in roots if str(root).strip()}

    @staticmethod
    def _contract_schema_paths_from_context(
        fallback_problem_context: dict[str, Any],
    ) -> set[str]:
        """Extrai paths declarados no schema_saida incluidos no contexto da LLM."""
        contract = fallback_problem_context.get("contrato_semantico_relevante", {})
        if not isinstance(contract, dict):
            return set()
        paths = contract.get("schema_saida_paths", [])
        if not isinstance(paths, list):
            return set()
        return {str(path).strip() for path in paths if str(path).strip()}

    @staticmethod
    def _mapping_path_is_in_contract(
        path: str,
        schema_roots: set[str],
        schema_paths: set[str],
    ) -> bool:
        """Confirma que o path de mapeamento aponta para path do contrato."""
        if not schema_roots:
            return False
        normalized = path.strip()
        if normalized.startswith("mapeamento_canonico."):
            normalized = normalized.removeprefix("mapeamento_canonico.")
        normalized = FallbackLlmService._normalize_mapping_path(normalized)
        if schema_paths and normalized not in schema_paths:
            return False
        root = normalized.split(".", maxsplit=1)[0]
        return root in schema_roots

    @staticmethod
    def _normalize_mapping_path(path: str) -> str:
        """Remove filtros de array para comparar mapeamento com schema_saida."""
        parts = []
        for part in path.split("."):
            clean = part.split("[", maxsplit=1)[0].strip()
            if clean:
                parts.append(clean)
        return ".".join(parts)

    def _schema_saida_paths(self, schema_saida: Any) -> list[str]:
        """Lista paths navegaveis declarados no schema_saida do contrato."""
        paths: set[str] = set()
        self._collect_schema_paths(schema_saida, prefix="", paths=paths)
        return sorted(paths)

    def _collect_schema_paths(self, value: Any, *, prefix: str, paths: set[str]) -> None:
        """Percorre schema_saida declarando caminhos de objetos e folhas."""
        if prefix:
            paths.add(prefix)
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                self._collect_schema_paths(item, prefix=child, paths=paths)
            return
        if isinstance(value, list) and value:
            self._collect_schema_paths(value[0], prefix=prefix, paths=paths)

    def _contains_forbidden_llm_key(self, value: Any) -> bool:
        """Bloqueia chaves que indicam tentativa de alterar fronteiras proibidas."""
        forbidden = {
            "schema_saida_resolvido",
            "referencia_contrato_semantico",
            "contrato_semantico",
            "regras_execucao",
            "versao_artefato",
        }
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key) in forbidden:
                    return True
                if self._contains_forbidden_llm_key(item):
                    return True
        if isinstance(value, list):
            return any(self._contains_forbidden_llm_key(item) for item in value)
        return False

    def _contains_any_key(self, value: Any, forbidden: set[str]) -> bool:
        """Busca qualquer chave proibida em uma estrutura JSON."""
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key) in forbidden:
                    return True
                if self._contains_any_key(item, forbidden):
                    return True
        if isinstance(value, list):
            return any(self._contains_any_key(item, forbidden) for item in value)
        return False

    @staticmethod
    def _rejected_rules(validation: dict[str, Any]) -> list[dict[str, Any]]:
        """Filtra regras deterministicas reprovadas na validacao da DAG 2."""
        rules = validation.get("regras_executadas", [])
        if not isinstance(rules, list):
            return []
        return [
            rule
            for rule in rules
            if isinstance(rule, dict) and str(rule.get("status", "")).strip() == "reprovada"
        ]

    def _unresolved_required_audit_items(self, audit: dict[str, Any]) -> list[dict[str, Any]]:
        """Extrai campos obrigatorios nao resolvidos da auditoria da resolucao."""
        audit_items = audit.get("auditoria_resolucao", [])
        if isinstance(audit_items, list):
            return [
                item
                for item in audit_items
                if isinstance(item, dict)
                and bool(item.get("obrigatorio", False))
                and str(item.get("status_resolucao", "")).strip() != "resolvido"
            ]

        resolutions = audit.get("resolucoes", {})
        if not isinstance(resolutions, dict):
            return []

        unresolved: list[dict[str, Any]] = []
        for field, item in resolutions.items():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or item.get("status_resolucao") or "").strip()
            if status and status != "resolvido":
                unresolved.append(
                    {
                        "campo_saida": str(field),
                        "status_resolucao": status,
                        "tipo_origem": item.get("tipo_origem"),
                        "arquivo_origem": item.get("arquivo_origem"),
                        "evidencia": item,
                    }
                )
        return unresolved

    @staticmethod
    def _has_unresolved_layout_profile(rule: dict[str, Any]) -> bool:
        """Identifica itens incompletos em um perfil critico declarado pelo layout."""
        evidence = rule.get("evidencia", {})
        if not isinstance(evidence, dict):
            return False
        profile_items = (
            evidence.get("itens_perfil_resolvidos")
            or evidence.get("itens_resolvidos")
            or evidence.get("papeis_periodo_resolvidos", [])
        )
        if not isinstance(profile_items, list):
            return False
        for item in profile_items:
            if not isinstance(item, dict):
                continue
            observed_value = str(
                item.get("valor_encontrado")
                or item.get("cabecalho_encontrado")
                or item.get("valor_observado")
                or ""
            ).strip()
            if item.get("ok") is False or not observed_value:
                return True
        return False

    @staticmethod
    def _compact_rule_evidence(rule: dict[str, Any]) -> dict[str, Any]:
        """Reduz uma regra reprovada aos campos uteis para logs e prompt futuro."""
        evidence = rule.get("evidencia", {})
        return {
            "id_regra": rule.get("id_regra"),
            "tipo_teste": rule.get("tipo_teste"),
            "codigo_falha": rule.get("codigo_falha"),
            "arquivo_origem": evidence.get("arquivo_origem") if isinstance(evidence, dict) else None,
        }

    @staticmethod
    def _compact_audit_evidence(item: dict[str, Any]) -> dict[str, Any]:
        """Reduz uma falha de campo obrigatorio aos campos uteis para fallback."""
        return {
            "campo_saida": item.get("campo_saida"),
            "tipo_origem": item.get("tipo_origem"),
            "arquivo_origem": item.get("arquivo_origem"),
            "status_resolucao": item.get("status_resolucao"),
        }

    @staticmethod
    def _as_text_list(value: Any) -> list[str]:
        """Normaliza codigos de falha para lista textual."""
        if isinstance(value, list):
            return [str(item) for item in value]
        if value is None:
            return []
        return [str(value)]

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
                "empresa": layout.get("empresa"),
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
        return {
            "identificacao": {
                "nome": contract.get("nome"),
                "versao": contract.get("versao"),
                "dominio": contract.get("dominio"),
            },
            "schema_saida_campos_raiz": sorted(
                contract.get("schema_saida", {}).keys()
                if isinstance(contract.get("schema_saida"), dict)
                else []
            ),
            "schema_saida_paths": self._schema_saida_paths(contract.get("schema_saida", {})),
            "schema_saida_trechos_relevantes": self._schema_fragments_for_fields(
                contract.get("schema_saida", {}),
                broken_fields,
            ),
            "entidades": self._truncate_json(contract.get("entidades", {})),
            "metricas": self._truncate_json(contract.get("metricas", {})),
        }

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

    def _load_extraction_samples(
        self,
        *,
        manifest: dict[str, Any],
        origin_files: list[str],
    ) -> dict[str, Any]:
        """Carrega pequenas amostras dos artefatos de extracao associados a falha."""
        artifact_uris = manifest.get("artifact_uris", [])
        if not isinstance(artifact_uris, list):
            return {}

        samples: dict[str, Any] = {}
        for origin_file in origin_files[:5]:
            object_key = self._find_artifact_object_key(
                artifact_uris=[str(uri) for uri in artifact_uris],
                origin_file=origin_file,
            )
            if not object_key:
                samples[origin_file] = {"status": "nao_encontrado_no_manifesto"}
                continue
            samples[origin_file] = self._load_extraction_sample_object(object_key)
        return samples

    def _find_artifact_object_key(self, *, artifact_uris: list[str], origin_file: str) -> str | None:
        """Localiza no manifesto o object key de um arquivo de extracao relativo."""
        normalized_origin = origin_file.strip("/")
        for uri in artifact_uris:
            object_key = self._object_key_from_minio_uri(uri)
            if object_key.endswith(f"/extraction/{normalized_origin}") or object_key.endswith(normalized_origin):
                return object_key
        return None

    def _load_extraction_sample_object(self, object_key: str) -> dict[str, Any]:
        """Le um artefato de extracao e devolve somente uma amostra truncada."""
        try:
            raw = self.minio_client.get_bytes(object_key=object_key)
        except Exception as exc:
            return {"object_key": object_key, "status": "erro_ao_carregar", "erro": str(exc)}

        text = raw.decode("utf-8", errors="replace")
        if object_key.endswith(".json"):
            try:
                return {
                    "object_key": object_key,
                    "formato": "json",
                    "sample": self._truncate_json(json.loads(text)),
                }
            except Exception:
                return {
                    "object_key": object_key,
                    "formato": "texto",
                    "sample": text[:2000],
                }

        if object_key.endswith(".jsonl"):
            rows: list[Any] = []
            for line in text.splitlines():
                if len(rows) >= 5:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rows.append(self._truncate_json(json.loads(stripped)))
                except Exception:
                    rows.append(stripped[:500])
            return {"object_key": object_key, "formato": "jsonl", "sample": rows}

        return {"object_key": object_key, "formato": "texto", "sample": text[:2000]}

    @staticmethod
    def _object_key_from_minio_uri(uri: str) -> str:
        """Extrai object key de uma URI minio://bucket/key ou retorna a propria string."""
        if not uri.startswith("minio://"):
            return uri
        without_scheme = uri.removeprefix("minio://")
        parts = without_scheme.split("/", maxsplit=1)
        return parts[1] if len(parts) == 2 else ""

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

    @staticmethod
    def _assert_validation_requires_fallback(validation: dict[str, Any], object_key: str) -> None:
        """Bloqueia fallback quando a validacao e compativel ou esta malformada."""
        status_info = validation.get("status_compatibilidade")
        if not isinstance(status_info, dict):
            raise RuntimeError(
                "validacao_layout_signature malformado: "
                f"status_compatibilidade ausente ou invalido em {object_key}"
            )

        status = str(status_info.get("status", "")).strip()
        if not status:
            raise RuntimeError(
                "validacao_layout_signature malformado: "
                f"status_compatibilidade.status ausente em {object_key}"
            )
        if status == "compativel":
            raise RuntimeError(
                "Fallback recusado: validacao_layout_signature esta compativel "
                f"em {object_key}."
            )
        if status != "incompativel":
            raise RuntimeError(
                "Fallback recusado: status de compatibilidade desconhecido "
                f"'{status}' em {object_key}."
            )

    @staticmethod
    def _required_text(conf: dict[str, object], field: str) -> str:
        """Extrai um campo textual obrigatorio do contexto de fallback."""
        value = str(conf.get(field, "")).strip()
        if not value:
            raise RuntimeError(f"Campo obrigatorio ausente no contexto de fallback: {field}")
        return value


FALLBACK_LLM_SERVICE = FallbackLlmService()
