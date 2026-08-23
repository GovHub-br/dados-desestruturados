"""Componente especializado do caso de uso de fallback LLM."""

from __future__ import annotations

from ._common import *  # noqa: F401,F403


class FallbackStorageAccessMixin:
    def _fallback_object_key(
        self,
        fallback_context: dict[str, str],
        filename: str,
    ) -> str:
        """Monta object key de artefatos da DAG 3 sob fallback/..."""
        return f"{self._fallback_prefix(fallback_context)}/{filename}"


    def _fallback_prefix(
        self,
        fallback_context: dict[str, str],
        suffix: str | None = None,
    ) -> str:
        """Prefixo isolado para artefatos de fallback da execucao original."""
        config = self.config_loader.load_local_platform_config()
        entity_slug = str(
            fallback_context.get("entity_slug") or fallback_context.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("fallback_context sem entity_slug.")
        prefix = (
            f"fallback/{fallback_context.get('domain') or config.dominio}/{entity_slug}/"
            f"document_id={fallback_context['document_id']}/"
            f"execution_id={fallback_context.get('fallback_execution_id') or fallback_context['execution_id']}"
        )
        if suffix:
            return f"{prefix}/{suffix.strip('/')}"
        return prefix


    def _minio_uri(self, object_key: str) -> str:
        """Converte object key do bucket configurado para URI minio://."""
        config = self.config_loader.load_local_platform_config()
        return f"minio://{config.minio_bucket}/{object_key}"


    def _parse_minio_uri(self, uri_or_key: str) -> str:
        """Aceita object key ou URI do bucket configurado para contratos externos."""
        value = str(uri_or_key).strip()
        if not value.startswith("minio://"):
            return value
        config = self.config_loader.load_local_platform_config()
        prefix = f"minio://{config.minio_bucket}/"
        if not value.startswith(prefix):
            raise RuntimeError("contrato_semantico_uri aponta para bucket MinIO diferente do configurado.")
        return value.removeprefix(prefix)


    @staticmethod
    def _loaded_fallback_context(loaded_context: dict[str, Any]) -> dict[str, str]:
        """Extrai o contexto validado retornado por load_fallback_context."""
        fallback_context = loaded_context.get("fallback_context", {})
        if not isinstance(fallback_context, dict):
            raise RuntimeError("Contexto carregado sem fallback_context.")
        entity_slug = str(
            fallback_context.get("entity_slug") or fallback_context.get("company_slug") or ""
        ).strip()
        if not entity_slug:
            raise RuntimeError("fallback_context sem campo obrigatorio: entity_slug")
        required = ("document_id", "execution_id", "manifest_key")
        cleaned: dict[str, str] = {}
        cleaned["entity_slug"] = entity_slug
        for field in required:
            value = str(fallback_context.get(field, "")).strip()
            if not value:
                raise RuntimeError(f"fallback_context sem campo obrigatorio: {field}")
            cleaned[field] = value
        for optional in ("domain", "fallback_execution_id", "source_execution_id", "fallback_mode", "motivo", "entity_name", "contrato_semantico_uri"):
            value = str(fallback_context.get(optional, "")).strip()
            if value:
                cleaned[optional] = value
        return cleaned


    @staticmethod
    def _fallback_context_from_revalidation_conf(
        revalidation_conf: dict[str, Any],
    ) -> dict[str, str]:
        """Normaliza o contexto a partir do conf usado para revalidar."""
        return {
            "domain": str(revalidation_conf.get("domain", "")).strip(),
            "entity_slug": str(
                revalidation_conf.get("entity_slug") or revalidation_conf["company_slug"]
            ),
            "document_id": str(revalidation_conf["document_id"]),
            "execution_id": str(revalidation_conf["execution_id"]),
            "manifest_key": str(revalidation_conf["manifest_key"]),
            "fallback_execution_id": str(
                revalidation_conf.get("fallback_execution_id")
                or revalidation_conf["execution_id"]
            ),
            "source_execution_id": str(
                revalidation_conf.get("source_execution_id")
                or revalidation_conf["execution_id"]
            ),
        }


    @staticmethod
    def _candidate_updated_sections(candidate: dict[str, Any]) -> list[str]:
        """Lista secoes do layout alteraveis presentes no candidato."""
        sections = [
            "fontes_relevantes",
            "regras_deteccao_mudanca",
            "mapeamento_canonico",
            "metadados_estruturais_evidencia",
        ]
        return [section for section in sections if section in candidate]


    @staticmethod
    def _should_select_artifacts_with_llm(
        fallback_problem_context: dict[str, Any],
    ) -> bool:
        """Indica se o fallback deve fazer a chamada previa de selecao de artefatos."""
        constraints = fallback_problem_context.get("llm_constraints", {})
        if not isinstance(constraints, dict):
            return False
        return bool(constraints.get("selecionar_artefatos_por_llm_usando_inventario"))


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
        key = self._current_layout_signature_object_key(
            fallback_context["entity_slug"],
            domain=fallback_context.get("domain", "construtoras"),
        )
        return key, self._load_json_object(key, "layout_signature_base")


    def load_semantic_contract(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o contrato ativo do dominio, sem prender o fallback ao manifesto historico."""
        config = self.config_loader.load_local_platform_config()
        domain = str(fallback_context.get("domain") or config.dominio).strip()
        historical_uri = str(fallback_context.get("contrato_semantico_uri", "")).strip()
        contract_uri, _version = SemanticContractRegistry(
            config=config,
            minio_client=self.minio_client,
        ).latest_contract_uri(domain)
        if historical_uri and historical_uri != contract_uri:
            logging.info(
                "Contrato historico do manifesto substituido pelo contrato ativo do dominio "
                "na DAG 3: historico=%s ativo=%s",
                historical_uri,
                contract_uri,
            )
        fallback_context["contrato_semantico_uri"] = contract_uri
        key = self._parse_minio_uri(contract_uri)
        return key, self._load_json_object(key, "contrato_semantico")


    def load_extraction_manifest(self, fallback_context: dict[str, str]) -> tuple[str, dict[str, Any]]:
        """Le o manifesto de extracao para localizar os artefatos da DAG 1."""
        key = fallback_context["manifest_key"]
        return key, self._load_json_object(key, "manifesto_extracao")


    def _resolution_artifact_key(self, fallback_context: dict[str, str], filename: str) -> str:
        """Monta o object key de um artefato de resolucao da DAG 2."""
        config = self.config_loader.load_local_platform_config()
        return (
            f"{self._prefix_for_domain(config.minio_resolution_prefix, fallback_context.get('domain', config.dominio))}/{fallback_context['entity_slug']}/"
            f"document_id={fallback_context['document_id']}/"
            f"execution_id={fallback_context['execution_id']}/resolution/{filename}"
        )


    def _current_layout_signature_object_key(self, entity_slug: str, *, domain: str = "construtoras") -> str:
        """Resolve pelo ponteiro `current.json` qual layout vigente carregar."""
        pointer_key = self._current_layout_pointer_object_key(entity_slug, domain=domain)
        pointer = self._load_json_object(pointer_key, "layout_signature_current_pointer")
        object_key = str(pointer.get("object_key", "")).strip()
        if not object_key:
            raise RuntimeError(
                f"Ponteiro de layout vigente sem object_key: {pointer_key}"
            )
        return object_key


    def _current_layout_pointer_object_key(self, entity_slug: str, *, domain: str = "construtoras") -> str:
        """Object key do ponteiro de layout vigente."""
        config = self.config_loader.load_local_platform_config()
        return f"{self._prefix_for_domain(config.minio_layout_prefix, domain)}/{entity_slug}/current.json"


    @staticmethod
    def _prefix_for_domain(configured_prefix: str, domain: str) -> str:
        parts = configured_prefix.strip("/").split("/")
        if len(parts) >= 2:
            parts[1] = str(domain).strip().lower()
        return "/".join(parts)


    def _load_json_object(self, object_key: str, artifact_name: str) -> dict[str, Any]:
        """Le um JSON do MinIO e adiciona contexto ao erro de carregamento."""
        try:
            loaded = self.minio_client.get_json(object_key=object_key)
        except Exception as exc:
            raise RuntimeError(
                f"Nao foi possivel carregar {artifact_name} no MinIO: {object_key}"
            ) from exc
        return loaded


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
