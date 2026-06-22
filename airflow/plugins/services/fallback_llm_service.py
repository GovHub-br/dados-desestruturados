from __future__ import annotations

from typing import Any

from helpers import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader
from plugins.clients.minio_storage_client import MinioStorageClient


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
    ) -> None:
        """Inicializa dependencias com injecao opcional para testes."""
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._minio_client = minio_client

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

        return {
            "fallback_context": fallback_context,
            "validation_status": validation["status_compatibilidade"]["status"],
            "failure_codes": validation["status_compatibilidade"].get("codigos_alerta", []),
            "fallback_scope": fallback_classification["fallback_scope"],
            "fallback_classification": fallback_classification,
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

    def load_validation_artifact(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o `validacao_layout_signature.json` produzido pela DAG 2."""
        key = self._resolution_artifact_key(fallback_context, "validacao_layout_signature.json")
        return key, self._load_json_object(key, "validacao_layout_signature")

    def load_audit_artifact(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o `auditoria_resolucao.json` da execucao que acionou o fallback."""
        key = self._resolution_artifact_key(fallback_context, "auditoria_resolucao.json")
        return key, self._load_json_object(key, "auditoria_resolucao")

    def load_base_layout_signature(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le a versao vigente do layout usada como base para futura proposta."""
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
